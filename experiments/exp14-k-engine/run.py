"""exp14 — estimate_k 검증: 글이 쌓이면 k 가 내려가는가 · 사람마다 갈리는가 · LLM 추론 성공과 맞는가 (#302).

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp14-k-engine/run.py

- 표본: exp11 인물 10명 × 누적 창 7개 = 70개 (같은 글 묶음 · 같은 최상위 골드 스팬 · 위치태그 없음 — exp11 위험도와 같은 입력)
- LLM 성공 수: exp11 `results/teacher_window_scores.csv` 의 success_count (E03 현 거주지 기준 — exp11 주 분석)
- 비교 기준: exp11 위험도(our_risk) · 글 수
- 점수: −log10(k) — k 가 작을수록 위험. 조건이 없는 창(k=null)은 전 국민으로 둔다 (좁혀지지 않음)
- α 민감도는 **튜닝군 5명에서만** 본다 (exp11 과 같은 분리). 보고 수치는 α=0.6 고정
"""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP11 = ROOT / "experiments/exp11-risk-correlation"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


run11 = _load("exp11_run", EXP11 / "run.py")
score11 = _load("exp11_score", EXP11 / "score.py")

from kopl.c2_specificity.k_engine import DEFAULT_PRIORS_PATH, _default_index, conditions_from_posts, estimate_k_trace  # noqa: E402

NATION = None  # 첫 계산에서 채운다
CURRENT_CITY = {"E03": None}  # exp11 §4 — E03 현 거주지는 상하이(국내 사전 밖)라 위치 대조에서 뺀다


def truth_codes(pid: str) -> frozenset[str]:
    """인물 정답 위치 → 읍면동 집합 (위치 대조용)."""
    if pid in CURRENT_CITY:
        return frozenset()
    idx = _default_index()
    full = json.loads((ROOT / f"data/corpus/v0/personas/{pid}.json").read_text(encoding="utf-8"))["ground_truth"]["location"]
    toks = full.split()
    for n in range(len(toks), 0, -1):
        info = idx.d.resolve_info(toks[n - 1], context=" ".join(toks[: n - 1]) or None)
        out: set[str] = set()
        for c in info.get("codes") or []:
            out |= idx.emds(c)
        if out:
            return frozenset(out)
    return frozenset()


def windows_with_k(priors_path: str | None = None) -> list[dict]:
    global NATION
    scores = {(r["persona_id"], int(r["window_size"])): r
              for r in csv.DictReader((EXP11 / "results/teacher_window_scores.csv").open(encoding="utf-8-sig"))}
    rows = []
    for pid in run11.select_personas():
        spans = run11.load_gold_spans(pid)
        for w in run11.build_windows(pid):
            posts = [{"post_id": p, "spans": spans.get(p, [])} for p in w["post_ids"]]
            out, trace = estimate_k_trace(conditions_from_posts(posts), priors_path=priors_path)
            codes = trace["codes"]
            truth = truth_codes(pid)
            if NATION is None:
                NATION = out["steps"][0]["n_after"] if out["steps"] else 51_088_284
            k = out["k"] if out["k"] is not None else NATION
            s = scores[(pid, w["window_size"])]
            rows.append({
                "persona_id": pid, "split": s["split"], "window_size": w["window_size"],
                "k": k, "k_level": out["k_level"], "neg_log10_k": round(-math.log10(k), 6),
                "our_risk": float(s["our_risk"]), "success_count": int(s["success_count"]),
                "floor_applied": out["floor_applied"],
                "location_steps": sum(1 for st in out["steps"] if st["axis"] == "location") - 1,
                "n_location_codes": len(codes),
                "narrowed_by_location": bool(codes),  # 강한 위치 단서로 후보 동네를 실제로 정했다 (약한 단서는 비율만)
                "truth_known": bool(truth),
                "location_contains_truth": bool(codes & truth),
                "supported_contains_truth": bool(trace["most_supported_codes"] & truth),
                "location_states": trace["location_states"],
            })
    return rows


def correlations(rows: list[dict]) -> dict:
    """exp11 baseline_checks 를 같은 방식으로 — our_risk 자리에 −log10 k 를 넣는다."""
    as_risk = [{**r, "our_risk": r["neg_log10_k"]} for r in rows]
    base = score11.baseline_checks(as_risk)
    rho = spearmanr([r["neg_log10_k"] for r in rows], [r["success_count"] for r in rows]).statistic
    return {"n": len(rows), "rho_k_success": round(float(rho), 4),
            "partial_rho_given_window_size": round(base["partial_rho_given_window_size"], 4),
            "rho_window_size_baseline": round(base["rho_window_size_baseline"], 4),
            "within_window_rho": {k: (round(v, 4) if v is not None else None) for k, v in base["within_window_rho"].items()},
            "within_window_shuffle_p": base["within_window_shuffle"]["p_one_sided"]}


