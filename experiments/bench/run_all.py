"""벤치마크 한 줄 실행 — 1단(B · run.py) → 2단 · 위험도 · 조치 · ablation(D · d_downstream.py) → (--final) 회귀.

B 의 1단 러너는 고치지 않고 **별도 프로세스로 그대로** 부른다(지연 측정에 하류 모듈이 섞이지 않게 · 규칙 켬/끔 설정이
프로세스 단위라서). 1단이 쓴 ``predictions.jsonl``(``candidates``)을 하류 입력 형식(``spans``)으로 옮겨 하류를 돌린다.

    # 개발 확인 (train 일부 · test 아님) — 1단 옵션은 run.py 것을 그대로 뒤에 붙인다
    python experiments/bench/run_all.py --output-dir experiments/bench/runs/<새 폴더> \\
        --stage2-mode rules -- --checkpoint-dir <ckpt> --limit 20 --rules on --threshold 0.7 --threads 4

    # 11/2 최종 측정 — test 239편 · --final 하나로 1단 --split test --final-test-confirm 과 하류 --final 이 같이 켜진다
    python experiments/bench/run_all.py --final --output-dir experiments/bench/runs/final_20261102 \\
        --stage2-mode both -- --checkpoint-dir <ckpt> --bio-data <bio> --rules on --threshold 0.7 --threads 4

    # 1단 없이 하류만 — 기존 예측 파일(spans 형식 · 예: exp24 dev 2,281편) 또는 run.py 출력 폴더
    python experiments/bench/run_all.py --output-dir experiments/bench/runs/<새 폴더> --preds <preds.jsonl>
    python experiments/bench/run_all.py --output-dir experiments/bench/runs/<새 폴더> --stage1-dir <run.py 출력 폴더>

test 보호:
- ``--split`` · ``--final-test-confirm`` · ``--output-dir`` 은 이 러너가 정한다. 1단 옵션에 직접 넣으면(줄임 포함) 멈춘다.
  --final 이 없으면 1단은 언제나 ``--split train`` 이다
- 하류는 --final 이 없으면 test 글(splits/test_post_ids.json 의 ``post_ids`` 255개)이 섞이는 순간 멈춘다 (d_downstream)
- --final 은 --preds 와 같이 쓸 수 없다. --stage1-dir 과는 그 폴더가 run.py 최종 test 출력(scope official_test)일 때만
  — 11/2 에 1단은 OK 이고 하류만 실패했을 때 1단을 다시 돌리지 않고 하류만 다시 도는 길이다

``--stage2-mode both`` = 2단 규칙 경로를 먼저 따로 돌리고(``downstream_rules/stage2``) 모델 경로 하류를 그것과 비교한다
(ablation ④). 위험도 · 조치 · ablation · 회귀는 모델 쪽 실행에서 한 번만 돈다.

결과: ``<output-dir>/stage1/``(run.py 그대로) · ``downstream_preds.jsonl`` · ``downstream/metrics_downstream.json`` ·
``bench_summary.json``(단계별 status · 걸린 시간 · 명령). 1단 ``metrics.json`` 의 ``extensions.downstream`` 에 하류 요약을 채운다.
1단이 실패하면 하류를 돌리지 않는다. 어느 단계든 failed 면 종료 코드 1.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
RUN_PY = BENCH / "run.py"
# 이 러너가 정하는 1단 옵션 — 사용자가 넣으면(argparse 줄임 포함) 멈춘다
RESERVED = ("--split", "--final-test-confirm", "--output-dir")
STAGE2_MODES = ("rules", "model", "both")
ABLATIONS = ("single_vs_account", "explicit_removed")


class BenchError(SystemExit):
    """실행 전에 멈춰야 하는 입력 오류 — 종료 코드 2 와 메시지."""

    def __init__(self, msg: str) -> None:
        super().__init__(f"⛔ {msg}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _reserved_hit(token: str) -> str | None:
    """1단 옵션 토큰이 예약 옵션(또는 argparse 가 받아 주는 그 줄임)이면 그 옵션 이름."""
    if not token.startswith("--") or len(token) <= 2:
        return None
    name = token.split("=", 1)[0]
    for opt in RESERVED:
        if opt.startswith(name):
            return opt
    return None


def check_output_dir(out: Path) -> Path:
    """run.py 와 같은 규칙 — experiments 아래 runs/ 가 들어간 **새** 경로만 (기존 결과를 덮지 않는다)."""
    resolved = out.resolve()
    if out.exists() or not resolved.is_relative_to(ROOT / "experiments") or "runs" not in resolved.parts:
        raise BenchError(f"--output-dir {out} — 기존 결과를 덮어쓰지 않는다. experiments 아래 새 runs/ 경로를 준다")
    return resolved


def stage1_command(stage1_args: list[str], out_dir: Path, *, final: bool) -> list[str]:
    """run.py 명령. --split · --final-test-confirm · --output-dir 은 여기서만 넣는다."""
    for tok in stage1_args:
        if hit := _reserved_hit(tok):
            raise BenchError(f"1단 옵션 {tok!r} 는 넣지 않는다 — {hit} 은 이 러너가 정한다 "
                             "(test 는 --final 하나로만 연다)")
    split = ["--split", "test", "--final-test-confirm"] if final else ["--split", "train"]
    return [sys.executable, str(RUN_PY), *stage1_args, *split, "--output-dir", str(out_dir / "stage1")]


def convert_stage1_preds(stage1_dir: Path, target: Path) -> int:
    """run.py 의 ``{"post_id", "candidates"}`` → 하류의 ``{"post_id", "spans"}``. 키 이름만 바꾸고 스팬은 그대로.

    형식이 다르면(spans 가 이미 있음 · candidates 가 리스트 아님 · 중복 post_id) 조용히 넘기지 않고 멈춘다.
    """
    src = stage1_dir / "predictions.jsonl"
    if not src.is_file():
        raise BenchError(f"1단 예측 파일이 없다: {src}")
    seen: set[str] = set()
    lines: list[str] = []
    for no, line in enumerate(src.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        where = f"{src}:{no}"
        if not isinstance(row, dict) or "spans" in row or not isinstance(row.get("candidates"), list):
            raise BenchError(f"{where} — run.py 출력 형식(post_id · candidates 리스트)이 아니다")
        pid = row.get("post_id")
        if not isinstance(pid, str) or not pid or pid in seen:
            raise BenchError(f"{where} — post_id 가 없거나 중복이다: {pid!r}")
        seen.add(pid)
        lines.append(json.dumps({"post_id": pid, "spans": row["candidates"]}, ensure_ascii=False) + "\n")
    if not lines:
        raise BenchError(f"1단 예측이 비었다: {src}")
    target.write_text("".join(lines), encoding="utf-8", newline="\n")
    return len(lines)


def _stage1_checkpoint(stage1_dir: Path) -> Path | None:
    """run.py metrics.json 의 checkpoint 경로 (하류 지문의 c1_checkpoint_sha256 용)."""
    m = stage1_dir / "metrics.json"
    if not m.is_file():
        return None
    ckpt = json.loads(m.read_text(encoding="utf-8")).get("checkpoint")
    return Path(ckpt) if ckpt else None


def _run_stage1(cmd: list[str]) -> int:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "experiments" / "exp06-finetune"),
                                          os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)}
    return subprocess.run(cmd, cwd=ROOT, env=env).returncode


def _statuses(res: dict[str, Any]) -> dict[str, Any]:
    """metrics_downstream.json → 단계별 status · 걸린 시간만 (요약용)."""
    out: dict[str, Any] = {}
    for key, v in res.items():
        if key == "fingerprint" or not isinstance(v, dict):
            continue
        if key in ("ablations", "regressions"):
            for name, sub in v.items():
                if isinstance(sub, dict):
                    out[f"{key}.{name}"] = {"status": sub.get("status"), "seconds": sub.get("seconds")}
        else:
            out[key] = {"status": v.get("status"), "seconds": v.get("seconds")}
    return out


def _fill_extensions(stage1_dir: Path, summary: dict[str, Any]) -> None:
    """run.py 가 비워 둔 metrics.json ``extensions`` 에 하류 요약을 채운다 (B 러너의 extension_policy)."""
    m = stage1_dir / "metrics.json"
    if not m.is_file():
        return
    report = json.loads(m.read_text(encoding="utf-8"))
    report.setdefault("extensions", {})["downstream"] = summary
    m.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `--` 뒤는 전부 1단(run.py) 옵션 — 이 러너 옵션과 섞이지 않게 나눈다
    stage1_args: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, stage1_args = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("--output-dir", type=Path, required=True,
                    help="experiments 아래 runs/ 가 들어간 새 경로 (있으면 멈춘다)")
    ap.add_argument("--final", action="store_true",
                    help="11/2 최종 측정 — 1단 test(--split test --final-test-confirm) + 하류 --final(test 허용 · 회귀)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--preds", type=Path, help="1단 없이 하류만 — spans 형식 예측 JSONL (예: exp24 dev)")
    src.add_argument("--stage1-dir", type=Path,
                     help="1단 없이 하류만 — 이미 돈 run.py 출력 폴더 (--final 이면 최종 test 출력만)")
    ap.add_argument("--stage2-mode", choices=STAGE2_MODES, default="rules",
                    help="rules(CPU) · model(어댑터 · GPU) · both(규칙 먼저 → 모델 + 일치율 · ablation ④)")
    ap.add_argument("--adapter", type=Path, default=None, help="2단 어댑터 폴더 (기본: STAGE2_ADAPTER_DIR · 앱 기본)")
    ap.add_argument("--ablation", nargs="*", choices=ABLATIONS, default=list(ABLATIONS),
                    help="하류 ablation (기본: 둘 다 · 빈 목록이면 끔)")
    ap.add_argument("--compare-stage2", type=Path, default=None,
                    help="다른 실행의 하류 폴더와 2단 일치율 (--stage2-mode both 면 자동)")
    args = ap.parse_args(argv)
    if args.final and args.preds:
        ap.error("--final 은 --preds 와 같이 쓰지 않는다 — 1단부터 한 줄로, 하류만 다시 돌 때는 --stage1-dir <test 1단 출력>")
    if (args.preds or args.stage1_dir) and stage1_args:
        ap.error("--preds · --stage1-dir 이면 1단을 돌리지 않는다 — `--` 뒤 1단 옵션을 빼라")
    if not (args.preds or args.stage1_dir) and not stage1_args:
        ap.error("1단 옵션이 없다 — `-- --checkpoint-dir <ckpt> ...` 를 붙이거나 --preds · --stage1-dir 을 준다")
    if args.stage2_mode == "both" and args.compare_stage2:
        ap.error("--stage2-mode both 는 비교 대상을 스스로 만든다 — --compare-stage2 를 같이 주지 않는다")
    return args, stage1_args


def main(argv: list[str] | None = None, *, stage1_runner: Callable[[list[str]], int] = _run_stage1,
         downstream: Any = None) -> int:
    """stage1_runner · downstream 은 테스트 주입구 (기본: run.py 프로세스 · d_downstream 모듈)."""
    started = time.perf_counter()
    args, stage1_args = parse_args(argv)
    out = check_output_dir(args.output_dir)
    cmd = stage1_command(stage1_args, out, final=args.final) if stage1_args else None  # 예약 옵션 검사도 쓰기 전에
    if args.preds and not args.preds.is_file():
        raise BenchError(f"--preds 파일이 없다: {args.preds}")
    if args.stage1_dir and not (args.stage1_dir / "predictions.jsonl").is_file():
        raise BenchError(f"--stage1-dir 에 predictions.jsonl 이 없다: {args.stage1_dir}")
    if args.final and args.stage1_dir:
        m = args.stage1_dir / "metrics.json"
        scope = json.loads(m.read_text(encoding="utf-8")).get("scope") if m.is_file() else None
        if scope != "official_test":
            raise BenchError(f"--final --stage1-dir 은 run.py 최종 test 출력(scope official_test)만 받는다: {scope!r}")
    if str(BENCH) not in sys.path:
        sys.path.insert(0, str(BENCH))
    if downstream is None:
        import d_downstream as downstream  # noqa: PLC0415

    out.mkdir(parents=True)
    summary: dict[str, Any] = {
        "schema_version": "bench-all-1.0",
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "final": args.final, "argv": list(sys.argv[1:] if argv is None else argv),
        "stage2_mode": args.stage2_mode, "ablations": args.ablation, "stages": {},
    }
    stages = summary["stages"]

    def save() -> None:
        summary["total_seconds"] = round(time.perf_counter() - started, 2)
        (out / "bench_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")

    # 1) 1단
    stage1_dir: Path | None = None
    if cmd is not None:
        stage1_dir = out / "stage1"
        t0 = time.perf_counter()
        code = stage1_runner(cmd)
        stages["stage1"] = {"status": "ok" if code == 0 else "failed", "returncode": code, "command": cmd,
                            "seconds": round(time.perf_counter() - t0, 2),
                            "note": "run.py 프로세스 전체 — 모델 로딩 · 추가 탐지율 기준 도구 · 지연 측정 포함"}
        if code != 0:
            save()
            print(f"⛔ 1단 실패(종료 코드 {code}) — 하류를 돌리지 않는다", file=sys.stderr)
            return 1
    elif args.stage1_dir:
        stage1_dir = args.stage1_dir.resolve()
        stages["stage1"] = {"status": "reused", "dir": str(stage1_dir)}
    else:
        stages["stage1"] = {"status": "not_run", "preds": str(args.preds.resolve())}

    # 2) 1단 예측 → 하류 입력
    if stage1_dir is not None:
        preds = out / "downstream_preds.jsonl"
        n = convert_stage1_preds(stage1_dir, preds)
        stages["convert"] = {"status": "ok", "posts": n, "from": str(stage1_dir / "predictions.jsonl"),
                             "to": str(preds), "sha256": _sha256(preds)}
        checkpoint = _stage1_checkpoint(stage1_dir)
    else:
        preds, checkpoint = args.preds.resolve(), None

    # 3) (both) 2단 규칙 경로 — 모델 쪽 하류와 비교할 대상
    compare = args.compare_stage2
    mode = args.stage2_mode
    if mode == "both":
        rules_dir = out / "downstream_rules"
        t0 = time.perf_counter()
        try:
            downstream._check_test_leak(downstream._read_preds(preds), args.final)
            import d_stage2  # noqa: PLC0415
            res = d_stage2.run_stage2(preds, rules_dir / "stage2", mode="rules", allow_test=args.final)
            stages["stage2_rules"] = {"status": "ok", "out_file": res.get("out_file")}
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            stages["stage2_rules"] = {"status": "failed", "error": f"{type(e).__name__}: {e}"}
        stages["stage2_rules"]["seconds"] = round(time.perf_counter() - t0, 2)
        compare, mode = (rules_dir if stages["stage2_rules"]["status"] == "ok" else None), "model"

    # 4) 하류 (2단 · 위험도 · 조치 · ablation · --final 회귀)
    t0 = time.perf_counter()
    result = downstream.run_downstream(preds, out / "downstream", stage2_mode=mode, ablations=args.ablation,
                                       allow_test=args.final, c1_checkpoint=checkpoint, final=args.final,
                                       adapter=args.adapter, compare_stage2=compare)
    bad = downstream.failures(result)
    stages["downstream"] = {"status": "failed" if bad else "ok", "failed": bad,
                            "seconds": round(time.perf_counter() - t0, 2),
                            "metrics": str(out / "downstream" / "metrics_downstream.json"),
                            "steps": _statuses(result)}
    if stages.get("stage2_rules", {}).get("status") == "failed":
        bad = [*bad, "stage2_rules"]

    save()
    if stage1_dir is not None and cmd is not None:
        m = out / "downstream" / "metrics_downstream.json"
        _fill_extensions(stage1_dir, {"metrics_downstream": str(m), "sha256": _sha256(m) if m.is_file() else None,
                                      "stage2_mode": args.stage2_mode, "steps": stages["downstream"]["steps"],
                                      "failed": bad})

    print(f"\n[run_all] {out}")
    for name, st in stages.items():
        print(f"  {name:<14} {str(st.get('status')).upper():<8} {st.get('seconds', '')}")
        if name == "downstream":
            for step, sub in st["steps"].items():
                print(f"    {step:<32} {str(sub['status']).upper():<18} {sub.get('seconds') or ''}")
    print(f"  total          {summary['total_seconds']} s")
    if bad:
        print(f"⛔ 실패 단계: {', '.join(bad)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
