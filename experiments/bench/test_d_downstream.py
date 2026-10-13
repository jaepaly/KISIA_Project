"""d_downstream.py 테스트 — 실제 시그니처 spy · 실제 하위 test guard · 상태 전파 · --final 회귀(mock) · 패키지 import."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# experiments/bench 를 먼저 붙여 d_downstream 을 바로 import 할 수 있게 한다
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import d_downstream  # noqa: E402
import d_risk_action  # noqa: E402
import d_stage2  # noqa: E402

META = {"preds_sha256": "abc", "n_users": 1, "n_posts": 2,
        "measured_at": "2026-10-13T00:00:00+00:00", "git_commit": "deadbeef"}
ABLS = ["single_vs_account", "explicit_removed"]


# ── 실제 시그니처 spy ──────────────────────────────────────────────

def _spy_modules() -> tuple[ModuleType, ModuleType]:
    """실제 함수 시그니처를 그대로 따르는 spy(autospec) — 없는 인자를 넘기면 TypeError 가 난다."""
    s2 = ModuleType("d_stage2")
    s2.run_stage2 = mock.create_autospec(d_stage2.run_stage2, return_value={"meta": META, "stage2_mode": "rules"})
    s2.compare_stage2 = mock.create_autospec(d_stage2.compare_stage2, return_value={"verdict_agreement": 1.0})
    s2.exp09_commands = d_stage2.exp09_commands
    s2.exp09_outputs = d_stage2.exp09_outputs
    s2.exp09_config_files = d_stage2.exp09_config_files
    s2.EXP09_ENV = d_stage2.EXP09_ENV
    ra = ModuleType("d_risk_action")
    ra.run_risk_action = mock.create_autospec(d_risk_action.run_risk_action, return_value={"meta": META})
    ra.run_ablation = mock.create_autospec(
        d_risk_action.run_ablation, side_effect=lambda name, *a, **k: {"meta": META, "ablation_name": name})
    ra.regression_commands = d_risk_action.regression_commands
    ra.regression_outputs = d_risk_action.regression_outputs
    return s2, ra


@pytest.fixture()
def spies():
    s2, ra = _spy_modules()
    with mock.patch.dict(sys.modules, {"d_stage2": s2, "d_risk_action": ra}):
        yield s2, ra


@pytest.fixture()
def fake_preds(tmp_path: Path) -> Path:
    """dev 예측 JSONL — 실제 test 목록에 없는 글 두 편 (A01_b01 · A01_b03)."""
    rows = [
        {"post_id": "A01_b01", "spans": []},
        {"post_id": "A01_b03", "spans": [{"text_id": "body", "start": 0, "end": 3, "type": "LOC_ADMIN", "text": "서울", "level": "explicit", "subject": "self"}]},
    ]
    p = tmp_path / "preds_dev.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return p


def _fake_splits(tmp_path: Path, ids: list[str]) -> Path:
    ids = ids + [f"T00_b{i:03d}" for i in range(255 - len(ids))]
    p = tmp_path / "test_post_ids.json"
    p.write_text(json.dumps({"note": "가짜", "post_ids": ids}), encoding="utf-8")
    return p


def _statuses(result: dict) -> list[str]:
    out = [result[k]["status"] for k in ("stage2", "risk_action", "stage2_compare") if k in result]
    for group in ("ablations", "regressions"):
        out += [v["status"] for v in (result.get(group) or {}).values()]
    return out


# ── 묶기 ────────────────────────────────────────────────────────

class TestEndToEnd:
    def test_basic_run(self, spies, fake_preds: Path, tmp_path: Path) -> None:
        result = d_downstream.run_downstream(fake_preds, tmp_path / "out", stage2_mode="rules", ablations=[])
        assert result["stage2"]["status"] == "ok" and result["stage2"]["stage2_mode"] == "rules"
        assert result["risk_action"]["status"] == "ok"
        assert "regressions" not in result  # --final 이 아니면 회귀를 돌리지 않는다
        assert (tmp_path / "out" / "metrics_downstream.json").exists()

    def test_ablation_run(self, spies, fake_preds: Path, tmp_path: Path) -> None:
        result = d_downstream.run_downstream(fake_preds, tmp_path / "out", ablations=ABLS)
        for name in ABLS:
            assert result["ablations"][name]["ablation_name"] == name
            assert result["ablations"][name]["status"] == "ok"

    def test_fingerprint_fields(self, spies, fake_preds: Path, tmp_path: Path) -> None:
        fp = d_downstream.run_downstream(fake_preds, tmp_path / "out")["fingerprint"]
        for key in ("preds_sha256", "n_posts", "n_users", "git_commit",
                    "model_version", "stage2_target_risk", "stage2_mode", "measured_at"):
            assert key in fp, f"지문 필드 누락: {key}"


class TestAllowTestPassed:
    """allow_test 가 lazy wrapper 를 거쳐 하위 공개 함수 전부에 들어간다 (리뷰 1 · 8)."""

    @pytest.mark.parametrize("allow", [False, True])
    def test_spy_receives_allow_test(self, spies, fake_preds: Path, tmp_path: Path, allow: bool) -> None:
        s2, ra = spies
        result = d_downstream.run_downstream(fake_preds, tmp_path / "out", ablations=ABLS, allow_test=allow)
        assert s2.run_stage2.call_args.kwargs["allow_test"] is allow
        assert ra.run_risk_action.call_args.kwargs["allow_test"] is allow
        assert [c.kwargs["allow_test"] for c in ra.run_ablation.call_args_list] == [allow, allow]
        assert set(_statuses(result)) == {"ok"}

    def test_final_turns_on_allow_test(self, spies, fake_preds: Path, tmp_path: Path) -> None:
        s2, ra = spies
        runner = mock.Mock(return_value=SimpleNamespace(returncode=0))
        with mock.patch.object(d_stage2, "EXP09", tmp_path / "exp09"):
            d_downstream.run_downstream(fake_preds, tmp_path / "out", final=True, runner=runner)
        assert s2.run_stage2.call_args.kwargs["allow_test"] is True
        assert ra.run_risk_action.call_args.kwargs["allow_test"] is True


class TestRealGuard:
    """합성 test ID 로 실제 d_stage2 · d_risk_action 의 test guard 까지 연결한다."""

    @pytest.fixture()
    def synth(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        pid = "Z99_t01"
        splits = _fake_splits(tmp_path, [pid])
        fake_ids = frozenset(json.loads(splits.read_text(encoding="utf-8"))["post_ids"])
        monkeypatch.setattr(d_downstream, "SPLITS", splits)
        monkeypatch.setattr(d_stage2, "SPLITS", splits)
        monkeypatch.setattr(d_stage2, "load_corpus", lambda *a, **k: {
            pid: {"post_id": pid, "persona_id": "Z99", "texts": {"title": "제목", "body": "오늘은 날씨가 좋았다."}}})
        monkeypatch.setattr(d_risk_action, "load_test_ids", lambda *a, **k: fake_ids)
        monkeypatch.setattr(d_risk_action, "seed_geo_tags", lambda: {})
        preds = tmp_path / "preds_test.jsonl"
        preds.write_text(json.dumps({"post_id": pid, "spans": []}) + "\n", encoding="utf-8")
        return preds

    def test_lower_guard_blocks_without_allow(self, synth: Path, tmp_path: Path) -> None:
        r = d_downstream._lazy_stage2(synth, tmp_path / "s2", mode="rules", allow_test=False)
        assert r["status"] == "failed" and "test 글" in r["error"]
        r = d_downstream._lazy_risk_action(synth, tmp_path / "ra", allow_test=False)
        assert r["status"] == "failed" and "test 글" in r["error"]
        r = d_downstream._lazy_ablation("explicit_removed", synth, tmp_path / "ab", allow_test=False)
        assert r["status"] == "failed" and "test 글" in r["error"]

    def test_top_guard_stops_without_final(self, synth: Path, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            d_downstream.run_downstream(synth, tmp_path / "out", allow_test=False)

    def test_allow_test_reaches_real_guard(self, synth: Path, tmp_path: Path) -> None:
        result = d_downstream.run_downstream(synth, tmp_path / "out", ablations=ABLS, allow_test=True)
        assert set(_statuses(result)) == {"ok"}, result
        assert not any("skipped" in v for v in [result["stage2"], result["risk_action"], *result["ablations"].values()])
        assert result["stage2"]["meta"]["n_test_posts"] == 1


class TestStatus:
    """모듈 파일이 없을 때만 skipped — 그 밖은 failed · CLI 종료 코드 1 (리뷰 2)."""

    def test_missing_module_is_skipped(self, fake_preds: Path, tmp_path: Path) -> None:
        _, ra = _spy_modules()
        with mock.patch.dict(sys.modules, {"d_stage2": None, "d_risk_action": ra}):
            result = d_downstream.run_downstream(fake_preds, tmp_path / "out")
        assert result["stage2"]["status"] == "skipped" and "모듈 없음" in result["stage2"]["skipped"]
        assert result["risk_action"]["status"] == "ok"
        assert d_downstream.failures(result) == []

    def test_both_missing_still_writes_json(self, fake_preds: Path, tmp_path: Path) -> None:
        with mock.patch.dict(sys.modules, {"d_stage2": None, "d_risk_action": None}):
            result = d_downstream.run_downstream(fake_preds, tmp_path / "out", ablations=["single_vs_account"])
        assert (tmp_path / "out" / "metrics_downstream.json").exists()
        assert result["ablations"]["single_vs_account"]["status"] == "skipped"

    def test_inner_missing_dependency_is_failed(self, fake_preds: Path, tmp_path: Path) -> None:
        """모듈 안에서 다른 패키지가 없으면(e.name 이 다름) skipped 가 아니라 failed."""
        real_import = d_downstream.importlib.import_module

        def fake_import(name: str, *a):
            if name == "d_stage2":
                raise ModuleNotFoundError("No module named 'peft'", name="peft")
            return real_import(name, *a)
        _, ra = _spy_modules()
        with mock.patch.dict(sys.modules, {"d_risk_action": ra}), \
                mock.patch.object(d_downstream.importlib, "import_module", fake_import):
            result = d_downstream.run_downstream(fake_preds, tmp_path / "out")
        assert result["stage2"]["status"] == "failed" and "peft" in result["stage2"]["error"]
        assert d_downstream.failures(result) == ["stage2"]

    def test_runtime_error_fails_cli(self, spies, fake_preds: Path, tmp_path: Path, capsys) -> None:
        s2, ra = spies
        s2.run_stage2.side_effect = RuntimeError("모델 로드 실패")
        code = d_downstream.main(["--preds", str(fake_preds), "--out", str(tmp_path / "out")])
        assert code == 1
        assert "stage2: FAILED" in capsys.readouterr().out

    def test_nested_ablation_failure_fails_cli(self, spies, fake_preds: Path, tmp_path: Path, capsys) -> None:
        s2, ra = spies
        ra.run_ablation.side_effect = ValueError("계산 오류")
        code = d_downstream.main(["--preds", str(fake_preds), "--out", str(tmp_path / "out"),
                                  "--ablation", "single_vs_account"])
        assert code == 1
        assert "ablations.single_vs_account: FAILED" in capsys.readouterr().out

    def test_ok_cli_returns_zero(self, spies, fake_preds: Path, tmp_path: Path) -> None:
        assert d_downstream.main(["--preds", str(fake_preds), "--out", str(tmp_path / "out")]) == 0


def _fake_file(path: Path, *, adapter_sha: str | None = None, broken: bool = False,
               cfg: dict[str, str] | None = None) -> None:
    """확장자에 맞게 읽히는 가짜 산출물 — broken 이면 파싱이 안 되게. meta 는 run_config.py 와 같은 키."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if broken:
        path.write_text("{깨짐", encoding="utf-8")
    elif path.name.endswith("_meta.json"):
        path.write_text(json.dumps({"config": "v2", "adapter_sha256": adapter_sha, **(cfg or {})}), encoding="utf-8")
    elif path.suffix == ".json":
        path.write_text('{"ok": 1}', encoding="utf-8")
    elif path.suffix == ".jsonl":
        path.write_text('{"ok": 1}\n', encoding="utf-8")
    else:
        path.write_text("a,b\n1,2\n", encoding="utf-8")


