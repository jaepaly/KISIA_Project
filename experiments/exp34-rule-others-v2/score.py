"""exp34 채점 (README §2 — 구현 결과 전 고정). exp33 score.py 와 같은 방식에 판정셋 · 패턴별 판정 · 시간을 더했다.

    PYTHONIOENCODING=utf-8 python experiments/exp34-rule-others-v2/score.py --base <main 의 attributes.py> [--new src/kopl/c1_span/attributes.py]

판정셋: data/heldout/pos.jsonl(Claude · pos) · neg.jsonl(Codex · neg 와 pos-hard). excluded 줄은 뺀다.
기준 1 은 pos 로, 기준 2 · 3 은 「반례」 = neg + pos-hard 로 잰다(pos-hard 는 정답 other 인데 인용 · 묻다가 섞여 규칙이 self 로 둘 위험이 있는 문장).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("score33", ROOT / "experiments/exp33-rule-others/score.py")
s33 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s33)


def rows(name: str) -> list[dict]:
    return [r for r in (json.loads(l) for l in open(HERE / "data" / "heldout" / name, encoding="utf-8")) if not r.get("excluded")]


def worst_time(m) -> float:
    worst = 0.0
    for text in (" " * 5000 + "마음만은 열여덟", "옆집 할머니" + " " * 5000 + "여든둘", "아부지 " * 1500, ("마음은 " * 1200) + "열여덟"):
        span = text.split()[-1]
        a = text.rindex(span)
        for stype in ("AGE", "SEX", "JOB"):
            t = time.perf_counter()
            m.subject_of(stype, span, text, a, a + len(span))
            worst = max(worst, time.perf_counter() - t)
    return round(worst, 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--new", type=Path, default=ROOT / "src/kopl/c1_span/attributes.py")
    a = ap.parse_args()
    A, R = s33.mod(a.base, "attr_base"), s33.mod(a.new, "attr_new")
    out: dict = {"patterns": {}}
    for pat in ("P1", "P2", "P3"):
        pos = [c for c in rows("pos.jsonl") if c["pattern"] == pat]
        rev = [c for c in rows("neg.jsonl") if c["pattern"] == pat]
        p = {"pos_n": len(pos), "pos_A": 0, "pos_R": 0, "rev_n": len(rev), "rev_A": 0, "rev_R": 0, "rev_new_wrong": [], "pos_R_wrong": []}
        for c in pos:
            ra, rr = s33.run_case(A, c), s33.run_case(R, c)
            p["pos_A"] += ra == c["subject"]
            p["pos_R"] += rr == c["subject"]
            if rr != c["subject"]:
                p["pos_R_wrong"].append(f'{c["id"]}:{rr}')
        for c in rev:
            ra, rr = s33.run_case(A, c), s33.run_case(R, c)
            p["rev_A"] += ra == c["subject"]
            p["rev_R"] += rr == c["subject"]
            if ra == c["subject"] and rr != c["subject"]:
                p["rev_new_wrong"].append(f'{c["id"]}:{rr}')
        p["pos_rate"] = round(p["pos_R"] / p["pos_n"], 3)
        p["pass"] = p["pos_rate"] >= 0.75 and len(p["rev_new_wrong"]) <= 1   # 기준 1 · 2 (패턴별)
        out["patterns"][pat] = p
    g = {w: {"n": 0, "A_agree": 0, "R_agree": 0, "lost": 0, "fixed": 0} for w in ("reviewed", "all")}
    for pid, rev, s, text, piece in s33.gold_spans():
        sa = A.subject_of(s["type"], piece, text, s["start"], s["end"])
        sr = R.subject_of(s["type"], piece, text, s["start"], s["end"])
        for w in ("reviewed", "all"):
            if w == "reviewed" and not rev:
                continue
            x = g[w]
            x["n"] += 1
            x["A_agree"] += sa == s["subject"]
            x["R_agree"] += sr == s["subject"]
            x["lost"] += sa == s["subject"] and sr != s["subject"]
            x["fixed"] += sa != s["subject"] and sr == s["subject"]
    out["gold"] = g
    out["time_worst_sec"] = {"A": worst_time(A), "R": worst_time(R)}
    P = out["patterns"]
    out["checks"] = {
        "patterns_pass": {k: v["pass"] for k, v in P.items()},
        "rev_new_wrong_total_le_3": sum(len(v["rev_new_wrong"]) for v in P.values()) <= 3,
        "rev_R_ge_A": sum(v["rev_R"] for v in P.values()) >= sum(v["rev_A"] for v in P.values()),
        "gold": g["reviewed"]["lost"] <= 1 and g["all"]["lost"] <= 5 and g["all"]["R_agree"] >= g["all"]["A_agree"],
        "time_le_0.05": out["time_worst_sec"]["R"] <= 0.05,
    }
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
