"""exp22 1단 예측 — 앱과 같은 경로(apps/analyzer/engines/real.detect_spans · 기준선 v2 + 명시 규칙 · CPU)로 720편의 스팬을 한 번 만들어 고정한다.
v1 · v2 두 2단 구성은 이 파일 하나를 같은 입력으로 받는다 (README §2).

    ENGINE_MODE=real C1_CHECKPOINT_DIR=<v2 폴더> HF_HUB_OFFLINE=1 PYTHONIOENCODING=utf-8 PYTHONPATH="src;." \\
        python experiments/exp22-stage2-judge/run_stage1.py

출력: data/stage1.jsonl — {post_id, spans:[...]} · data/stage1_manifest.json — 데이터 해시 · 체크포인트 SHA-256 · 규칙 켬 여부 · 커밋 · 시간
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
DATA = HERE / "data" / "accounts.jsonl"
FROZEN = "d9db9bdec3a8407837f9b29ec0f97e84b93c86273f41e9b6bb5d1a62974ace86"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if sha256(DATA) != FROZEN:
        raise SystemExit("accounts.jsonl 해시가 고정값과 다르다 — README §4")
    from apps.analyzer.engines import real  # 체크포인트를 여기서 올린다

    ckpt = Path(os.environ["C1_CHECKPOINT_DIR"])
    rows = [json.loads(l) for l in DATA.read_text(encoding="utf-8").splitlines() if l.strip()]
    t0 = time.perf_counter()
    out = HERE / "data" / "stage1.jsonl"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for a in rows:
            for p in a["posts"]:
                rec = {"post_id": p["post_id"], "title": None, "body": p["texts"]["body"], "photo_captions": []}
                spans = real.detect_spans(rec).get("spans") or []
                f.write(json.dumps({"post_id": p["post_id"], "spans": spans}, ensure_ascii=False) + "\n")
    manifest = {
        "measured": time.strftime("%Y-%m-%d %H:%M"), "accounts_sha256": FROZEN, "stage1_sha256": sha256(out),
        "checkpoint": ckpt.name, "checkpoint_model_sha256": sha256(ckpt / "model.safetensors"),
        "c1_rules": os.getenv("C1_RULES", "1") not in ("0", "false", "off", "no"),
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip(),
        "seconds": round(time.perf_counter() - t0, 1),
    }
    (HERE / "data" / "stage1_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
