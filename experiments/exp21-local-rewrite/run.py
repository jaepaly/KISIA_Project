"""exp21 — 로컬 Qwen 바꿔 쓰기 시제품. 합성 골드(test 제외)에서 규칙 엔진이 후보를 못 내는 본인 단서를 골라 후보를 만든다.

    python experiments/exp21-local-rewrite/run.py --n-posts 15 --out <결과.jsonl>

결과 줄: {post_id, span_id, type, level, original, suggestion, model_core, reason, context_before, context_after}
reason — 후보를 거른 이유 (잔존: 바꾼 글을 1단에 다시 넣었을 때 같은 자리 · 같은 유형 단서가 또 잡힘)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("KISIA_DATA", ROOT / "data"))
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(Path(__file__).resolve().parent)]

from kopl.c4_stage2.rewrite import suggest  # noqa: E402
from rewrite_llm import apply, load_rewrite_adapter, propose  # noqa: E402

TARGET_TYPES = {"JOB", "REL_HOME", "REL_WORK", "LOC_FACILITY", "AGE", "INCOME", "COMMUTE", "FAM"}


def candidates(n_posts: int, seed: int) -> list[dict]:
    corpus = DATA / "corpus" / "v0"
    test = set(json.loads((corpus / "splits" / "test_post_ids.json").read_text(encoding="utf-8")))
    posts = []
    for f in sorted((corpus / "gold").glob("*_spans.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if "post_id" not in r or r["post_id"] in test:
                continue
            body = r["texts"].get("body") or ""
            spans = [s for s in r["spans"] if s["text_id"] == "body" and s.get("subject") == "self"
                     and s["type"] in TARGET_TYPES and not suggest(s, body)]
            if len(spans) >= 2 and len(body) <= 900:
                posts.append({"post_id": r["post_id"], "text": body, "spans": spans})
    random.Random(seed).shuffle(posts)
    return posts[:n_posts]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-posts", type=int, default=15)
    ap.add_argument("--seed", type=int, default=21)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--adapter", type=Path, help="학습한 바꿔 쓰기 어댑터 (없으면 기본 모델 = v1)")
    args = ap.parse_args()

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    from apps.analyzer.engines import real  # 1단 (모델+규칙) — 잔존 확인용
    from kopl.c4_stage2.infer import Stage2Model

    model = Stage2Model()
    adapter = load_rewrite_adapter(model, args.adapter) if args.adapter else None
    rows, t_total = [], 0.0
    detect = lambda t: real.detect_spans({"post_id": "rw", "body": t})["spans"]  # noqa: E731
    posts = candidates(args.n_posts, args.seed)
    # 글마다 바로 덧붙여 쓴다 — 중간에 끊겨도 다시 실행하면 끝난 글은 건너뛴다 (10/8 · 시스템 RAM 부족으로 평가가 끊긴 뒤)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done_posts = set()
    if args.out.exists():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows.append(r)
                done_posts.add(r["post_id"])
    with args.out.open("a", encoding="utf-8") as fh:
        for post in posts:
            if post["post_id"] in done_posts:
                continue
            t = time.time()
            props = propose(model, post["text"], post["spans"], detector=detect, adapter=adapter)
            t_total += time.time() - t
            for s in post["spans"][:8]:
                pr = props.get(s["span_id"], {})
                row = {"post_id": post["post_id"], "span_id": s["span_id"], "type": s["type"], "level": s["level"],
                       "original": s["text"], "suggestion": pr.get("suggestion"), "model_core": pr.get("core"),
                       "reason": pr.get("reason"),
                       "context_before": post["text"][max(0, s["start"] - 30):s["start"]],
                       "context_after": post["text"][s["end"]:s["end"] + 30]}
                rows.append(row)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"  {len(done_posts) + 1}/{len(posts)} {post['post_id']}", flush=True)
            done_posts.add(post["post_id"])
    made = [r for r in rows if r["suggestion"]]
    from collections import Counter
    print(json.dumps({"spans": len(rows), "suggested": len(made),
                      "dropped": dict(Counter(r["reason"] for r in rows if not r["suggestion"])),
                      "sec_per_post": round(t_total / max(1, args.n_posts), 1)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
