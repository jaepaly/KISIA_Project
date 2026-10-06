"""exp12 집계 — 조건별 교사 LLM 추론 성공 수(0~7)와 엔진 위험도를 나란히 낸다.

    PYTHONIOENCODING=utf-8 python experiments/exp12-action-llm/score.py

- 주 분석 열: correct_e03_current_location (exp11 과 같다 — E03 위치 정답은 현 거주지)
- 조건: c0 기준 → c1 비공개 → c2 + 위치태그 제거 → c3 + 명시 단서 삭제 (누적)
- 단계별 변화는 인물 단위 쌍 비교 — 줄어든 인물 수 / 같은 인물 수 / 늘어난 인물 수
- 입력이 같은 조건(조치 대상이 없어 c1 = c2 = c3)은 같은 입력을 다시 부른 것이라 교사 응답의 흔들림으로 따로 센다
"""
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONDITIONS = ("c0_baseline", "c1_unpublish", "c2_meta", "c3_rewrite")
ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")
MAIN = "correct_e03_current_location"


def main() -> int:
    rows = list(csv.DictReader((HERE / "results/teacher_scored.csv").open(encoding="utf-8-sig")))
    blank = [r for r in rows if r[MAIN] == ""]
    if blank:
        raise SystemExit(f"판정 안 된 칸 {len(blank)}개 — make_judging.py 결과를 먼저 채운다")
    inputs = {(r["persona_id"], r["condition"]): r
              for r in map(json.loads, (HERE / "data/inputs.jsonl").read_text(encoding="utf-8").splitlines())}

    # 40조건 × 7속성이 빠짐없이 한 번씩 있어야 한다 — 인물 하나가 통째로 빠져도 9명으로 집계되지 않게
    expected = {(p, c, a) for p, c in inputs for a in ATTRS}
    got = [(r["persona_id"], r["condition"], r["attribute"]) for r in rows]
    if len(got) != len(set(got)) or set(got) != expected:
        raise SystemExit(f"판정표 칸이 입력과 다르다: 기대 {len(expected)} · 실제 {len(got)} (중복 {len(got) - len(set(got))})")

    success: dict[tuple[str, str], int] = {}
    loc: dict[tuple[str, str], int] = {}
    risk: dict[tuple[str, str], float] = {}
    for r in rows:
        key = (r["persona_id"], r["condition"])
        success[key] = success.get(key, 0) + (r[MAIN] == "True")
        if r["attribute"] == "location":
            loc[key] = int(r[MAIN] == "True")
        risk[key] = float(r["our_risk"])
    personas = sorted({p for p, _ in success})
    missing = [(p, c) for p in personas for c in CONDITIONS if (p, c) not in success]
    if missing:
        raise SystemExit(f"결과 없는 조건: {missing}")

    per_condition = {
        c: {
            "llm_success_mean": round(statistics.fmean(success[(p, c)] for p in personas), 2),
            "location_success": sum(loc[(p, c)] for p in personas),
            "engine_risk_mean": round(statistics.fmean(risk[(p, c)] for p in personas), 2),
        }
        for c in CONDITIONS
    }
    steps = {}
    for a, b in zip(CONDITIONS, CONDITIONS[1:]):
        same_input = [p for p in personas if inputs[(p, a)]["posts"] == inputs[(p, b)]["posts"]]
        changed = [p for p in personas if p not in same_input]
        d = [success[(p, b)] - success[(p, a)] for p in changed]
        steps[f"{a}→{b}"] = {
            "personas_with_change": len(changed),
            "down": sum(x < 0 for x in d), "same": sum(x == 0 for x in d), "up": sum(x > 0 for x in d),
            "mean_delta": round(statistics.fmean(d), 2) if d else None,
            "engine_risk_mean_delta": round(statistics.fmean(risk[(p, b)] - risk[(p, a)] for p in changed), 2) if changed else None,
        }
    # 같은 입력 재호출 — 교사 응답 흔들림
    noise = []
    for p in personas:
        for a, b in zip(CONDITIONS, CONDITIONS[1:]):
            if inputs[(p, a)]["posts"] == inputs[(p, b)]["posts"]:
                noise.append(abs(success[(p, b)] - success[(p, a)]))
    total = {
        "c0_mean": per_condition["c0_baseline"]["llm_success_mean"],
        "c3_mean": per_condition["c3_rewrite"]["llm_success_mean"],
        "down": sum(success[(p, "c3_rewrite")] < success[(p, "c0_baseline")] for p in personas),
        "same": sum(success[(p, "c3_rewrite")] == success[(p, "c0_baseline")] for p in personas),
        "up": sum(success[(p, "c3_rewrite")] > success[(p, "c0_baseline")] for p in personas),
    }
    c0 = total["c0_mean"]
    total["llm_reduction_pct"] = None if not c0 else round(100 * (c0 - total["c3_mean"]) / c0, 1)
    e0 = per_condition["c0_baseline"]["engine_risk_mean"]
    total["engine_reduction_pct"] = None if not e0 else round(100 * (e0 - per_condition["c3_rewrite"]["engine_risk_mean"]) / e0, 1)
    judged = {}
    for r in rows:
        judged[r["judged_by"]] = judged.get(r["judged_by"], 0) + 1
    res = {
        "main_column": MAIN,
        "personas": len(personas),
        "cells": len(rows),
        "judged_by": judged,
        "per_condition": per_condition,
        "steps": steps,
        "total_c0_to_c3": total,
        "same_input_recall": {"pairs": len(noise), "abs_delta_mean": round(statistics.fmean(noise), 2) if noise else None,
                              "nonzero": sum(x > 0 for x in noise)},
        "per_persona": {p: {c: {"llm": success[(p, c)], "risk": risk[(p, c)]} for c in CONDITIONS} for p in personas},
    }
    (HERE / "results/metrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    for c in CONDITIONS:
        v = per_condition[c]
        print(f"{c:13s} LLM {v['llm_success_mean']:.2f}/7 · 위치 {v['location_success']}/{len(personas)} · 엔진 {v['engine_risk_mean']}")
    print("c0→c3", total)
    print("같은 입력 재호출", res["same_input_recall"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
