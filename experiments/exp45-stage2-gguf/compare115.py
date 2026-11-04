"""결과 3 요약 — run_validate115.py 의 NF4 · GGUF JSONL 두 개를 칸마다 비교해 요약 JSON 을 쓴다(원문 없음).

    python experiments/exp45-stage2-gguf/compare115.py --nf4 <validate115_nf4.jsonl> --gguf <validate115_gguf.jsonl> \\
        --sns-db <Veilo 3100 DB> --out experiments/exp45-stage2-gguf/results/validate115.json

- 판정 칸 = 계정 × 7속성의 verdict. 근거는 span_id 집합 · 신뢰도 · 범위(granularity)는 따로 센다
- 위험도 · 추천은 빠른 결과의 값(analyze 가 findings 와 무관하게 스팬으로 계산 — infer.analyze)이라 두 실행의 1단 · 규칙 경로가 같은지를 본다
- 규칙(rules-v1) 판정도 같이 적는다 — 다른 칸에서 어느 쪽이 규칙과 같은지
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from collections import Counter
from pathlib import Path

ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")


def load(p: Path) -> dict[str, dict]:
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {r["user_ref"]: r for r in rows}


def timing(rows: list[dict]) -> dict:
    done = [r for r in rows if r.get("status") == "done"]
    med = lambda xs: round(statistics.median(xs), 2) if xs else None  # noqa: E731
    return {"fast_median_s": med([r["fast_s"] for r in rows]),
            "precise_median_s": med([r["precise_s"] for r in done]),
            "model_only_median_s": med([r["precise_s"] - r["fast_s"] for r in done]),
            "precise_max_s": max((r["precise_s"] for r in done), default=None),
            "status": dict(Counter(str(r.get("status")) for r in rows)),
            "fallback_reasons": dict(Counter(str(r.get("reason")) for r in rows if r.get("status") != "done")),
            "model_version": sorted({str(r.get("model_version")) for r in done})}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nf4", type=Path, required=True)
    ap.add_argument("--gguf", type=Path, required=True)
    ap.add_argument("--sns-db", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    nf4, gguf = load(a.nf4), load(a.gguf)
    con = sqlite3.connect(f"file:{a.sns_db.as_posix()}?mode=ro", uri=True)
    pid = dict((u, p) for p, u in con.execute("SELECT author_id, user_ref FROM authors"))
    con.close()
    users = sorted(set(nf4) & set(gguf), key=lambda u: pid.get(u, u))
    c = Counter()
    diffs, ev_diffs, rule_disagree = [], [], Counter()
    for u in users:
        n, g = nf4[u], gguf[u]
        c["risk_same"] += n["risk"] == g["risk"]
        c["rec_same"] += n["rec_sha"] == g["rec_sha"]
        c["fast_same"] += n["fast"] == g["fast"]
        if n.get("status") != "done" or g.get("status") != "done":
            c["accounts_not_both_done"] += 1
            continue
        c["accounts_both_done"] += 1
        for at in ATTRS:
            nc, gc, rc = n["model"].get(at), g["model"].get(at), n["fast"].get(at)
            c["cells"] += 1
            same_v = nc["verdict"] == gc["verdict"]
            c["verdict_same"] += same_v
            c["evidence_same"] += nc["evidence"] == gc["evidence"]
            c["granularity_same"] += nc["granularity"] == gc["granularity"]
            c["confidence_same"] += nc["confidence"] == gc["confidence"]
            c["cell_identical"] += nc == gc
            rule_disagree["nf4"] += nc["verdict"] != rc["verdict"]
            rule_disagree["gguf"] += gc["verdict"] != rc["verdict"]
            if not same_v:
                diffs.append({"persona": pid.get(u), "user_ref": u, "attr": at, "rules": rc["verdict"],
                              "nf4": {k: nc[k] for k in ("verdict", "granularity", "confidence", "evidence")},
                              "gguf": {k: gc[k] for k in ("verdict", "granularity", "confidence", "evidence")}})
            elif nc["evidence"] != gc["evidence"]:
                ev_diffs.append({"persona": pid.get(u), "user_ref": u, "attr": at, "verdict": nc["verdict"],
                                 "nf4_only": sorted(set(nc["evidence"]) - set(gc["evidence"])),
                                 "gguf_only": sorted(set(gc["evidence"]) - set(nc["evidence"]))})
    out = {"accounts": {"nf4": len(nf4), "gguf": len(gguf), "both": len(users)},
           "counts": dict(c), "model_vs_rules_verdict_diff": dict(rule_disagree),
           "timing": {"nf4": timing(list(nf4.values())), "gguf": timing(list(gguf.values()))},
           "verdict_diffs": diffs, "evidence_diffs_same_verdict": ev_diffs}
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("accounts", "counts", "model_vs_rules_verdict_diff", "timing")},
                     ensure_ascii=False, indent=1))
    print("verdict diffs", len(diffs), "evidence-only diffs", len(ev_diffs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
