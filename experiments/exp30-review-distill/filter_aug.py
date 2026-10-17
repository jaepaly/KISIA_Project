"""exp30 — 보강 글이 판정셋 D1c 와 섞이지 않게 거른다 (README §2 · 교사 라벨 전).

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp30-review-distill/filter_aug.py

D1c 표현(design.json) 이나 D1c 1단(A0)이 잡은 장소 이름(조사 뗀 것 · 2자 이상)이 보강 글 본문에 그대로 있으면 `excluded` 를 단다.
"""
from __future__ import annotations

import json
import re
import sys

import common
from kopl.c1_span.attributes import _core


def main() -> int:
    design = json.load(open(common.EXP29 / "data" / "design.json", encoding="utf-8"))
    words = {x["text"] for k in ("A", "T", "V") for x in design[k]}
    for line in open(common.HERE / "results" / "a0_d1c.jsonl", encoding="utf-8"):
        for s in json.loads(line)["spans"]:
            core = _core(s["text"])
            if s["type"] in ("LOC_ADMIN", "LOC_FACILITY") and len(core) >= 2 \
                    and not re.fullmatch(r"(?:에서|에게|으로|부터|까지|한테|처럼|에도)", core):   # 1단 잡음 조각은 지명이 아니다
                words.add(core)
    path = common.HERE / "data" / "aug_posts.jsonl"
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    n = 0
    for r in rows:
        hit = sorted(w for w in words if w in r["texts"]["body"])
        r.pop("excluded", None)
        if hit:
            r["excluded"] = "D1c 와 겹침: " + " · ".join(hit[:5])
            n += 1
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"보강 {len(rows)} 편 중 제외 {n} · 남음 {len(rows) - n} (거른 말 {len(words)}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