class TestFinalRegressions:
    """--final 에서만 exp09 · exp10 · exp11 — subprocess 는 mock · exp09 는 덮어쓰지 않는다 (R2 1 · 3 · 5)."""

    @pytest.fixture()
    def env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
        exp09 = tmp_path / "exp09"
        monkeypatch.setattr(d_stage2, "EXP09", exp09)
        adapter = tmp_path / "adapter_v2"
        adapter.mkdir()
        (adapter / "adapter_model.safetensors").write_bytes(b"weights")
        out = tmp_path / "out"
        gen, meta, metrics = d_stage2.exp09_outputs("v2")
        cfg_files = d_stage2.exp09_config_files()  # 입력 · 외부 판정 (실제로는 .gitignore)
        for p in cfg_files.values():
            _fake_file(p)
        return SimpleNamespace(exp09=exp09, adapter=adapter, sha=d_downstream._sha256(adapter / "adapter_model.safetensors"),
                               out=out, gen=gen, meta=meta, metrics=metrics, cfg_files=cfg_files,
                               cfg={k: d_downstream._sha256(p) for k, p in cfg_files.items()},
                               required=d_risk_action.regression_outputs(out / "regressions"))

    def _writer(self, env: SimpleNamespace, *, skip: tuple[str, ...] = (), broken: tuple[str, ...] = ()):
        """명령별로 그 스크립트가 쓰는 파일을 가짜로 만드는 runner (종료 코드 0)."""
        req = env.required
        files = {
            ("exp09", "run_config.py"): [env.gen, env.meta], ("exp09", "score.py"): [env.metrics],
            ("exp10", "build_inputs.py"): req["exp10"],
            ("exp11", "score.py"): req["exp11"][:2], ("exp11", "sensitivity.py"): req["exp11"][2:],
        }

        def run(cmd, **kw):
            exp = next(e for e in ("exp09", "exp10", "exp11") if e in cmd[1])
            for f in files[(exp, Path(cmd[1]).name)]:
                if f.name not in skip:
                    _fake_file(f, adapter_sha=env.sha, broken=f.name in broken)
            return SimpleNamespace(returncode=0)
        return mock.Mock(side_effect=run)

    def _run(self, fake_preds: Path, env: SimpleNamespace, runner, *, final: bool = True) -> dict:
        return d_downstream.run_downstream(fake_preds, env.out, final=final, runner=runner, adapter=env.adapter)

    def test_all_run_and_hashes(self, spies, fake_preds: Path, env: SimpleNamespace) -> None:
        r = self._run(fake_preds, env, self._writer(env))["regressions"]
        assert {k: v["status"] for k, v in r.items()} == {"exp09": "ok", "exp10": "ok", "exp11": "ok"}
        e9 = r["exp09"]
        assert [Path(c["cmd"][1]).name for c in e9["commands"]] == ["run_config.py", "score.py"]
        assert e9["commands"][0]["cmd"][-2:] == ["--adapter", str(env.adapter)]  # 2단과 같은 어댑터를 명시
        assert e9["adapter_sha256"] == env.sha
        assert all(e9["outputs"][str(f)] for f in (env.gen, env.meta, env.metrics))  # SHA-256 3종
        for k in ("exp10", "exp11"):
            assert set(r[k]["outputs"]) == {str(f) for f in env.required[k]} and all(r[k]["outputs"].values())
        names = [Path(c["cmd"][1]).name for k in ("exp10", "exp11") for c in r[k]["commands"]]
        assert names == ["build_inputs.py", "score.py", "sensitivity.py"] and "run_teacher.py" not in names

    def test_exit0_but_missing_outputs_fails(self, spies, fake_preds: Path, env: SimpleNamespace) -> None:
        runner = self._writer(env, skip=("metrics_cfg_v2.json", "preview.json", "sensitivity_v1_rules_metrics.json"))
        r = self._run(fake_preds, env, runner)["regressions"]
        for k, missing in (("exp09", "metrics_cfg_v2.json"), ("exp10", "preview.json"),
                           ("exp11", "sensitivity_v1_rules_metrics.json")):
            assert r[k]["status"] == "failed" and all(c["returncode"] == 0 for c in r[k]["commands"])
            assert "필수 산출물" in r[k]["error"] and missing in r[k]["error"]

    def test_exit0_but_unparsable_fails(self, spies, fake_preds: Path, env: SimpleNamespace) -> None:
        r = self._run(fake_preds, env, self._writer(env, broken=("preview.json",)))["regressions"]
        assert r["exp10"]["status"] == "failed" and "읽기 실패" in r["exp10"]["error"]
        assert r["exp11"]["status"] == "ok"

    def test_cli_exit0_missing_outputs_returns_1(self, spies, fake_preds: Path, env: SimpleNamespace) -> None:
        """CLI --final — 명령은 모두 0 인데 산출물이 없으면 종료 코드 1."""
        with mock.patch.object(d_downstream.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            code = d_downstream.main(["--preds", str(fake_preds), "--out", str(env.out), "--final",
                                      "--adapter", str(env.adapter)])
        assert code == 1

    def test_exp09_existing_verified(self, spies, fake_preds: Path, env: SimpleNamespace) -> None:
        _fake_file(env.meta, adapter_sha=env.sha, cfg=env.cfg)
        _fake_file(env.metrics)
        runner = self._writer(env)
        e9 = self._run(fake_preds, env, runner)["regressions"]["exp09"]
        assert e9["status"] == "existing_verified" and e9["commands"] == []
        assert e9["outputs"][str(env.gen)] is None and e9["outputs"][str(env.meta)] and e9["outputs"][str(env.metrics)]
        assert "재사용" in e9["message"]
        assert not any("exp09" in c.args[0][1] for c in runner.call_args_list)

    @pytest.mark.parametrize("case", ["other_adapter", "only_gen", "only_metrics", "adapter_unknown"])
    def test_exp09_never_overwrites(self, spies, fake_preds: Path, env: SimpleNamespace, case: str) -> None:
        if case == "other_adapter":
            _fake_file(env.meta, adapter_sha="0" * 64)
            _fake_file(env.metrics)
        elif case == "only_gen":
            _fake_file(env.gen)
        elif case == "only_metrics":
            _fake_file(env.metrics)
        else:  # meta · metrics 는 있는데 이번 어댑터 SHA 를 확인할 수 없다
            _fake_file(env.meta, adapter_sha=env.sha)
            _fake_file(env.metrics)
            (env.adapter / "adapter_model.safetensors").unlink()
        before = {f: f.read_bytes() for f in (env.gen, env.meta, env.metrics) if f.exists()}
        runner = self._writer(env)
        e9 = self._run(fake_preds, env, runner)["regressions"]["exp09"]
        assert e9["status"] == "failed" and "덮어쓰지 않는다" in e9["error"] and e9["commands"] == []
        assert not any("exp09" in c.args[0][1] for c in runner.call_args_list)
        assert {f: f.read_bytes() for f in (env.gen, env.meta, env.metrics) if f.exists()} == before

    @pytest.mark.parametrize("case", ["inputs_differ", "external_differ", "files_missing"])
    def test_exp09_config_files_checked(self, spies, fake_preds: Path, env: SimpleNamespace, case: str) -> None:
        """어댑터가 같아도 입력 · 외부 판정 SHA 가 meta 와 다르거나 파일이 없으면 재사용하지 않는다 (R3 ①)."""
        cfg = dict(env.cfg)
        if case == "inputs_differ":
            cfg["inputs_sha256"] = "0" * 64
        elif case == "external_differ":
            cfg["external_sha256"] = "0" * 64
        else:  # 이 PC 처럼 .gitignore 라 파일이 없다
            for p in env.cfg_files.values():
                p.unlink()
        _fake_file(env.meta, adapter_sha=env.sha, cfg=cfg)
        _fake_file(env.metrics)
        before = {f: f.read_bytes() for f in (env.meta, env.metrics)}
        runner = self._writer(env)
        e9 = self._run(fake_preds, env, runner)["regressions"]["exp09"]
        assert e9["status"] == "failed" and e9["commands"] == []
        want = ("입력 · 외부 판정 파일이 없어 저장 결과의 구성을 확인할 수 없다" if case == "files_missing"
                else "입력 · 외부 판정 SHA 가 meta 와 다름")
        assert want in e9["error"]
        assert not any("exp09" in c.args[0][1] for c in runner.call_args_list)
        assert {f: f.read_bytes() for f in (env.meta, env.metrics)} == before

    def test_exp09_failure_propagates(self, spies, fake_preds: Path, env: SimpleNamespace) -> None:
        runner = mock.Mock(return_value=SimpleNamespace(returncode=3))
        e9 = self._run(fake_preds, env, runner)["regressions"]["exp09"]
        assert e9["status"] == "failed" and len(e9["commands"]) == 1  # 첫 명령 실패에서 멈춘다

    def test_not_run_without_final(self, spies, fake_preds: Path, env: SimpleNamespace) -> None:
        runner = mock.Mock()
        assert "regressions" not in self._run(fake_preds, env, runner, final=False)
        runner.assert_not_called()


class TestAdapter:
    """어댑터를 한 번 해석해 2단과 exp09 에 같은 경로 · 지문에 경로와 SHA (R2 2)."""

    @pytest.fixture()
    def adapter(self, tmp_path: Path) -> Path:
        a = tmp_path / "ckpt" / "adapter_v2"
        a.mkdir(parents=True)
        (a / "adapter_model.safetensors").write_bytes(b"w")
        return a

    def test_model_mode_same_adapter(self, spies, fake_preds: Path, tmp_path: Path, adapter: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
        s2, _ = spies
        monkeypatch.setattr(d_stage2, "EXP09", tmp_path / "exp09")
        runner = mock.Mock(return_value=SimpleNamespace(returncode=1))
        r = d_downstream.run_downstream(fake_preds, tmp_path / "out", stage2_mode="model", adapter=adapter,
                                        final=True, runner=runner)
        assert s2.run_stage2.call_args.kwargs["adapter"] == adapter
        fp = r["fingerprint"]
        assert fp["stage2_adapter"] == str(adapter)
        assert fp["stage2_adapter_sha256"] == d_downstream._sha256(adapter / "adapter_model.safetensors")
        gen_cmd = runner.call_args_list[0].args[0]
        assert Path(gen_cmd[1]).name == "run_config.py" and gen_cmd[-2:] == ["--adapter", str(adapter)]
        assert r["regressions"]["exp09"]["adapter_sha256"] == fp["stage2_adapter_sha256"]

    def test_env_adapter_when_no_arg(self, spies, fake_preds: Path, tmp_path: Path, adapter: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
        s2, _ = spies
        monkeypatch.setenv("STAGE2_ADAPTER_DIR", str(adapter))
        r = d_downstream.run_downstream(fake_preds, tmp_path / "out", stage2_mode="model")
        assert Path(s2.run_stage2.call_args.kwargs["adapter"]) == adapter
        assert r["fingerprint"]["stage2_adapter"] == str(adapter)

    def test_rules_mode_null(self, spies, fake_preds: Path, tmp_path: Path, adapter: Path,
                             monkeypatch: pytest.MonkeyPatch) -> None:
        s2, _ = spies
        monkeypatch.setenv("STAGE2_ADAPTER_DIR", str(adapter))
        monkeypatch.setattr(d_stage2, "EXP09", tmp_path / "exp09")
        runner = mock.Mock(return_value=SimpleNamespace(returncode=1))
        r = d_downstream.run_downstream(fake_preds, tmp_path / "out", stage2_mode="rules", final=True, runner=runner)
        assert s2.run_stage2.call_args.kwargs["adapter"] is None
        assert r["fingerprint"]["stage2_adapter"] is None and r["fingerprint"]["stage2_adapter_sha256"] is None
        # exp09 는 같은 순서(STAGE2_ADAPTER_DIR)로 해석한 어댑터를 명시해서 받는다
        assert runner.call_args_list[0].args[0][-2:] == ["--adapter", str(adapter)]


class TestTargetRisk:
    """STAGE2_TARGET_RISK 를 한 번 float 로 해석해 지문과 계산에 같은 값 (리뷰 5)."""

    def test_same_value(self, spies, fake_preds: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, ra = spies
        monkeypatch.setenv("STAGE2_TARGET_RISK", "20")
        result = d_downstream.run_downstream(fake_preds, tmp_path / "out")
        assert result["fingerprint"]["stage2_target_risk"] == 20.0
        assert ra.run_risk_action.call_args.kwargs["app_target"] == 20.0

    @pytest.mark.parametrize("bad", ["abc", "150", "nan"])
    def test_invalid(self, spies, fake_preds: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
        monkeypatch.setenv("STAGE2_TARGET_RISK", bad)
        with pytest.raises(ValueError):
            d_downstream.run_downstream(fake_preds, tmp_path / "out")


class TestCompareStage2:
    """ablation ④ — --compare-stage2 로 두 실행의 verdict 일치율 (리뷰 7)."""

    def test_connects_to_compare(self, spies, fake_preds: Path, tmp_path: Path) -> None:
        s2, _ = spies
        other = tmp_path / "other"
        (other / "stage2").mkdir(parents=True)
        (other / "stage2" / "stage2_preds.jsonl").write_text("", encoding="utf-8")
        result = d_downstream.run_downstream(fake_preds, tmp_path / "out", compare_stage2=other)
        assert result["stage2_compare"]["status"] == "ok"
        a, b = s2.compare_stage2.call_args.args
        assert Path(a) == tmp_path / "out" / "stage2" / "stage2_preds.jsonl"
        assert Path(b) == other / "stage2" / "stage2_preds.jsonl"

    def test_same_folder_fails_before_writing(self, spies, fake_preds: Path, tmp_path: Path) -> None:
        """같은 파일이면 측정 전에 멈춘다 — 하위 측정 미호출 · 기존 파일 바이트 그대로 · CLI 종료 코드 1."""
        s2, ra = spies
        out = tmp_path / "out"
        prev = out / "stage2" / "stage2_preds.jsonl"
        prev.parent.mkdir(parents=True)
        prev.write_bytes(b'{"user_ref": "u_first"}\n')
        with pytest.raises(SystemExit) as e:
            d_downstream.main(["--preds", str(fake_preds), "--out", str(out), "--compare-stage2", str(out),
                               "--ablation", "single_vs_account"])
        assert isinstance(e.value.code, str) and "--out" in e.value.code  # 문자열 SystemExit = 종료 코드 1
        s2.run_stage2.assert_not_called()
        ra.run_risk_action.assert_not_called()
        ra.run_ablation.assert_not_called()
        assert prev.read_bytes() == b'{"user_ref": "u_first"}\n'
        assert not (out / "metrics_downstream.json").exists()

    def test_missing_target_fails_before_writing(self, spies, fake_preds: Path, tmp_path: Path) -> None:
        s2, _ = spies
        with pytest.raises(SystemExit):
            d_downstream.run_downstream(fake_preds, tmp_path / "out", compare_stage2=tmp_path / "없는폴더")
        s2.run_stage2.assert_not_called()
        assert not (tmp_path / "out").exists()


def test_package_import_finds_siblings(tmp_path: Path) -> None:
    """새 프로세스 · PYTHONPATH=src · 저장소 루트에서 패키지 import 로 불러도 형제 모듈을 찾는다 (리뷰 4)."""
    test_ids = set(d_stage2.load_test_ids())
    pid = next(p for p in sorted(d_stage2.load_corpus()) if p not in test_ids)  # dev 글 한 편
    preds = tmp_path / "preds.jsonl"
    preds.write_text(json.dumps({"post_id": pid, "spans": []}) + "\n", encoding="utf-8")
    code = (
        "import json, sys\n"
        "from experiments.bench.d_downstream import run_downstream\n"
        f"r = run_downstream({str(preds)!r}, {str(tmp_path / 'out')!r}, ablations=['explicit_removed'])\n"
        "print(json.dumps([r['stage2']['status'], r['risk_action']['status'], "
        "r['ablations']['explicit_removed']['status']]))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    cp = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                        encoding="utf-8", timeout=300)
    assert cp.returncode == 0, cp.stderr
    assert json.loads(cp.stdout.strip().splitlines()[-1]) == ["ok", "ok", "ok"]
