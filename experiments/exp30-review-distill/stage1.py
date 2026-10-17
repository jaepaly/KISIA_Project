"""exp29 · exp30 — 1단 후보를 뽑는다. GPU 서버에서 돈다 (exp28b review.py a0 와 같은 호출).

    export PYTHONIOENCODING=utf-8 PYTHONPATH=src
    python experiments/exp30-review-distill/stage1.py --checkpoint <1단 v2 폴더> --tag a0 --sets d1c,d4,pool,aug

subject 는 실행하는 코드 트리의 `attributes.py` 로 정해진다 — A0 는 main, R1 은 exp29 규칙이 든 트리에서 돌린다.
출력: results/{tag}_{set}.jsonl — 글마다 {post_id, spans:[{start,end,text,type,subject}], sec}
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import common

for p in (common.ROOT / "src", common.ROOT / "experiments" / "exp06-finetune", common.ROOT / "apps" / "analyzer" / "engines"):
    sys.path.insert(0, str(p))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--sets", default="d1c,d4,pool")
    a = ap.parse_args()
    import c1_rules
    import infer
    from kopl.c1_span.attributes import resolve

    det = infer.SpanDetector(a.checkpoint, device="cuda", min_span_score=0.7)
    (common.HERE / "results").mkdir(exist_ok=True)
    for name in a.sets.split(","):
        rows = common.load(name)
        with open(common.HERE / "results" / f"{a.tag}_{name}.jsonl", "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                t = time.perf_counter()
                spans = c1_rules.detect(det, {"post_id": r["post_id"], "body": r["body"]}, resolve)["spans"]
                spans = [{k: s[k] for k in ("start", "end", "text", "type", "subject")} for s in spans if s["text_id"] == "body"]
                f.write(json.dumps({"post_id": r["post_id"], "spans": spans, "sec": round(time.perf_counter() - t, 3)}, ensure_ascii=False) + "\n")
        print(name, len(rows), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
