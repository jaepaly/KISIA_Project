"""exp30 — 회귀 감시 D4(교사 라벨 골드 300편)를 학습 · 판정 전에 고정한다 (README §2).

    PYTHONIOENCODING=utf-8 python experiments/exp30-review-distill/plan.py

D4 = 검수하지 않은 교사 라벨 골드 글 중 test 255편 · D2(검수 골드) · D3(exp28b · data/d3_post_ids.json 사본) 제외,
body 스팬 1개 이상에서 seed 20261018 로 300편. 출력 data/d4_post_ids.json.
"""
from __future__ import annotations

import glob
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SEED = 20261018


def main() -> None:
    test = set(json.load(open(ROOT / "data/corpus/v0/splits/test_post_ids.json", encoding="utf-8"))["post_ids"])
    assert len(test) == 255
    d3 = set(json.load(open(HERE / "data" / "d3_post_ids.json", encoding="utf-8"))["post_ids"])
    assert len(d3) == 300
    pool = set()
    for f in sorted(glob.glob(str(ROOT / "data/corpus/v0/gold/*_spans.jsonl"))):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            pid = d.get("post_id")
            if not pid or "spans" not in d or d.get("reviewed") or pid in test or pid in d3:
                continue
            if any(s["text_id"] == "body" for s in d["spans"]):
                pool.add(pid)
    pick = sorted(random.Random(SEED).sample(sorted(pool), 300))
    out = HERE / "data" / "d4_post_ids.json"
    out.write_text(json.dumps({"seed": SEED, "pool": len(pool), "post_ids": pick}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"D4 {len(pick)} / 풀 {len(pool)} → {out.name}")


if __name__ == "__main__":
    main()
