"""하류 묶음 CLI — 1단 예측 파일 하나로 2단·위험도·ablation 을 순서대로 부르고
metrics_downstream.json 하나로 모운다.

사용 예:
    export PYTHONIOENCODING=utf-8 PYTHONPATH=src
    python experiments/bench/d_downstream.py \\
        --preds preds_dev.jsonl \\
        --out results/bench/downstream_dev \\
        --stage2-mode rules \\
        --ablation single_vs_account explicit_removed

test 글이 섞이면 --final 없이는 오류로 멈춘다. --final 은 test 를 하위 단계까지 허용하고
기존 회귀(exp09 · exp10 · exp11 재채점)를 함께 돌린다. 어느 단계든 failed 면 종료 코드 1.

ablation ④(2단 규칙 vs 모델)는 두 번 돌리고(--out 을 다르게) 두 번째에 --compare-stage2 <첫 실행 --out> 을 준다.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import importlib
import io
import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPLITS = ROOT / "data" / "corpus" / "v0" / "splits" / "test_post_ids.json"
BENCH = Path(__file__).resolve().parent


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_test_ids() -> frozenset[str]:
    """splits/test_post_ids.json 에서 255개 post_id 목록을 읽는다."""
    if not SPLITS.exists():
        return frozenset()
    with open(SPLITS, encoding="utf-8") as f:
        d = json.load(f)
    ids = d["post_ids"]
    assert len(ids) == 255, f"test_post_ids.json 에 {len(ids)}개 — 255 여야 한다"
    return frozenset(ids)


def _read_preds(preds_path: Path) -> list[dict[str, Any]]:
    """JSONL 예측 파일을 읽는다 — spans 없음 · 리스트 아님 · 중복 post_id 는 멈춘다 (d_preds · #359 B 리뷰)."""
    _ensure_bench_path()
    from d_preds import read_pred_rows
    return read_pred_rows(preds_path)


def _check_test_leak(preds: list[dict], allow_test: bool) -> None:
    """test 글이 섞이면 --final 없이는 오류를 낸다."""
    test_ids = _load_test_ids()
    if not test_ids:
        return
    leaked = [r["post_id"] for r in preds if r["post_id"] in test_ids]
    if leaked and not allow_test:
        raise SystemExit(
            f"⛔ test 글 {len(leaked)}개가 입력에 섞여 있다 "
            f"(예: {leaked[:3]}). "
            "11/2 최종 측정 때만 --final 로 돌린다."
        )


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def _c1_checkpoint_sha(c1_checkpoint: Path | None) -> str:
    """체크포인트 폴더의 model.safetensors SHA-256 (없으면 빈 문자열)."""
    if c1_checkpoint is None:
        return ""
    safetensors = Path(c1_checkpoint) / "model.safetensors"
    if not safetensors.exists():
        return ""
    return _sha256(safetensors)


def _ensure_bench_path() -> None:
    """패키지 import(``experiments.bench.d_downstream``)로 불려도 형제 모듈을 최상위 이름으로 찾게 한다."""
    if str(BENCH) not in sys.path:
        sys.path.insert(0, str(BENCH))


def _import_sibling(name: str) -> ModuleType | None:
    """형제 모듈 import. **그 모듈 파일 자체가 없을 때만** None — 모듈 안의 import 실패(의존 패키지 등)는 그대로 올린다."""
    _ensure_bench_path()
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name == name:
            return None
        raise


def _call(name: str, label: str, fn: Callable[[ModuleType], dict[str, Any]]) -> dict[str, Any]:
    """하위 단계 실행 → status 와 걸린 시간(seconds)을 붙인 dict. ok · skipped(모듈 파일 없음) · failed(그 밖의 예외 전부)."""
    t0 = time.perf_counter()
    try:
        mod = _import_sibling(name)
        if mod is None:
            return {"status": "skipped", "skipped": f"모듈 없음: {name}"}
        res = {"status": "ok", **fn(mod)}
    except Exception as e:  # noqa: BLE001 — 실패는 failed 로 남기고 CLI 가 종료 코드 1 로 알린다
        res = {"status": "failed", "error": f"{label}: {type(e).__name__}: {e}"}
    res["seconds"] = round(time.perf_counter() - t0, 2)
    return res


def _lazy_stage2(preds_path: Path, out_dir: Path, *, mode: str, allow_test: bool = False,
                 adapter: Path | None = None) -> dict[str, Any]:
    """d_stage2.run_stage2 를 lazy import 로 호출한다. adapter 는 run_downstream 이 해석한 경로 (rules 면 None)."""
    return _call("d_stage2", "d_stage2", lambda m: m.run_stage2(str(preds_path), str(out_dir), mode=mode,
                                                                   adapter=adapter, allow_test=allow_test))


def _lazy_risk_action(preds_path: Path, out_dir: Path, *, allow_test: bool = False,
                      app_target: float = 40.0) -> dict[str, Any]:
    """d_risk_action.run_risk_action 을 lazy import 로 호출한다."""
    return _call("d_risk_action", "d_risk_action", lambda m: m.run_risk_action(
        str(preds_path), str(out_dir), allow_test=allow_test, app_target=app_target))


def _lazy_ablation(name: str, preds_path: Path, out_dir: Path, *, allow_test: bool = False) -> dict[str, Any]:
    """d_risk_action.run_ablation 을 lazy import 로 호출한다."""
    return _call("d_risk_action", f"d_risk_action.run_ablation({name})",
                 lambda m: m.run_ablation(name, str(preds_path), str(out_dir), allow_test=allow_test))


def _lazy_compare(ours: Path, other_run: Path) -> dict[str, Any]:
    """ablation ④ — 이 실행과 다른 실행 폴더의 stage2_preds.jsonl 을 d_stage2.compare_stage2 로 비교한다."""
    def go(m: ModuleType) -> dict[str, Any]:
        other = _compare_target(other_run)
        if not other.exists():
            raise FileNotFoundError(f"비교할 stage2_preds.jsonl 이 없다: {other}")
        if other.resolve() == ours.resolve():
            raise ValueError("같은 파일끼리 비교 — 두 실행은 --out 을 다르게 준다")
        return m.compare_stage2(ours, other)
    return _call("d_stage2", "d_stage2.compare_stage2", go)


# ── 기존 실험 회귀 (--final 전용) ────────────────────────────────────────

def _hash_outputs(paths: list[Path]) -> dict[str, str | None]:
    """산출 파일 SHA-256 — 없으면 None."""
    return {str(p): _sha256(p) if p.is_file() else None for p in paths}


def _output_problems(paths: list[Path]) -> list[str]:
    """필수 산출 파일 검사 — 없거나 비었거나 JSON · JSONL · CSV 로 읽히지 않으면 문제로 적는다."""
    bad = []
    for p in paths:
        if not p.is_file():
            bad.append(f"없음: {p}")
            continue
        try:
            text = p.read_text(encoding="utf-8-sig")
            if p.suffix == ".json":
                json.loads(text)
            elif p.suffix == ".jsonl":
                rows = [json.loads(line) for line in text.splitlines() if line.strip()]
                if not rows:
                    raise ValueError("빈 파일")
            elif p.suffix == ".csv":
                rows = list(csv.reader(io.StringIO(text)))
                if len(rows) < 2:
                    raise ValueError("머리줄만 있거나 빈 파일")
        except Exception as e:  # noqa: BLE001
            bad.append(f"읽기 실패: {p} ({type(e).__name__}: {e})")
    return bad


def _run_commands(cmds: list[list[str]], *, env: dict[str, str], outputs: list[Path],
                  runner: Callable[..., Any]) -> dict[str, Any]:
    """명령을 차례로 돌린다(실패하면 거기서 멈춤). 명령 · 종료 코드 · 산출 파일 SHA-256 을 남긴다.

    종료 코드가 모두 0 이어도 필수 산출 파일(outputs)이 없거나 읽히지 않으면 failed 다.
    """
    ran: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for cmd in cmds:
        code = runner(cmd, cwd=ROOT, env={**os.environ, **env}).returncode
        ran.append({"cmd": cmd, "returncode": code})
        if code != 0:
            break
    res: dict[str, Any] = {"status": "ok", "commands": ran, "outputs": _hash_outputs(outputs),
                           "seconds": round(time.perf_counter() - t0, 2)}
    if any(r["returncode"] != 0 for r in ran):
        res["status"], res["error"] = "failed", f"종료 코드 {ran[-1]['returncode']}: {' '.join(ran[-1]['cmd'])}"
    elif problems := _output_problems(outputs):
        res["status"], res["error"] = "failed", "종료 코드 0 이지만 필수 산출물 문제 — " + " · ".join(problems)
    return res


def _resolve_adapter(adapter: str | Path | None) -> Path:
    """앱 Stage2Model 과 같은 순서 — 인자 > STAGE2_ADAPTER_DIR > infer._DEFAULT_ADAPTER (exp08 results/adapter_v2)."""
    if str(ROOT / "src") not in sys.path:
        sys.path.insert(0, str(ROOT / "src"))
    from kopl.c4_stage2 import infer  # noqa: PLC0415
    return Path(adapter or os.getenv("STAGE2_ADAPTER_DIR", infer._DEFAULT_ADAPTER))


def _adapter_sha(adapter: Path | None) -> str | None:
    """어댑터 폴더의 adapter_model.safetensors SHA-256 (없으면 None)."""
    if adapter is None:
        return None
    f = Path(adapter) / "adapter_model.safetensors"
    return _sha256(f) if f.is_file() else None


EXP09_KEEP = "exp09 추적 산출물이 있어 덮어쓰지 않는다 — 새로 재려면 사람이 세 파일을 옮기고 다시 실행"


def _exp09_regression(adapter: Path, runner: Callable[..., Any]) -> dict[str, Any]:
    """exp09 v2 회귀 — 실험 폴더의 산출물을 **절대 덮어쓰지 않는다**.

    - meta + metrics 가 있고 meta 의 adapter_sha256 · inputs_sha256 · external_sha256 이 이번 어댑터와
      지금의 입력(data/inputs.jsonl) · 외부 판정(data/external.jsonl) SHA 와 모두 같으면 → 실행 없이 existing_verified
    - 셋(생성 jsonl · meta · metrics) 중 하나라도 있는데 그 밖이면(어댑터 다름 · 확인 불가 · 일부만 있음) → 실행 없이 failed
    - 셋 다 없을 때만 명령을 돌린다 (어댑터는 --adapter 로 명시해 run_config 의 자체 기본값과 갈리지 않게)
    """
    def go(m: ModuleType) -> dict[str, Any]:
        outputs = m.exp09_outputs("v2")
        _gen, meta, metrics = outputs
        want = _adapter_sha(adapter)
        base: dict[str, Any] = {"adapter": str(adapter), "adapter_sha256": want}
        if not any(p.exists() for p in outputs):
            return {**base, **_run_commands(m.exp09_commands("v2", adapter), env=m.EXP09_ENV, outputs=outputs,
                                            runner=runner)}
        found = {**base, "commands": [], "outputs": _hash_outputs(outputs)}
        meta_d: dict[str, Any] = {}
        if meta.is_file():
            try:
                meta_d = json.loads(meta.read_text(encoding="utf-8-sig"))
            except Exception:  # noqa: BLE001 — 읽히지 않으면 확인 불가
                meta_d = {}
        recorded = meta_d.get("adapter_sha256")
        found["recorded_adapter_sha256"] = recorded
        # 입력 · 외부 판정 — run_config.py 가 meta 에 남긴 해시와 지금 파일의 해시
        cfg_files = m.exp09_config_files()
        found["config_files"] = {k: {"path": str(p), "sha256": _sha256(p) if p.is_file() else None,
                                     "recorded": meta_d.get(k)} for k, p in cfg_files.items()}
        cfg_missing = any(v["sha256"] is None for v in found["config_files"].values())
        cfg_same = not cfg_missing and all(v["sha256"] == v["recorded"] for v in found["config_files"].values())
        if metrics.is_file() and not _output_problems([metrics]) and want and recorded == want and cfg_same:
            return {**found, "status": "existing_verified",
                    "message": "동결 구성과 같은 어댑터 · 입력 · 외부 판정으로 잰 저장 결과 재사용"}
        why = ("meta 또는 metrics 없음" if not (meta.is_file() and metrics.is_file())
               else "이번 어댑터 SHA 를 확인할 수 없음" if not want
               else "meta 에 어댑터 SHA 없음" if not recorded
               else "어댑터 SHA 가 다름" if recorded != want
               else "metrics 를 읽을 수 없음" if _output_problems([metrics])
               else "입력 · 외부 판정 파일이 없어 저장 결과의 구성을 확인할 수 없다" if cfg_missing
               else "입력 · 외부 판정 SHA 가 meta 와 다름")
        return {**found, "status": "failed", "error": f"{EXP09_KEEP} ({why})"}
    return _call("d_stage2", "exp09", go)  # go 가 낸 status 가 _call 의 ok 를 덮는다


def _regressions(out_dir: Path, adapter: Path, runner: Callable[..., Any]) -> dict[str, Any]:
    """--final 에서만 — exp09(외부 LLM 일치율) · exp10(조치 재현) · exp11(위험 vs 추론 성공 재채점)."""
    out: dict[str, Any] = {"exp09": _exp09_regression(adapter, runner)}

    def other(m: ModuleType) -> dict[str, Any]:
        res = {}
        required = m.regression_outputs(out_dir)
        for name, cmds in m.regression_commands(out_dir).items():
            env = {"PYTHONIOENCODING": "utf-8", "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)])}
            res[name] = _run_commands(cmds, env=env, outputs=required[name], runner=runner)
        return res
    rest = _call("d_risk_action", "exp10·exp11", other)
    if rest["status"] == "ok":
        rest.pop("status")
        rest.pop("seconds", None)  # 회귀마다 _run_commands 가 따로 잰다
        out.update(rest)
    else:
        out["exp10_exp11"] = rest
    return out


def _compare_target(other_run: Path) -> Path:
    """--compare-stage2 폴더 → 비교할 stage2_preds.jsonl."""
    other = Path(other_run)
    return other / "stage2" / "stage2_preds.jsonl" if (other / "stage2").is_dir() else other / "stage2_preds.jsonl"


def failures(result: dict[str, Any]) -> list[str]:
    """결과 안의 failed 단계 이름 (ablation · 회귀 안쪽까지)."""
    bad = []
    for key in ("stage2", "risk_action", "stage2_compare"):
        if isinstance(result.get(key), dict) and result[key].get("status") == "failed":
            bad.append(key)
    for group in ("ablations", "regressions"):
        for name, v in (result.get(group) or {}).items():
            if isinstance(v, dict) and v.get("status") == "failed":
                bad.append(f"{group}.{name}")
    return bad


def _model_version() -> str:
    """src/kopl/c4_stage2/infer.py 의 MODEL_VERSION (없으면 빈 문자열)."""
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from kopl.c4_stage2 import infer  # noqa: PLC0415
        return getattr(infer, "MODEL_VERSION", "")
    except Exception:
        return ""


def _stage2_target_risk() -> float:
    """STAGE2_TARGET_RISK — 앱(apps/analyzer real.py)처럼 float 로 한 번 해석한다 (기본 40 · 0~100).

    이 값 하나를 지문과 run_risk_action(app_target=…)에 함께 넘긴다.
    """
    raw = os.getenv("STAGE2_TARGET_RISK", "40")
    try:
        v = float(raw)
    except ValueError:
        raise ValueError(f"STAGE2_TARGET_RISK={raw!r} — 숫자여야 한다") from None
    if not math.isfinite(v) or not 0 <= v <= 100:
        raise ValueError(f"STAGE2_TARGET_RISK={raw!r} — 0~100 이어야 한다")
    return v


def run_downstream(
    preds_path: str | Path,
    out_dir: str | Path,
    *,
    stage2_mode: str = "rules",
    ablations: list[str] | None = None,
    allow_test: bool = False,
    c1_checkpoint: str | Path | None = None,
    final: bool = False,
    adapter: str | Path | None = None,
    compare_stage2: str | Path | None = None,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """B 의 1단 러너가 나중에 호출할 수 있는 공개 함수.

    Args:
        preds_path: 1단 예측 JSONL 경로.
        out_dir: 결과 디렉터리.
        stage2_mode: "rules" | "model".
        ablations: 돌릴 ablation 이름 목록 ("single_vs_account", "explicit_removed").
        allow_test: True 면 test 글이 섞여도 계속 진행 (11/2 용) — 하위 단계까지 그대로 넘긴다.
        c1_checkpoint: 1단 체크포인트 폴더 (SHA 기록용).
        final: 11/2 최종 측정 — allow_test 를 켜고 기존 회귀(exp09 · exp10 · exp11)를 함께 돌린다.
        adapter: 2단 어댑터 폴더. 인자 > STAGE2_ADAPTER_DIR > 앱 기본 순으로 한 번 해석해 model 모드 2단과
            exp09 회귀에 같은 경로를 넘긴다 (rules 모드의 2단 지문은 null).
        compare_stage2: 다른 실행의 --out 폴더 — 2단 verdict 일치율(ablation ④)을 낸다.
        runner: 회귀 명령 실행 함수 (테스트 주입구 · 기본 subprocess.run).

    Returns:
        metrics_downstream.json 과 같은 내용의 dict. 단계마다 status(ok · skipped · failed · existing_verified)가 붙는다.
    """
    allow_test = allow_test or final
    preds_path = Path(preds_path)
    out_dir = Path(out_dir)

    # ④ 비교 대상 — 아무것도 쓰기 전에 확인한다 (같은 파일이면 첫 실행 결과를 덮어쓰게 된다)
    if compare_stage2 is not None:
        ours, other = (out_dir / "stage2" / "stage2_preds.jsonl").resolve(), _compare_target(Path(compare_stage2)).resolve()
        if ours == other:
            raise SystemExit(f"⛔ --compare-stage2 가 이 실행의 출력과 같은 파일이다: {other} — 두 실행은 --out 을 다르게 준다")
        if not other.is_file():
            raise SystemExit(f"⛔ 비교할 stage2_preds.jsonl 이 없다: {other}")
    out_dir.mkdir(parents=True, exist_ok=True)

    preds = _read_preds(preds_path)
    _check_test_leak(preds, allow_test)
    target = _stage2_target_risk()
    stage2_adapter = _resolve_adapter(adapter) if stage2_mode == "model" else None

    # 구성 지문
    fingerprint: dict[str, Any] = {
        "preds_sha256": _sha256(preds_path),
        "n_posts": len(preds),
        "n_users": len({r["post_id"].split("_")[0] for r in preds}),
        "git_commit": _git_commit(),
        "c1_checkpoint_sha256": _c1_checkpoint_sha(c1_checkpoint),
        "model_version": _model_version(),
        "stage2_target_risk": target,
        "stage2_mode": stage2_mode,
        "stage2_adapter": str(stage2_adapter) if stage2_adapter else None,
        "stage2_adapter_sha256": _adapter_sha(stage2_adapter),
        "measured_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
    }

    results: dict[str, Any] = {"fingerprint": fingerprint}

    # 2단
    results["stage2"] = _lazy_stage2(preds_path, out_dir / "stage2", mode=stage2_mode, allow_test=allow_test,
                                     adapter=stage2_adapter)

    # 위험도·조치
    results["risk_action"] = _lazy_risk_action(preds_path, out_dir / "risk_action", allow_test=allow_test,
                                               app_target=target)

    # ablation
    ablation_results: dict[str, Any] = {}
    for name in (ablations or []):
        ablation_results[name] = _lazy_ablation(name, preds_path, out_dir / f"ablation_{name}",
                                                allow_test=allow_test)
    results["ablations"] = ablation_results

    # ablation ④ — 다른 실행과 2단 verdict 일치율
    if compare_stage2 is not None:
        results["stage2_compare"] = (
            _lazy_compare(out_dir / "stage2" / "stage2_preds.jsonl", Path(compare_stage2))
            if results["stage2"]["status"] == "ok"
            else {"status": "failed", "error": f"이 실행의 2단이 {results['stage2']['status']} — 비교할 수 없다"})

    # 기존 회귀 — --final 에서만
    if final:
        # exp09 는 2단과 같은 어댑터 — rules 모드면 같은 순서로 여기서 해석한다
        results["regressions"] = _regressions(out_dir / "regressions", stage2_adapter or _resolve_adapter(adapter),
                                              runner or subprocess.run)

    # 저장
    out_path = out_dir / "metrics_downstream.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[d_downstream] 저장: {out_path}", file=sys.stderr)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="하류 묶음 CLI")
    ap.add_argument("--preds", required=True, type=Path, help="1단 예측 JSONL")
    ap.add_argument("--out", required=True, type=Path, help="결과 디렉터리")
    ap.add_argument(
        "--stage2-mode",
        choices=("rules", "model"),
        default="rules",
        help="2단 경로: rules(폴백) | model(어댑터)",
    )
    ap.add_argument(
        "--ablation",
        nargs="*",
        choices=("single_vs_account", "explicit_removed"),
        default=[],
        help="돌릴 ablation 이름 (여러 개 가능)",
    )
    ap.add_argument(
        "--final",
        action="store_true",
        help="11/2 최종 측정용 — test 글 허용(하위 단계까지) + exp09 · exp10 · exp11 회귀 실행",
    )
    ap.add_argument(
        "--c1-checkpoint",
        type=Path,
        default=None,
        help="1단 체크포인트 폴더 (model.safetensors SHA 기록용)",
    )
    ap.add_argument("--adapter", type=Path, default=None,
                    help="2단 어댑터 폴더 — model 모드 2단과 --final 의 exp09 회귀에 같은 경로 (기본: STAGE2_ADAPTER_DIR · 앱 기본)")
    ap.add_argument(
        "--compare-stage2",
        type=Path,
        default=None,
        help="다른 실행의 --out 폴더 — 2단 verdict 일치율 (ablation ④ · 출력 폴더는 서로 달라야 한다)",
    )
    args = ap.parse_args(argv)

    result = run_downstream(
        preds_path=args.preds,
        out_dir=args.out,
        stage2_mode=args.stage2_mode,
        ablations=args.ablation,
        allow_test=args.final,
        c1_checkpoint=args.c1_checkpoint,
        final=args.final,
        adapter=args.adapter,
        compare_stage2=args.compare_stage2,
    )

    # 상태를 그대로 찍는다
    fp = result.get("fingerprint", {})
    print(f"posts={fp.get('n_posts')}  users={fp.get('n_users')}  commit={fp.get('git_commit','')[:8]}")

    def line(name: str, v: dict[str, Any]) -> str:
        why = v.get("skipped") or v.get("error") or v.get("message") or ""
        return f"  {name}: {str(v.get('status', '?')).upper()}" + (f" — {why}" if why else "")

    for k, v in result.items():
        if k == "fingerprint" or not isinstance(v, dict):
            continue
        if k in ("ablations", "regressions"):
            for name, sub in v.items():
                print(line(f"{k}.{name}", sub))
        else:
            print(line(k, v))
    bad = failures(result)
    if bad:
        print(f"⛔ 실패 단계: {', '.join(bad)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
