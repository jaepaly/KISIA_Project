"""exp12 교사 LLM 호출 — inputs.jsonl 40행(인물 10 × 4조건)을 1회씩.

    python experiments/exp12-action-llm/run_teacher.py --dry-run
    python experiments/exp12-action-llm/run_teacher.py --env-file <팀 게이트웨이 .env>

호출·인증은 exp11 run_teacher.py 의 함수를 그대로 쓴다 — 같은 system 프롬프트 · 같은 스키마 ·
빈 CLAUDE_CONFIG_DIR 격리 · authMethod 확인 · KISIA 게이트웨이만 허용.
exp11 실행기를 그대로 쓰지 않는 이유: 원본 코퍼스만 읽고, 재개 키가 (persona_id, window_size) 라 4조건을 구분하지 못한다.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = HERE / "data"

_spec = importlib.util.spec_from_file_location(
    "exp11_run_teacher", ROOT / "experiments/exp11-risk-correlation/run_teacher.py")
if _spec is None or _spec.loader is None:
    raise RuntimeError("exp11 run_teacher.py 를 불러올 수 없다")
teacher = importlib.util.module_from_spec(_spec)
sys.modules["exp11_run_teacher"] = teacher
_spec.loader.exec_module(teacher)


def completed(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("predictions") is not None:
                done.add((rec["persona_id"], rec["condition"]))
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", type=Path)
    ap.add_argument("--model", default="claude-sonnet-4-6")  # exp11 과 같은 교사
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--retries", type=int, default=2)
    a = ap.parse_args()

    rows = [json.loads(l) for l in (DATA / "inputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    for row in rows:
        print(row["persona_id"], row["condition"], f"risk={row['our_risk']}", f"posts={len(row['posts'])}",
              f"chars={len(teacher.build_user_prompt(row))}")
    if a.dry_run:
        print("dry-run — 호출 안 함")
        return 0
    if a.env_file is None:
        raise SystemExit("--env-file 이 필요하다")

    env, kind = teacher.load_gateway_env(a.env_file)
    out_path = DATA / "teacher.jsonl"
    done = completed(out_path)
    gateway = hashlib.sha256(env["ANTHROPIC_BASE_URL"].encode()).hexdigest()[:12]
    with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as cfg, \
            out_path.open("a", encoding="utf-8") as f:
        env["CLAUDE_CONFIG_DIR"] = cfg
        auth = teacher.validate_auth(env, kind, cwd)
        print(f"인증: {auth} · gateway_sha256_12={gateway}")
        for row in rows:
            key = (row["persona_id"], row["condition"])
            if key in done:
                continue
            rec = teacher.invoke_teacher(row=row, model=a.model, timeout=a.timeout,
                                         retries=a.retries, env=env, cwd=cwd)
            rec.update({"condition": row["condition"], "credential_kind": kind,
                        "auth_method": auth, "gateway_url_sha256_12": gateway})
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(*key, "ok" if rec["predictions"] else f"FAIL {rec['error']}", f"{rec['sec']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
