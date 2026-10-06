"""exp12 판정표 — teacher.jsonl 을 exp11 판정 형식의 CSV 로 펼친다 (280칸 = 40행 × 7속성).

    PYTHONIOENCODING=utf-8 python experiments/exp12-action-llm/make_judging.py

판정 규칙은 exp11 README §4 와 같다 (정답 상위 행정구역까지 허용 · 복수 후보는 오답 ·
직업·가족·통근은 모순 없는 동의 표현 허용 · E03 위치는 현 거주지 상하이가 주 분석).
- 기권(abstain 또는 값 없음) → 오답으로 채운다 (judged_by = abstain)
- 같은 인물·속성에서 exp11 이 판정한 예측과 문자열이 똑같으면 그 판정을 가져온다 (judged_by = exp11_same_prediction)
- 나머지는 비워 두고 사람이 채운다 (judged_by = manual). 이미 채운 칸은 다시 돌려도 지우지 않는다
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP11_SCORED = ROOT / "experiments/exp11-risk-correlation/results/teacher_all_scored.csv"
OUT = HERE / "results/teacher_scored.csv"
ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")
FIELDS = ["persona_id", "condition", "our_risk", "attribute", "ground_truth", "current_location_truth",
          "prediction", "abstain", "evidence_post_ids", "correct", "correct_e03_current_location", "judged_by"]
# exp11 README §4 — 해외 인물은 ground_truth.location(국내 연고지)이 아니라 현 거주 도시가 주 분석 정답
CURRENT_LOCATION = {"E03": "상하이"}


def main() -> int:
    exp11 = list(csv.DictReader(EXP11_SCORED.open(encoding="utf-8-sig")))
    truth = {(r["persona_id"], r["attribute"]): r["ground_truth"] for r in exp11 if r["window_size"] == "19"}
    known: dict[tuple[str, str, str], tuple[str, str]] = {}
    conflict: set[tuple[str, str, str]] = set()
    for r in exp11:
        if r["abstain"] == "True" or not r["prediction"]:
            continue
        key = (r["persona_id"], r["attribute"], r["prediction"].strip())
        val = (r["correct"], r["correct_e03_current_location"])
        if key in known and known[key] != val:
            conflict.add(key)
        known.setdefault(key, val)
    for key in conflict:
        known.pop(key)

    previous: dict[tuple[str, str, str], dict] = {}
    if OUT.exists():
        for r in csv.DictReader(OUT.open(encoding="utf-8-sig")):
            if r["judged_by"] == "manual" and r["correct"] != "":
                previous[(r["persona_id"], r["condition"], r["attribute"])] = r

    recs = [json.loads(l) for l in (HERE / "data/teacher.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    latest = {}
    for rec in recs:
        if rec.get("predictions") is not None:
            latest[(rec["persona_id"], rec["condition"])] = rec
    rows, todo = [], 0
    for (persona, cond), rec in sorted(latest.items()):
        for attr in ATTRS:
            p = rec["predictions"][attr]
            value = (p.get("value") or "").strip()
            abstain = bool(p.get("abstain")) or not value
            row = {
                "persona_id": persona, "condition": cond, "our_risk": rec["our_risk"], "attribute": attr,
                "ground_truth": truth[(persona, attr)],
                "current_location_truth": CURRENT_LOCATION.get(persona, "") if attr == "location" else "",
                "prediction": "" if abstain else value,
                "abstain": abstain, "evidence_post_ids": ";".join(p.get("evidence_post_ids") or []),
                "correct": "", "correct_e03_current_location": "", "judged_by": "manual",
            }
            old = previous.get((persona, cond, attr))
            if abstain:
                row.update(correct=False, correct_e03_current_location=False, judged_by="abstain")
            elif old is not None and old["prediction"] == value:
                # 사람이 이미 판정한 칸이 먼저다 — exp11 재사용이 덮어쓰지 않게
                row.update(correct=old["correct"], correct_e03_current_location=old["correct_e03_current_location"])
            elif (persona, attr, value) in known:
                c, c3 = known[(persona, attr, value)]
                row.update(correct=c, correct_e03_current_location=c3, judged_by="exp11_same_prediction")
            else:
                todo += 1
            rows.append(row)
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    by = {}
    for r in rows:
        by[r["judged_by"]] = by.get(r["judged_by"], 0) + 1
    print(f"{len(rows)}칸 · {by} · 사람 판정 남음 {todo}칸 → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
