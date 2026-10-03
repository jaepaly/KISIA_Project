"""exp09 채점 — Qwen vs 외부 LLM verdict 일치율 + MF-012 보조 지표 → results/metrics.json

    python experiments/exp09-external-agreement/score.py [--pilot] [--boot 2000]

칸 = 인물 × 7속성. 파싱 실패는 'invalid' 로 두고 본 지표에서는 불일치로 센다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")
CLASSES = ("specified", "narrowed", "weak_signal", "abstain")
POS = {"specified", "narrowed"}
INVALID = "invalid"


def load(path: Path) -> dict[str, dict]:
    return {json.loads(l)["persona_id"]: json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


def verdicts(rec: dict | None) -> dict[str, str]:
    f = (rec or {}).get("findings") or {}
    out = {}
    for a in ATTRS:
        v = (f.get(a) or {}).get("verdict") if isinstance(f.get(a), dict) else None
        out[a] = v if v in CLASSES else INVALID
    return out


def evidence(rec: dict | None, attr: str) -> set[str]:
    f = ((rec or {}).get("findings") or {}).get(attr) or {}
    return {e.get("span_id") for e in f.get("evidence") or [] if isinstance(e, dict)}


def agreement(pairs):
    return sum(a == b != INVALID for a, b in pairs) / len(pairs) if pairs else None


def kappa(pairs):
    pairs = [(a, b) for a, b in pairs if INVALID not in (a, b)]
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[c] * cb[c] for c in CLASSES) / n / n
    return (po - pe) / (1 - pe) if pe < 1 else None


def gwet_ac1(pairs):
    pairs = [(a, b) for a, b in pairs if INVALID not in (a, b)]
    n, q = len(pairs), len(CLASSES)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    pi = {c: (sum(a == c for a, _ in pairs) + sum(b == c for _, b in pairs)) / (2 * n) for c in CLASSES}
    pe = sum(p * (1 - p) for p in pi.values()) / (q - 1)
    return (po - pe) / (1 - pe)


def mcc_multi(ref, pred):
    """Gorodkin 다중 클래스 MCC. invalid 는 별도 클래스로 둔다."""
    labels = sorted(set(ref) | set(pred))
    n = len(ref)
    c = sum(r == p for r, p in zip(ref, pred))
    t, pr = Counter(ref), Counter(pred)
    num = c * n - sum(t[k] * pr[k] for k in labels)
    den = math.sqrt((n * n - sum(pr[k] ** 2 for k in labels)) * (n * n - sum(t[k] ** 2 for k in labels)))
    return num / den if den else None


def macro_f1(ref, pred):
    f1s = []
    for c in CLASSES:
        tp = sum(r == c and p == c for r, p in zip(ref, pred))
        fp = sum(r != c and p == c for r, p in zip(ref, pred))
        fn = sum(r == c and p != c for r, p in zip(ref, pred))
        if tp + fp + fn:
            f1s.append(2 * tp / (2 * tp + fp + fn))
    return sum(f1s) / len(f1s) if f1s else None


def binary(ref, pred):
    """양성 = specified·narrowed. invalid 예측은 음성으로 두지 않고 오답으로 센다. invalid 기준값 칸은 뺀다."""
    excluded = sum(r == INVALID for r in ref)
    pairs = [(r, p) for r, p in zip(ref, pred) if r != INVALID]
    ref, pred = [r for r, _ in pairs], [p for _, p in pairs]
    tp = sum(r in POS and p in POS for r, p in zip(ref, pred))
    fn = sum(r in POS and p not in POS for r, p in zip(ref, pred))
    fp = sum(r not in POS and p in POS for r, p in zip(ref, pred))
    tn = sum(r not in POS and p not in POS and p != INVALID for r, p in zip(ref, pred))
    bad_neg = sum(r not in POS and p == INVALID for r, p in zip(ref, pred))
    fp_all = fp + bad_neg
    den = math.sqrt((tp + fp_all) * (tp + fn) * (tn + fp_all) * (tn + fn))
    return {
        "tp": tp, "fp": fp_all, "fn": fn, "tn": tn, "excluded_invalid_reference": excluded,
        "specificity": tn / (tn + fp_all) if tn + fp_all else None,
        "fpr": fp_all / (tn + fp_all) if tn + fp_all else None,
        "f1": 2 * tp / (2 * tp + fp_all + fn) if tp else 0.0,
        "mcc": (tp * tn - fp_all * fn) / den if den else None,
    }


def mcnemar(ref, a, b):
    """a·b 가 ref 를 맞혔는지의 대응표본 — exact 양측 이항검정."""
    b01 = sum(x == r and y != r for r, x, y in zip(ref, a, b))
    b10 = sum(x != r and y == r for r, x, y in zip(ref, a, b))
    n = b01 + b10
    if not n:
        return {"a_only_correct": 0, "b_only_correct": 0, "p": 1.0}
    k = min(b01, b10)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return {"a_only_correct": b01, "b_only_correct": b10, "p": p}


def r4(x):
    return None if x is None else round(x, 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20260928)
    ap.add_argument("--variant", default="base", help="외부 결과 변형 — base · verdictdef (#279)")
    a = ap.parse_args()
    data = HERE / "data"
    inputs = load(data / "inputs.jsonl")
    sfx = "_pilot" if a.pilot else ""
    vsfx = "" if a.variant == "base" else f"_{a.variant}"
    qwen, ext = load(data / f"qwen{sfx}.jsonl"), load(data / f"external{sfx}{vsfx}.jsonl")
    personas = sorted(set(qwen) & set(ext)) if a.pilot else sorted(inputs)
    missing = [p for p in personas if p not in qwen or p not in ext]

    cells = []  # (persona, attr, qwen, ext, rule)
    for p in personas:
        qv, ev, rv = verdicts(qwen.get(p)), verdicts(ext.get(p)), inputs[p]["rule_target"]
        for at in ATTRS:
            cells.append((p, at, qv[at], ev[at], rv[at]["verdict"]))

    def block(cs):
        qe = [(c[2], c[3]) for c in cs]
        valid = [x for x in qe if INVALID not in x]
        non_abs = [x for x in qe if x != ("abstain", "abstain")]
        rule, q, e = [c[4] for c in cs], [c[2] for c in cs], [c[3] for c in cs]
        return {
            "cells": len(cs),
            "agreement": r4(agreement(qe)),
            "agreement_dual_valid": r4(agreement(valid)),
            "agreement_non_abstain": r4(agreement(non_abs)), "non_abstain_cells": len(non_abs),
            "kappa": r4(kappa(qe)), "gwet_ac1": r4(gwet_ac1(qe)),
            "qwen_vs_external": {"macro_f1": r4(macro_f1(e, q)), "mcc": r4(mcc_multi(e, q)), "binary": binary(e, q)},
            "qwen_vs_rule": {"agreement": r4(agreement(list(zip(q, rule)))), "macro_f1": r4(macro_f1(rule, q)), "mcc": r4(mcc_multi(rule, q)), "binary": binary(rule, q)},
            "external_vs_rule": {"agreement": r4(agreement(list(zip(e, rule)))), "macro_f1": r4(macro_f1(rule, e)), "mcc": r4(mcc_multi(rule, e)), "binary": binary(rule, e)},
            "mcnemar_vs_rule_qwen_vs_external": mcnemar(rule, q, e),
            "always_abstain_vs_rule": r4(agreement([("abstain", r) for r in rule])),
        }

    # 인물 단위 cluster bootstrap — 본 지표 · κ
    rng = random.Random(a.seed)
    by_p: dict[str, list] = {}
    for c in cells:
        by_p.setdefault(c[0], []).append(c)
    boots_ag, boots_k = [], []
    for _ in range(a.boot):
        sample = [c for p in rng.choices(personas, k=len(personas)) for c in by_p[p]]
        boots_ag.append(agreement([(c[2], c[3]) for c in sample]))
        k = kappa([(c[2], c[3]) for c in sample])
        if k is not None:
            boots_k.append(k)

    def ci(xs):
        xs = sorted(xs)
        # nearest-rank: k = ceil(q·B), 0-기준 인덱스 k-1
        return [r4(xs[math.ceil(0.025 * len(xs)) - 1]), r4(xs[math.ceil(0.975 * len(xs)) - 1])] if xs else None

    seen = {p for p in personas if inputs[p]["seen_in_sft"]}
    has_clue = {p for p in personas if inputs[p]["kinds"].get("clue")}
    confusion = Counter((c[2], c[3]) for c in cells)
    ev_j = [len(evidence(qwen.get(c[0]), c[1]) & evidence(ext.get(c[0]), c[1])) /
            max(1, len(evidence(qwen.get(c[0]), c[1]) | evidence(ext.get(c[0]), c[1])))
            for c in cells if c[2] not in ("abstain", INVALID) and c[3] not in ("abstain", INVALID)]
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))

    def contract_violations(recs: dict) -> dict:
        """계약 Finding: abstain 이면 confidence ≤ 0.25 · evidence 비어 있음 · granularity null (stage2-io.schema.json)."""
        bad = Counter()
        for p in personas:
            for at, f in (((recs.get(p) or {}).get("findings")) or {}).items():
                if isinstance(f, dict) and f.get("verdict") == "abstain":
                    bad["abstain_confidence_gt_0.25"] += (f.get("confidence") or 0) > 0.25
                    bad["abstain_evidence_nonempty"] += bool(f.get("evidence"))
                    bad["abstain_granularity_not_null"] += f.get("granularity") is not None
        return dict(bad)

    def file_digest(path: Path) -> dict:
        b = path.read_bytes()
        return {"sha256": hashlib.sha256(b).hexdigest(), "rows": sum(1 for l in b.decode("utf-8").splitlines() if l.strip())}

    res = {
        "target": "agreement >= 0.8 ([목표] roadmap §5)",
        "definition": "7속성 × 인물 4종 verdict micro 정확 일치. 파싱 실패 = 불일치. 공유 골드 스팬 조건부",
        "personas": len(personas), "missing_outputs": missing,
        "parse_success": {"qwen": r4(sum(bool((qwen.get(p) or {}).get("findings")) for p in personas) / len(personas)),
                          "external": r4(sum(bool((ext.get(p) or {}).get("findings")) for p in personas) / len(personas))},
        "overall": {**block(cells), "agreement_ci95": ci(boots_ag), "kappa_ci95": ci(boots_k)},
        "strata": {
            "seen_in_sft": block([c for c in cells if c[0] in seen]),
            "unseen_in_sft": block([c for c in cells if c[0] not in seen]),
            "has_clue_post": block([c for c in cells if c[0] in has_clue]),
            "noise_only": block([c for c in cells if c[0] not in has_clue]),
        },
        "per_attr": {at: r4(agreement([(c[2], c[3]) for c in cells if c[1] == at])) for at in ATTRS},
        "confusion_qwen_rows_external_cols": {q: {e: confusion[(q, e)] for e in (*CLASSES, INVALID)} for q in (*CLASSES, INVALID)},
        "evidence_jaccard_both_positive": {"cells": len(ev_j), "mean": r4(sum(ev_j) / len(ev_j)) if ev_j else None},
        "models": {"qwen": next(iter(qwen.values()))["model"], "external": next(iter(ext.values()))["model"],
                   "external_served": sorted({m for r in ext.values() for m in r.get("served_model") or []})},
        "cost_usd_external": r4(sum(r.get("cost_usd") or 0 for r in ext.values())),
        "contract_finding_violations": {"qwen": contract_violations(qwen), "external": contract_violations(ext)},
        "external_variant": a.variant,
        "raw_outputs": {f: file_digest(data / f) for f in ("inputs.jsonl", f"qwen{sfx}.jsonl", f"external{sfx}{vsfx}.jsonl")},
        "external_routes": sorted({f"{r.get('route')}:{r.get('gateway_url_sha256_12')}" for r in ext.values()}),
        "invalid_policy": {
            "agreement": "invalid 는 불일치 (invalid-invalid 포함)",
            "kappa_ac1": "한쪽이라도 invalid 인 칸 제외",
            "mcc": "invalid 를 다섯 번째 클래스로 포함",
            "macro_f1": "4개 verdict 중 기준·예측 어디에도 없는 클래스는 평균에서 제외 (observed-class macro)",
            "binary": "invalid 예측 = 오답, invalid 기준값 칸 = 제외",
        },
        "sec": {"qwen_mean": r4(sum(r["sec"] for r in qwen.values()) / len(qwen)),
                "external_mean": r4(sum(r["sec"] for r in ext.values()) / len(ext))},
        "bootstrap": {"reps": a.boot, "seed": a.seed, "unit": "persona"},
        "inputs_manifest": manifest,
    }
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / f"metrics{sfx}{vsfx}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    o = res["overall"]
    print(f"agreement {o['agreement']} CI {o['agreement_ci95']} · κ {o['kappa']} · AC1 {o['gwet_ac1']} · "
          f"non-abstain {o['agreement_non_abstain']} (n={o['non_abstain_cells']}) · always-abstain baseline {o['always_abstain_vs_rule']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
