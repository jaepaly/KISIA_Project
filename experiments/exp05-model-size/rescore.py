"""exp05 재채점 — 정확도 말고 F1·혼동행렬·McNemar 로 다시 본다 [MF-012].

    python experiments/exp05-model-size/rescore.py

멘토 피드백 MF-012(2026-09-02): 「탐지 성능을 단순 정확도만으로 평가하지 마라.
F-score 등 다른 기준을 함께 보면 더 유의미한 결과가 나온다.」

⚠️ 이 스크립트가 재는 것은 「2단 추론 성능」이 아니라 **속성 단위 탐지 성능**이다.
   각 칸은 「그 속성에 단서가 있다고 봤는가(verdict != abstain)」 대 「골드에 단서가
   있는가」의 이진 판정이다. verdict 의 내용·근거 스팬·추론값의 정확성은 안 본다.
   원래 score.py 가 이 구분 없이 「정확도」라고만 불러서 성능이 실제보다 넓게 읽혔다.

⚠️ 245칸은 독립이 아니다. 인물 35명 안에 7속성이 군집돼 있어 실효 표본은 더 작다.
   그래서 McNemar 는 참고값이고, 확증하려면 인물 단위 cluster bootstrap 이 필요하다.
"""
from __future__ import annotations

import collections
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

HERE = Path(__file__).resolve().parent
ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")
MODELS = {"4B": "raw_qwen3-4b.json", "1.7B": "raw_qwen3-1.7b.json"}


def load_gold() -> dict:
    return {x["persona_id"]: x for x in json.loads(
        (HERE / "input.json").read_text(encoding="utf-8"))}


def cells(name: str, gold: dict) -> dict:
    """(인물, 속성) → (예측, 정답, 근거 스팬)"""
    out = {}
    for r in json.loads((HERE / "results" / MODELS[name]).read_text(encoding="utf-8")):
        it = gold[r["persona_id"]]
        f = r.get("findings") or {}
        for a in ATTRS:
            g = f.get(a) or {}
            out[(r["persona_id"], a)] = (
                g.get("verdict") != "abstain",
                bool(it["gold_has_clue"][a]),
                g.get("evidence") or [],
            )
    return out


def confusion(c: dict) -> tuple[int, int, int, int]:
    TP = FP = FN = TN = 0
    for pred, want, _ in c.values():
        if pred and want: TP += 1
        elif pred: FP += 1
        elif want: FN += 1
        else: TN += 1
    return TP, FP, FN, TN


def metrics(TP: int, FP: int, FN: int, TN: int) -> dict:
    n = TP + FP + FN + TN
    d = lambda a, b: a / b if b else 0.0
    P, R = d(TP, TP + FP), d(TP, TP + FN)
    P0, R0 = d(TN, TN + FN), d(TN, TN + FP)
    f = lambda p, r: d(2 * p * r, p + r)
    den = math.sqrt((TP+FP) * (TP+FN) * (TN+FP) * (TN+FN))
    return {
        "정확도": d(TP + TN, n), "F1_양성": f(P, R), "F1_음성": f(P0, R0),
        "macroF1": (f(P, R) + f(P0, R0)) / 2, "정밀도": P, "재현율": R,
        "특이도": R0, "FPR": 1 - R0, "balanced": (R + R0) / 2,
        "MCC": (TP * TN - FP * FN) / den if den else 0.0,
    }


def mcnemar(a: dict, b: dict) -> tuple[int, int, float]:
    """같은 칸에 두 모델을 적용했으므로 대응표본이다. 양측 exact."""
    x = sum(1 for k in a if a[k][0] == a[k][1] and b[k][0] != b[k][1])
    y = sum(1 for k in a if b[k][0] == b[k][1] and a[k][0] != a[k][1])
    n = x + y
    if n == 0:
        return x, y, 1.0
    tail = sum(math.comb(n, i) for i in range(min(x, y) + 1))
    return x, y, min(1.0, 2 * tail / 2 ** n)


def main() -> int:
    gold = load_gold()
    C = {m: cells(m, gold) for m in MODELS}
    n = len(next(iter(C.values())))
    pos = sum(1 for _, want, _ in next(iter(C.values())).values() if want)

    print("=" * 74)
    print("exp05 재채점 — 속성 단위 «탐지» 성능 (2단 추론 성능이 아니다)")
    print("=" * 74)
    print(f"칸 {n}개 = 인물 {n // len(ATTRS)}명 × 속성 {len(ATTRS)}개")
    print(f"클래스 분포  양성 {pos} ({pos/n:.1%}) · 음성 {n-pos} ({(n-pos)/n:.1%})")
    print(f"⚠️ 다수 클래스로만 찍는 더미의 정확도 = {max(pos, n-pos)/n:.1%}")
    print("   정확도를 단독으로 읽으면 안 되는 이유다 [MF-012]\n")

    hdr = f"{'':7}{'정확도':>8}{'F1양성':>8}{'F1음성':>8}{'macroF1':>9}{'특이도':>8}{'재현율':>8}{'MCC':>7}"
    print(hdr); print("-" * len(hdr))
    for m in MODELS:
        s = metrics(*confusion(C[m]))
        print(f"{m:7}{s['정확도']:>8.3f}{s['F1_양성']:>8.3f}{s['F1_음성']:>8.3f}"
              f"{s['macroF1']:>9.3f}{s['특이도']:>8.3f}{s['재현율']:>8.3f}{s['MCC']:>7.3f}")

    print(f"\n{'':7}{'TP':>5}{'FP':>5}{'FN':>5}{'TN':>5}")
    for m in MODELS:
        print(f"{m:7}" + "".join(f"{v:>5}" for v in confusion(C[m])))

    x, y, p = mcnemar(C["4B"], C["1.7B"])
    print(f"\nMcNemar 정확검정 (대응표본)")
    print(f"  4B만 맞음 {x}칸 · 1.7B만 맞음 {y}칸 · 양측 p = {p:.4f}")
    print(f"  → {'유의 (p<.05)' if p < 0.05 else '⚠️ 유의하지 않다. 표본이 차이를 뒷받침하지 못한다'}")

    print("\n속성별 F1 (4B)")
    for a in ATTRS:
        sub = {k: v for k, v in C["4B"].items() if k[1] == a}
        TP, FP, FN, TN = confusion(sub)
        s = metrics(TP, FP, FN, TN)
        flag = "  ⚠️ 양성 표본 부족" if TP + FN < 10 else ""
        print(f"  {a:11} 양성 {TP+FN:>2}칸  F1 {s['F1_양성']:.3f}  FP {FP} · FN {FN}{flag}")

    fp = [(k[0], ev) for k, (pred, want, ev) in C["4B"].items()
          if k[1] == "location" and pred and not want]
    spans = {s["span_id"]: s for it in gold.values() for s in it["spans"]}
    trap = sum(1 for _, ev in fp if any(spans.get(e, {}).get("subject") == "other" for e in ev))
    print(f"\nlocation 오탐 {len(fp)}건 중 근거가 함정(subject:other) 스팬인 것: {trap}건")
    print("  → 모델이 «남의 거주지»를 «이 사람 거주지»로 채택한다. W4 학습 1순위 교정 목표")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
