"""exp24 채점 — README §5 채택 기준 셋을 그대로 계산한다 (기준은 결과 보기 전에 커밋 · 6e416b3).

    PYTHONIOENCODING=utf-8 python experiments/exp24-cpu-accel/score.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "exp06-finetune"))
sys.path.insert(0, str(HERE))
RESULTS = HERE / "results"

SPAN_AGREEMENT_MIN = 0.98
F1_DROP_MAX = 0.005
EXP17_SELF_DROP_MAX = 1
P95_CUT_MIN = 0.30


def _exp17_score():
    spec = importlib.util.spec_from_file_location("exp17_score", ROOT / "experiments/exp17-planted-eval/score.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load(path: Path) -> dict[str, list[dict]]:
    out = {}
    for line in open(path, encoding="utf-8"):
        row = json.loads(line)
        if row["post_id"] in out:
            raise ValueError(f"중복 post_id: {row['post_id']}")
        out[row["post_id"]] = row["spans"]
    return out


def span_set(preds: dict[str, list[dict]], tag: str) -> set[tuple]:
    return {(tag, pid, s["text_id"], s["start"], s["end"], s["type"]) for pid, spans in preds.items() for s in spans}


def dev_f1(gold: dict[str, dict], preds: dict[str, list[dict]]) -> dict:
    import train

    if set(preds) != set(gold):
        raise ValueError("dev 예측 글이 골드와 다르다")
    truth, guessed = {}, {}
    for pid, row in gold.items():
        for tid in row["texts"]:
            truth[(pid, tid)] = {(s["start"], s["end"], s["type"]) for s in row["spans"] if s["text_id"] == tid}
            guessed[(pid, tid)] = {(s["start"], s["end"], s["type"]) for s in preds[pid] if s["text_id"] == tid}
    o = train.score_span_sets(truth, guessed)["overall"]
    return {k: o[k] for k in ("tp", "fp", "fn", "precision", "recall", "f1")}


def exp17_self(preds: dict[str, list[dict]]) -> dict:
    sc = _exp17_score()
    gold = [json.loads(l) for l in open(sc.DATA, encoding="utf-8")]
    if set(preds) != {g["post_id"] for g in gold}:
        raise ValueError("exp17 예측 글이 평가셋 80편과 다르다")
    r = sc.evaluate(gold, preds)
    hit = tot = 0
    for key, frac in r["recall_by_type"].items():
        if key.endswith("/self"):
            h, t = map(int, frac.split("/"))
            hit, tot = hit + h, tot + t
    return {"self_hit": hit, "self_total": tot, "recall_self": r["recall_self"], "recall_all": r["recall_all"]}


def main() -> int:
    import run

    gold = run.dev_gold_posts()
    base = {n: load(RESULTS / f"preds_{n}_fp32.jsonl") for n in ("dev", "exp17")}
    cand = {n: load(RESULTS / f"preds_{n}_int8.jsonl") for n in ("dev", "exp17")}
    # 첫 실행(10/13)은 test 를 잘못 읽어(메타 dict 의 키 6개) dev 에 test 231편이 섞였다 — 저장된 예측에서 걸러 다시 채점한다
    # 알려진 test 글만 뺀다 — 그 밖에 골드에 없는 글은 입력 누락 · 오염이니 멈춘다 (B 리뷰 #350)
    test = run.test_post_ids()
    for preds in (base["dev"], cand["dev"]):
        extra = set(preds) - set(gold)
        if extra - test:
            raise SystemExit(f"골드에 없는 글 {len(extra - test)}편 (test 아님): {sorted(extra - test)[:5]}")
        for pid in extra:
            del preds[pid]

    a = span_set(base["dev"], "dev") | span_set(base["exp17"], "exp17")
    b = span_set(cand["dev"], "dev") | span_set(cand["exp17"], "exp17")
    agreement = len(a & b) / len(a | b) if a | b else 1.0

    f1_base, f1_cand = dev_f1(gold, base["dev"]), dev_f1(gold, cand["dev"])
    e_base, e_cand = exp17_self(base["exp17"]), exp17_self(cand["exp17"])

    latency = {}
    for t in (4, 2):
        lb = json.loads((RESULTS / f"latency_fp32_t{t}.json").read_text(encoding="utf-8"))
        lc = json.loads((RESULTS / f"latency_int8_t{t}.json").read_text(encoding="utf-8"))
        latency[f"t{t}"] = {path: {"fp32": lb[path], "int8": lc[path],
                                   "p95_cut": 1 - lc[path]["p95_ms"] / lb[path]["p95_ms"]} for path in ("app", "model")}

    checks = {
        "1_span_agreement": {"value": round(agreement, 4), "min": SPAN_AGREEMENT_MIN,
                             "base_spans": len(a), "cand_spans": len(b), "only_base": len(a - b), "only_cand": len(b - a),
                             "pass": agreement >= SPAN_AGREEMENT_MIN},
        "2a_dev_f1_drop": {"fp32": f1_base, "int8": f1_cand, "drop": round(f1_base["f1"] - f1_cand["f1"], 4),
                           "max": F1_DROP_MAX, "pass": f1_base["f1"] - f1_cand["f1"] <= F1_DROP_MAX},
        "2b_exp17_self_drop": {"fp32": e_base, "int8": e_cand, "drop": e_base["self_hit"] - e_cand["self_hit"],
                               "max": EXP17_SELF_DROP_MAX,
                               "pass": e_base["self_hit"] - e_cand["self_hit"] <= EXP17_SELF_DROP_MAX},
        "3_p95_cut": {**{t: round(v["app"]["p95_cut"], 3) for t, v in latency.items()}, "min": P95_CUT_MIN,
                      "pass": all(v["app"]["p95_cut"] >= P95_CUT_MIN for v in latency.values())},
    }
    out = {"checks": checks, "adopt": all(c["pass"] for c in checks.values()), "latency": latency,
           "meta": {m: json.loads((RESULTS / f"preds_{m}_meta.json").read_text(encoding="utf-8")) for m in ("fp32", "int8")}}
    (RESULTS / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for k, c in checks.items():
        print(k, "통과" if c["pass"] else "미달", {x: y for x, y in c.items() if x not in ("pass", "fp32", "int8")})
    print("채택" if out["adopt"] else "미채택")
    return 0


if __name__ == "__main__":
    sys.exit(main())
