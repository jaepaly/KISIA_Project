"""exp32 — exp31 학생(S2 · seed 2개 · 다시 학습하지 않는다)의 판정을 1단 후보 전부에 대해 받아 둔다. GPU 서버에서 돈다.

    export PYTHONIOENCODING=utf-8 PYTHONPATH=src
    python experiments/exp32-loc-gate/apply.py --model <S2 폴더> --tag S2-20261019 --sets d1e,d2

출력: results/{tag}_{set}.jsonl — 글마다 {post_id, decisions, sec}. 유형 제한(H) · 전체 적용(S2) 은 score.py 가 이 판정으로 만든다.
입력 문맥은 exp30 · exp31 student.py 의 context 와 같다(앞뒤 한 문장 · ⟦ ⟧ · 256토큰).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

import common

MAXLEN = 256
_CUT = re.compile(r"(?<=[.!?…~])\s+|\n+")


def context(body: str, s: dict) -> str:
    marked = body[:s["start"]] + "⟦" + body[s["start"]:s["end"]] + "⟧" + body[s["end"]:]
    sents = [x for x in _CUT.split(marked) if x.strip()]
    at = next(i for i, x in enumerate(sents) if "⟦" in x)
    return f"[{s['type']}] " + " ".join(sents[max(0, at - 1): at + 2])


def main() -> int:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--sets", default="d1e,d2")
    ap.add_argument("--device", default="cuda")
    a = ap.parse_args()
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForSequenceClassification.from_pretrained(a.model).to(a.device).eval()
    for name in a.sets.split(","):
        body = {r["post_id"]: r["body"] for r in common.load(name)}
        with open(common.HERE / "results" / f"{a.tag}_{name}.jsonl", "w", encoding="utf-8", newline="\n") as f:
            for line in open(common.HERE / "results" / f"a0_{name}.jsonl", encoding="utf-8"):
                r = json.loads(line)
                t = time.perf_counter()
                dec = []
                if r["spans"]:
                    enc = tok([context(body[r["post_id"]], s) for s in r["spans"]], truncation=True, max_length=MAXLEN,
                              padding=True, return_tensors="pt").to(a.device)
                    with torch.no_grad():
                        dec = [common.LABELS[i] for i in model(**enc).logits.argmax(-1).tolist()]
                f.write(json.dumps({"post_id": r["post_id"], "decisions": dec, "sec": round(time.perf_counter() - t + r.get("sec", 0), 3)},
                                   ensure_ascii=False) + "\n")
        print(name, "done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
