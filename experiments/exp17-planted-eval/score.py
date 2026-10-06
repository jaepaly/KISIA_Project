"""exp17 채점 — 1단 구성의 예측을 「심은 단서」 정답에 대 본다.

    python experiments/exp17-planted-eval/score.py preds_a.jsonl [preds_b.jsonl ...]

예측 파일: 줄마다 {"post_id", "spans": [{text_id, start, end, type, level?, subject?}, ...]} (span.schema 출력 그대로 가능)

- **재현율**: 심은 단서 중 type 일치 + IoU ≥ 0.5 로 잡힌 비율 (label-schema §2 partial) — 유형별 · 변이별.
  예측 하나는 정답 하나에만 쓴다 — 공식 채점기(exp06 evaluate_test)와 같은 (IoU, 정답, 예측) 내림차순 탐욕 1:1 매칭 (#311 리뷰)
- **입력 검사**: 예측 파일의 post_id 는 평가셋 80편과 정확히 같아야 한다 — 누락·추가·중복이면 멈춘다.
  처리했지만 탐지가 없는 글은 `"spans": []` 로 둔다 (#311 리뷰)
- **타인 함정**: subject=other 로 심은 단서를 잡았을 때 other 로 판정했나 (self 면 k 를 잘못 좁힌다)
- **숫자 함정 오탐**: 「서른 해」 「쉰 날」 같은 수를 AGE 로 잡았나
- **심지 않은 곳**: 심은 단서·함정과 겹치지 않는 예측 수 — Gemini 가 의도치 않게 넣은 단서일 수 있어 **정밀도가 아니라 참고치**
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "posts.jsonl"


def overlap(a: dict, b: dict, *, same_type: bool = True) -> bool:
    if a.get("text_id", "body") != b.get("text_id", "body") or (same_type and a["type"] != b["type"]):
        return False
    inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter > 0 and inter / union >= 0.5


def iou(a: dict, b: dict) -> float:
    inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter / union if inter > 0 else 0.0


def match_one_to_one(gold: list[dict], pred: list[dict]) -> dict[int, int]:
    """정답 인덱스 → 예측 인덱스. 같은 채널·유형 + IoU ≥ 0.5 쌍을 (IoU, 정답, 예측) 내림차순으로 탐욕 1:1 매칭."""
    cands = sorted(((iou(g, x), i, j) for i, g in enumerate(gold) for j, x in enumerate(pred) if overlap(g, x)),
                   reverse=True)
    used_pred: set[int] = set()
    out: dict[int, int] = {}
    for _, i, j in cands:
        if i not in out and j not in used_pred:
            out[i] = j
            used_pred.add(j)
    return out


def evaluate(gold: list[dict], preds: dict[str, list[dict]]) -> dict:
    hit, tot = Counter(), Counter()
    by_variant_hit, by_variant_tot = Counter(), Counter()
    trap = Counter()
    distract_fp = unplanned = n_pred = 0
    for g in gold:
        p = [dict(x, text_id=x.get("text_id", "body")) for x in preds.get(g["post_id"], [])]
        n_pred += len(p)
        planted = [dict(c, text_id="body") for c in g["planted"]]
        matched = match_one_to_one(planted, p)
        for i, c in enumerate(g["planted"]):
            key = f"{c['type']}/{c['subject']}"
            tot[key] += 1
            by_variant_tot[c["variant"]] += 1
            m = p[matched[i]] if i in matched else None
            if m is not None:
                hit[key] += 1
                by_variant_hit[c["variant"]] += 1
            if c["subject"] == "other":
                trap["planted"] += 1
                if m is not None:
                    trap["caught"] += 1
                    trap["judged_other" if m.get("subject") == "other" else "judged_self"] += 1
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


def load_preds(path: str, expected_ids: set[str] | None = None) -> dict[str, list[dict]]:
    """예측 파일 → {post_id: spans}. post_id 중복이거나 평가셋과 다르면 멈춘다 (#311 리뷰)."""
    out: dict[str, list[dict]] = {}
    for n, line in enumerate(open(path, encoding="utf-8-sig"), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        pid = r["post_id"]
        if pid in out:
            raise ValueError(f"{path}:{n}: post_id 중복 {pid}")
        spans = r.get("spans")
        if not isinstance(spans, list):
            raise ValueError(f"{path}:{n}: {pid} 에 spans 목록이 없다 — 탐지가 없으면 \"spans\": []")
        out[pid] = spans
    if expected_ids is not None and set(out) != expected_ids:
        missing, extra = sorted(expected_ids - set(out)), sorted(set(out) - expected_ids)
        raise ValueError(f"{path}: post_id 가 평가셋과 다르다 — 누락 {len(missing)} {missing[:5]} · 추가 {len(extra)} {extra[:5]}")
    return out


def main(argv: list[str]) -> int:
    gold = [json.loads(l) for l in DATA.open(encoding="utf-8") if l.strip()]
    ids = {g["post_id"] for g in gold}
    rows = {Path(p).stem: evaluate(gold, load_preds(p, ids)) for p in argv}
    print(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
