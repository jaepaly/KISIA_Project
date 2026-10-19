"""run_all.py 테스트 — 모델 · test 본문 없이 1단 명령 조립 · test 보호 · 예측 변환 · 단계 연결을 확인한다."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import d_downstream  # noqa: E402
import run_all  # noqa: E402

TEST_IDS = json.loads((run_all.ROOT / "data/corpus/v0/splits/test_post_ids.json").read_text(encoding="utf-8"))["post_ids"]
STAGE1 = ["--checkpoint-dir", "ckpt", "--limit", "4"]


@pytest.fixture()
def out(tmp_path: Path) -> Path:
    """experiments 아래 runs/ 규칙을 통과하는 새 경로 — 테스트 뒤 지운다."""
    import shutil
    base = run_all.ROOT / "experiments" / "bench" / "runs" / f"_pytest_{tmp_path.name}"
    yield base
    shutil.rmtree(base, ignore_errors=True)


def _fake_stage1(rows: list[dict], ckpt: str = "ckpt"):
    """run.py 대신 — predictions.jsonl(candidates) · metrics.json 을 쓰고 0 을 낸다."""
    calls = []

    def runner(cmd: list[str]) -> int:
        calls.append(cmd)
        d = Path(cmd[cmd.index("--output-dir") + 1])
        d.mkdir(parents=True)
        (d / "predictions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                            encoding="utf-8")
        (d / "metrics.json").write_text(json.dumps({"checkpoint": ckpt, "extensions": {}}), encoding="utf-8")
        return 0
    return runner, calls


# ── 1단 명령 · test 보호 ─────────────────────────────────────────────

def test_stage1_command_forces_train_without_final(tmp_path: Path):
    cmd = run_all.stage1_command(STAGE1, tmp_path, final=False)
    assert cmd[cmd.index("--split") + 1] == "train" and "--final-test-confirm" not in cmd
    assert cmd[cmd.index("--output-dir") + 1] == str(tmp_path / "stage1")


def test_stage1_command_final_opens_test(tmp_path: Path):
    cmd = run_all.stage1_command(STAGE1, tmp_path, final=True)
    assert cmd[cmd.index("--split") + 1] == "test" and "--final-test-confirm" in cmd


@pytest.mark.parametrize("tok", ["--split", "--split=test", "--spl", "--final-test-confirm", "--final-t", "--f",
                                 "--output-dir", "--out"])
def test_reserved_stage1_options_stop(tok: str, tmp_path: Path):
    with pytest.raises(SystemExit):
        run_all.stage1_command([*STAGE1, tok, "test"], tmp_path, final=False)


def test_split_test_stops_before_writing(out: Path):
    runner, calls = _fake_stage1([])
    with pytest.raises(SystemExit):
        run_all.main(["--output-dir", str(out), "--", *STAGE1, "--split", "test"], stage1_runner=runner)
    assert not calls and not out.exists()


def test_final_with_preds_is_refused(out: Path, tmp_path: Path):
    p = tmp_path / "p.jsonl"
    p.write_text('{"post_id": "A01_b01", "spans": []}\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        run_all.main(["--final", "--output-dir", str(out), "--preds", str(p)])


def test_final_stage1_dir_needs_official_test_output(out: Path, tmp_path: Path):
    (tmp_path / "predictions.jsonl").write_text('{"post_id": "A01_b01", "candidates": []}' + chr(10), encoding="utf-8")
    (tmp_path / "metrics.json").write_text('{"scope": "development_smoke_not_final"}', encoding="utf-8")
    with pytest.raises(SystemExit, match="official_test"):
        run_all.main(["--final", "--output-dir", str(out), "--stage1-dir", str(tmp_path)], downstream=_spy_downstream())
    assert not out.exists()


def test_final_stage1_dir_reuses_test_output(out: Path, tmp_path: Path):
    (tmp_path / "predictions.jsonl").write_text('{"post_id": "A01_b01", "candidates": []}' + chr(10), encoding="utf-8")
    (tmp_path / "metrics.json").write_text('{"scope": "official_test", "checkpoint": "ck"}', encoding="utf-8")
    ds = _spy_downstream()
    assert run_all.main(["--final", "--output-dir", str(out), "--stage1-dir", str(tmp_path)], downstream=ds) == 0
    kw = ds.run_downstream.call_args.kwargs
    assert kw["final"] is True and kw["allow_test"] is True and kw["c1_checkpoint"] == Path("ck")
    # 재사용한 1단 출력은 고치지 않는다
    assert "extensions" not in json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))


def test_existing_or_outside_output_dir_is_refused(tmp_path: Path):
    with pytest.raises(SystemExit):
        run_all.check_output_dir(tmp_path / "runs" / "x")  # experiments 밖
    with pytest.raises(SystemExit):
        run_all.check_output_dir(run_all.ROOT / "experiments" / "bench")  # 이미 있음 · runs 없음


def test_test_post_without_final_stops_downstream(out: Path):
    """1단 출력에 test 글이 섞이면 하류(d_downstream)가 멈춘다 — --final 없이는 통과 못 한다."""
    runner, _ = _fake_stage1([{"post_id": TEST_IDS[0], "candidates": []}])
    with pytest.raises(SystemExit, match="test 글"):
        run_all.main(["--output-dir", str(out), "--", *STAGE1], stage1_runner=runner)


# ── 예측 변환 ──────────────────────────────────────────────────────

def test_convert_renames_candidates_only(tmp_path: Path):
    span = {"text_id": "body", "start": 0, "end": 2, "type": "AGE", "text": "마흔", "level": "explicit",
            "subject": "self", "score": 0.9}
    (tmp_path / "predictions.jsonl").write_text(
        json.dumps({"post_id": "A01_b01", "candidates": [span]}, ensure_ascii=False) + "\n"
        + json.dumps({"post_id": "A01_b03", "candidates": []}) + "\n", encoding="utf-8")
    n = run_all.convert_stage1_preds(tmp_path, tmp_path / "o.jsonl")
    rows = [json.loads(x) for x in (tmp_path / "o.jsonl").read_text(encoding="utf-8").splitlines()]
    assert n == 2 and rows == [{"post_id": "A01_b01", "spans": [span]}, {"post_id": "A01_b03", "spans": []}]


@pytest.mark.parametrize("bad", [
    [{"post_id": "A01_b01", "spans": []}],                                      # 이미 spans 형식
    [{"post_id": "A01_b01", "candidates": None}],                               # 리스트 아님
    [{"post_id": "A01_b01", "candidates": []}, {"post_id": "A01_b01", "candidates": []}],  # 중복
    [],                                                                          # 빈 파일
])
def test_convert_refuses_bad_rows(bad: list[dict], tmp_path: Path):
    (tmp_path / "predictions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in bad), encoding="utf-8")
    with pytest.raises(SystemExit):
        run_all.convert_stage1_preds(tmp_path, tmp_path / "o.jsonl")


# ── 단계 연결 ──────────────────────────────────────────────────────

def _spy_downstream(result: dict | None = None):
    ds = mock.MagicMock()
    ds.run_downstream.return_value = result or {"fingerprint": {}, "stage2": {"status": "ok", "seconds": 1.0},
                                                "risk_action": {"status": "ok", "seconds": 2.0}, "ablations": {}}
    ds.failures = d_downstream.failures
    return ds


def test_stage1_then_downstream_gets_converted_preds(out: Path):
    runner, calls = _fake_stage1([{"post_id": "A01_b01", "candidates": []}], ckpt="C:/ckpt")
    ds = _spy_downstream()
    code = run_all.main(["--output-dir", str(out), "--ablation", "--", *STAGE1], stage1_runner=runner, downstream=ds)
    assert code == 0 and len(calls) == 1
    kw = ds.run_downstream.call_args.kwargs
    preds, ddir = ds.run_downstream.call_args.args
    assert preds == out / "downstream_preds.jsonl" and ddir == out / "downstream"
    assert kw["final"] is False and kw["allow_test"] is False and kw["ablations"] == []
    assert kw["c1_checkpoint"] == Path("C:/ckpt") and kw["stage2_mode"] == "rules"
    summary = json.loads((out / "bench_summary.json").read_text(encoding="utf-8"))
    assert summary["stages"]["stage1"]["status"] == "ok" and summary["stages"]["downstream"]["status"] == "ok"
    ext = json.loads((out / "stage1" / "metrics.json").read_text(encoding="utf-8"))["extensions"]["downstream"]
    assert ext["steps"]["risk_action"] == {"status": "ok", "seconds": 2.0}


def test_stage1_failure_skips_downstream(out: Path):
    ds = _spy_downstream()
    code = run_all.main(["--output-dir", str(out), "--", *STAGE1], stage1_runner=lambda cmd: 3, downstream=ds)
    assert code == 1 and not ds.run_downstream.called
    assert json.loads((out / "bench_summary.json").read_text(encoding="utf-8"))["stages"]["stage1"]["returncode"] == 3


def test_downstream_failure_exits_1(out: Path):
    runner, _ = _fake_stage1([{"post_id": "A01_b01", "candidates": []}])
    ds = _spy_downstream({"fingerprint": {}, "stage2": {"status": "failed", "error": "x"}, "ablations": {}})
    assert run_all.main(["--output-dir", str(out), "--", *STAGE1], stage1_runner=runner, downstream=ds) == 1


def test_both_runs_rules_stage2_then_model_with_compare(out: Path):
    runner, _ = _fake_stage1([{"post_id": "A01_b01", "candidates": []}])
    ds = _spy_downstream()
    ds._read_preds = d_downstream._read_preds
    ds._check_test_leak = d_downstream._check_test_leak
    with mock.patch("d_stage2.run_stage2", return_value={"out_file": "x"}) as s2:
        code = run_all.main(["--output-dir", str(out), "--stage2-mode", "both", "--", *STAGE1],
                            stage1_runner=runner, downstream=ds)
    assert code == 0
    assert s2.call_args.kwargs == {"mode": "rules", "allow_test": False}
    assert s2.call_args.args[1] == out / "downstream_rules" / "stage2"
    kw = ds.run_downstream.call_args.kwargs
    assert kw["stage2_mode"] == "model" and kw["compare_stage2"] == out / "downstream_rules"
