"""exp17 채점 — 1단 구성의 예측을 「심은 단서」 정답에 대 본다.

    python experiments/exp17-planted-eval/score.py preds_a.jsonl [preds_b.jsonl ...]

예측 파일: 줄마다 {"post_id", "spans": [{text_id, start, end, type, level?, subject?}, ...]} (span.schema 출력 그대로 가능)

- **재현율**: 심은 단서 중 type 일치 + IoU ≥ 0.5 로 잡힌 비율 (label-schema §2 partial) — 유형별 · 변이별
- **타인 함정**: subject=other 로 심은 단서를 잡았을 때 other 로 판정했나 (self 면 k 를 잘못 좁힌다)
- **숫자 함정 오탐**: 「서른 해」 「쉰 날」 같은 수를 AGE 로 잡았나
- **심지 않은 곳**: 심은 단서·함정과 겹치지 않는 예측 수 — Gemini 가 의도치 않게 넣은 단서일 수 있어 **정밀도가 아니라 참고치**
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "posts.jsonl"


def overlap(a: dict, b: dict, *, same_type: bool = True) -> bool:
    if a.get("text_id", "body") != b.get("text_id", "body") or (same_type and a["type"] != b["type"]):
        return False
    inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter > 0 and inter / union >= 0.5


def evaluate(gold: list[dict], preds: dict[str, list[dict]]) -> dict:
    hit, tot = Counter(), Counter()
    by_variant_hit, by_variant_tot = Counter(), Counter()
    trap = Counter()
    distract_fp = unplanned = n_pred = 0
    for g in gold:
        p = [dict(x, text_id=x.get("text_id", "body")) for x in preds.get(g["post_id"], [])]
        n_pred += len(p)
        for c in g["planted"]:
            key = f"{c['type']}/{c['subject']}"
            tot[key] += 1
            by_variant_tot[c["variant"]] += 1
            m = [x for x in p if overlap(dict(c, text_id="body"), x)]
            if m:
                hit[key] += 1
                by_variant_hit[c["variant"]] += 1
            if c["subject"] == "other":
                trap["planted"] += 1
                if m:
                    trap["caught"] += 1
                    trap["judged_other" if any(x.get("subject") == "other" for x in m) else "judged_self"] += 1
        for d in g["distractors"]:
            if any(x["type"] == "AGE" and overlap({**d, "type": "AGE", "text_id": "body"}, x) for x in p):
                distract_fp += 1
        planted_any = [dict(c, text_id="body") for c in g["planted"]] + [dict(d, text_id="body") for d in g["distractors"]]
        unplanned += sum(1 for x in p if not any(overlap(x, c, same_type=False) for c in planted_any))
    self_keys = [k for k in tot if k.endswith("/self")]
    return {
        "posts": len(gold), "predicted_spans": n_pred,
        "recall_self": round(sum(hit[k] for k in self_keys) / max(1, sum(tot[k] for k in self_keys)), 3),
        "recall_all": round(sum(hit.values()) / max(1, sum(tot.values())), 3),
        "recall_by_type": {k: f"{hit[k]}/{tot[k]}" for k in sorted(tot)},
        "recall_by_variant": {k: f"{by_variant_hit[k]}/{by_variant_tot[k]}" for k in sorted(by_variant_tot)},
        "trap_other": {"planted": trap["planted"], "caught": trap["caught"], "judged_other": trap["judged_other"],
                       "judged_self": trap["judged_self"]},
        "distractor_age_fp": f"{distract_fp}/{sum(len(g['distractors']) for g in gold)}",
        "unplanned_spans_per_post": round(unplanned / max(1, len(gold)), 2),
    }


def load_preds(path: str) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for line in open(path, encoding="utf-8-sig"):
        if line.strip():
            r = json.loads(line)
            out[r["post_id"]].extend(r.get("spans") or [])
    return out


def main(argv: list[str]) -> int:
    gold = [json.loads(l) for l in DATA.open(encoding="utf-8") if l.strip()]
    rows = {Path(p).stem: evaluate(gold, load_preds(p)) for p in argv}
    print(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