def main() -> int:
    rows = windows_with_k()
    by_p: dict[str, list[dict]] = {}
    for r in rows:
        by_p.setdefault(r["persona_id"], []).append(r)
    mono = {p: all(b["k"] <= a["k"] for a, b in zip(v, v[1:])) for p, v in by_p.items()}
    dropped = {p: v[-1]["k"] < v[0]["k"] for p, v in by_p.items()}
    w19 = [v[-1] for v in by_p.values()]

    risk_rows = [{**r} for r in rows]
    risk_base = score11.baseline_checks(risk_rows)
    risk_rho = spearmanr([r["our_risk"] for r in rows], [r["success_count"] for r in rows]).statistic

    # α 민감도 — 튜닝군에서만
    priors = json.loads(Path(DEFAULT_PRIORS_PATH).read_text(encoding="utf-8"))
    tuning = []
    for alpha in (0.4, 0.6, 0.8, 1.0):  # exp11 튜닝군 split 값은 "tune"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({**priors, "alpha": alpha}, f, ensure_ascii=False)
        rs = [r for r in windows_with_k(f.name) if r["split"] == "tune"]
        Path(f.name).unlink()
        c = correlations(rs)
        tuning.append({"alpha": alpha, "rho": c["rho_k_success"], "partial": c["partial_rho_given_window_size"]})

    res = {
        "sample": "exp11 10명 × 창 7개 = 70 · 최상위 골드 스팬 · 위치태그 없음",
        "criteria": {
            "k_dropped_w1_to_w19": f"{sum(dropped.values())}/{len(dropped)} (기준 ≥ 8)",
            "monotonic_non_increasing": f"{sum(mono.values())}/{len(mono)} (기준 10/10)",
            "distinct_k_at_w19": f"{len({r['k'] for r in w19})}/{len(w19)} (기준 ≥ 9)",
            "w19_not_narrowed_by_location": sum(1 for r in w19 if not r["narrowed_by_location"]),
            "w19_location_contains_truth": f"{sum(r['location_contains_truth'] for r in w19 if r['narrowed_by_location'] and r['truth_known'])}/{sum(1 for r in w19 if r['narrowed_by_location'] and r['truth_known'])} (위치로 좁혀진 인물 중 — k 의 후보 동네가 실제 사는 곳을 포함 · E03 제외)",
            "all_windows_location_contains_truth": f"{sum(r['location_contains_truth'] for r in rows if r['narrowed_by_location'] and r['truth_known'])}/{sum(1 for r in rows if r['narrowed_by_location'] and r['truth_known'])}",
            "all_windows_supported_contains_truth": f"{sum(r['supported_contains_truth'] for r in rows if r['narrowed_by_location'] and r['truth_known'])}/{sum(1 for r in rows if r['narrowed_by_location'] and r['truth_known'])} (참고 — 가장 뒷받침 많은 위치 묶음)",
            "windows_with_multiple_location_states": sum(1 for r in rows if r["location_states"] > 1),
        },
        "w19": {r["persona_id"]: {"k": r["k"], "k_level": r["k_level"], "success": r["success_count"],
                                  "risk": r["our_risk"]} for r in w19},
        "k_vs_llm": {"all": correlations(rows),
                     "tuning": correlations([r for r in rows if r["split"] == "tune"]),
                     "report": correlations([r for r in rows if r["split"] == "report"])},
        "risk_vs_llm_exp11": {"rho": round(float(risk_rho), 4),
                              "partial_rho_given_window_size": round(risk_base["partial_rho_given_window_size"], 4)},
        "alpha_sensitivity_tuning_only": tuning,
        "floor_applied_windows": sum(r["floor_applied"] for r in rows),
        "monotonic_violations": {p: [(a["window_size"], a["k"], b["window_size"], b["k"])
                                     for a, b in zip(v, v[1:]) if b["k"] > a["k"]] for p, v in by_p.items() if not mono[p]},
    }
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results/metrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    with (HERE / "results/windows.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(json.dumps({k: res[k] for k in ("criteria", "risk_vs_llm_exp11", "alpha_sensitivity_tuning_only")}, ensure_ascii=False, indent=1))
    print("k_vs_llm all:", json.dumps(res["k_vs_llm"]["all"], ensure_ascii=False))
    print("report:", res["k_vs_llm"]["report"]["rho_k_success"], res["k_vs_llm"]["report"]["partial_rho_given_window_size"])
    print("w19:", json.dumps(res["w19"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
