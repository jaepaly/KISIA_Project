"""exp22 채점 — README §2 에 등록한 지표 · 교체 기준 그대로.

    PYTHONIOENCODING=utf-8 PYTHONPATH="src;." python experiments/exp22-stage2-judge/score.py

입력: results/raw_v1.jsonl · results/raw_v2.jsonl (run_stage2.py) · data/accounts.jsonl · data/stage1.jsonl
- 모델 출력 = validate_findings 결과(앱이 쓰는 것). None 이면 폴백 — 모델 출력 칸 7개는 불일치 · 근거 0
- 같은 입력의 규칙 = 그 구성이 보낸 입력(상한 적용 뒤)으로 rules.findings_from_spans
- 전체 스팬의 규칙 = 1단 본인 스팬 전부(상한 없음)로 rules.findings_from_spans — 두 구성에 같다
- 앱 최종 = 모델 출력이 있으면 그것 · 폴백이면 전체 스팬의 규칙 (infer.analyze 와 같다)
출력: results/metrics.json
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(HERE)]
from kopl.c4_stage2 import infer  # noqa: E402
from kopl.c4_stage2.rules import ATTRS, findings_from_spans  # noqa: E402
from run_stage2 import load_accounts, model_input  # noqa: E402

sys.path.insert(0, str(ROOT / "experiments/exp08-stage2-sft"))
from make_sft_v1 import user_ref  # noqa: E402

BOOT, SEED = 2000, 20261013
TRUTH = {"E": "specified", "I": "narrowed", "N": "abstain"}


def cells(config: str, raw_rows: dict[str, dict], accounts: list[dict]) -> list[dict]:
    out = []
    for acc in accounts:
        _, _, entries = model_input(config, user_ref(acc["account_id"]), acc["posts"])
        full = [{"post_id": p["post_id"], "spans": infer.pseudonymize_spans(p)} for p in acc["posts"]]
        same, whole = findings_from_spans(entries), findings_from_spans(full)
        r = raw_rows[acc["account_id"]]
        assert [e["post_id"] for e in entries] == [e["post_id"] for e in r["entries"]], "입력이 실행 때와 다르다"
        model = r["validated"]
        for attr in ATTRS:
            m = model[attr] if model else None
            final = m if m else whole[attr]
            out.append({"account_id": acc["account_id"], "attr": attr, "fallback": model is None,
                        "model": m["verdict"] if m else None, "same": same[attr]["verdict"], "whole": whole[attr]["verdict"],
                        "final": final["verdict"],
                        "pred_ev": {(e["post_id"], e["span_id"]) for e in (m["evidence"] if m else [])},
                        "gold_ev": {(e["post_id"], e["span_id"]) for e in same[attr]["evidence"]}})
    return out


def metrics(cs: list[dict]) -> dict:
    n = len(cs)
    m1 = sum(c["model"] == c["same"] for c in cs) / n
    nab = [c for c in cs if c["same"] != "abstain"]
    m2 = sum(c["model"] == c["same"] for c in nab) / len(nab) if nab else None
    tp = sum(len(c["pred_ev"] & c["gold_ev"]) for c in cs)
    pp, gp = sum(len(c["pred_ev"]) for c in cs), sum(len(c["gold_ev"]) for c in cs)
    p, r = (tp / pp if pp else 0.0), (tp / gp if gp else 0.0)
    m3 = 2 * p * r / (p + r) if p + r else 0.0
    m4 = len({c["account_id"] for c in cs if c["fallback"]})
    m5 = sum(c["final"] == c["whole"] for c in cs) / n
    return {"cells": n, "M1": round(m1, 4), "M2": None if m2 is None else round(m2, 4), "M2_cells": len(nab),
            "M3": round(m3, 4), "M3_pr": [round(p, 4), round(r, 4)], "M4": m4, "M5": round(m5, 4)}


def by_attr(cs: list[dict]) -> dict:
    return {attr: f"{sum(c['model'] == c['same'] for c in cs if c['attr'] == attr)}/{sum(c['attr'] == attr for c in cs)}" for attr in ATTRS}


def bootstrap_m1_diff(c1: list[dict], c2: list[dict]) -> list[float]:
    accs = sorted({c["account_id"] for c in c1})
    per = {k: {} for k in ("v1", "v2")}
    for key, cs in (("v1", c1), ("v2", c2)):
        for a in accs:
            sub = [c for c in cs if c["account_id"] == a]
            per[key][a] = (sum(c["model"] == c["same"] for c in sub), len(sub))
    rng, diffs = random.Random(SEED), []
    for _ in range(BOOT):
        pick = [rng.choice(accs) for _ in accs]
        h1 = sum(per["v1"][a][0] for a in pick) / sum(per["v1"][a][1] for a in pick)
        h2 = sum(per["v2"][a][0] for a in pick) / sum(per["v2"][a][1] for a in pick)
        diffs.append(h2 - h1)
    diffs.sort()
    return [round(diffs[int(0.025 * BOOT)], 4), round(diffs[int(0.975 * BOOT) - 1], 4)]


def reference(cs: list[dict]) -> dict:
    """참고 — 심은 속성 정답과 앱 최종. 검토에서 뺀 칸 · N 표시 칸 · 유효한 심은 표현이 다 빠진 칸은 분모에서 뺀다"""
    acc = {json.loads(l)["account_id"]: json.loads(l) for l in (HERE / "data/accounts.jsonl").read_text(encoding="utf-8").splitlines() if l}
    hit = tot = 0
    for c in cs:
        a = acc[c["account_id"]]
        cond = a["conditions"][c["attr"]]
        if c["attr"] in a["review"]["cells_excluded"] or c["attr"] in a["review"]["n_flagged"]:
            continue
        if cond != "N" and not any(x.get("attr") == c["attr"] and not x.get("excluded") for p in a["posts"] for x in p["planted"]):
            continue
        tot += 1
        hit += c["final"] == TRUTH[cond]
    return {"cells": tot, "agree": round(hit / tot, 4) if tot else None}


def main() -> int:
    accounts = load_accounts()
    raw = {cfg: {r["account_id"]: r for r in map(json.loads, (HERE / f"results/raw_{cfg}.jsonl").read_text(encoding="utf-8").splitlines()) if r}
           for cfg in ("v1", "v2")}
    cs = {cfg: cells(cfg, raw[cfg], accounts) for cfg in ("v1", "v2")}
    res = {cfg: {**metrics(cs[cfg]), "M1_by_attr": by_attr(cs[cfg]), "reference_planted": reference(cs[cfg]),
                 "seconds_mean": round(sum(r["seconds"] for r in raw[cfg].values()) / len(raw[cfg]), 1),
                 "prompt_tokens_max": max(r["prompt_tokens"] for r in raw[cfg].values()),
                 "truncated": sum(r["truncated"] for r in raw[cfg].values())} for cfg in ("v1", "v2")}
    ci = bootstrap_m1_diff(cs["v1"], cs["v2"])
    v1, v2 = res["v1"], res["v2"]
    criteria = {
        "1 M1 +0.05 · CI 아래끝 > 0": v2["M1"] - v1["M1"] >= 0.05 and ci[0] > 0,
        "2 M2 v1 이상": v2["M2"] is not None and v1["M2"] is not None and v2["M2"] >= v1["M2"],
        "3 M3 -0.05 이내": v2["M3"] >= v1["M3"] - 0.05,
        "4 M4 v1 이하 · 3 이하": v2["M4"] <= v1["M4"] and v2["M4"] <= 3,
        "5 M5 -0.02 이내": v2["M5"] >= v1["M5"] - 0.02,
        "6 exp09 회귀": "따로 — README §2 6번",
    }
    res["M1_diff_ci95"] = ci
    res["criteria"] = criteria
    (HERE / "results/metrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
