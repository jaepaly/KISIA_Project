"""exp27 채점 — 원래 · 숨긴 판을 1단 v2 앱 경로로 탐지해 엄격 · 느슨 재현율을 잰다 (README §3 · 결과 전 커밋 1bffc58).

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp27-adversarial/score.py --checkpoint <1단 v2 폴더>

`excluded` 가 달린 쌍은 뺀다. 출력: results/preds.jsonl · results/metrics.json
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT / "src", ROOT / "experiments" / "exp06-finetune", ROOT / "apps" / "analyzer" / "engines"):
    sys.path.insert(0, str(p))

LOCATION = {"LOC_ADMIN", "LOC_FACILITY", "REL_HOME"}


def iou(a: dict, b: dict) -> float:
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter / union if union else 0.0


def strict(gold: dict, spans: list[dict]) -> dict | None:
    return next((s for s in spans if s["type"] == gold["type"] and iou(gold, s) >= 0.5), None)


def loose(gold: dict, spans: list[dict]) -> dict | None:
    group = LOCATION if gold["type"] in LOCATION else {gold["type"]}
    return next((s for s in spans if s["type"] in group and s["start"] < gold["end"] and gold["start"] < s["end"]), None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    a = ap.parse_args()
    import torch
    import c1_rules
    import infer
    from kopl.c1_span.attributes import resolve

    torch.set_num_threads(4)
    det = infer.SpanDetector(a.checkpoint, device="cpu", min_span_score=0.7)
    rows = [json.loads(l) for l in open(HERE / "data" / "posts.jsonl", encoding="utf-8")]
    rows = [r for r in rows if not r.get("excluded")]
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    res = {}
    with open(out / "preds.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            spans = c1_rules.detect(det, {"post_id": r["post_id"], "body": r["texts"]["body"]}, resolve)["spans"]
            spans = [{k: s[k] for k in ("text_id", "start", "end", "type", "text", "level", "subject")} for s in spans if s["text_id"] == "body"]
            f.write(json.dumps({"post_id": r["post_id"], "spans": spans}, ensure_ascii=False) + "\n")
            g = r["planted"][0]
            st, lo = strict(g, spans), loose(g, spans)
            res[(r["pair"], r["variant"])] = {"strict": st is not None, "loose": lo is not None,
                                              "subject": (st or lo or {}).get("subject"), "type": g["type"],
                                              "technique": r["technique"], "found": (st or lo or {}).get("text")}
    pairs = sorted({p for p, _ in res if (p, "plain") in res and (p, "hidden") in res})

    def rate(variant: str, kind: str, keep=lambda x: True) -> str:
        sel = [res[(p, variant)] for p in pairs if keep(res[(p, variant)])]
        return f"{sum(x[kind] for x in sel)}/{len(sel)}"

    summary = {"pairs": len(pairs)}
    for kind in ("strict", "loose"):
        summary[kind] = {
            "plain": rate("plain", kind), "hidden": rate("hidden", kind),
            "plain_hit_hidden_miss": sum(res[(p, "plain")][kind] and not res[(p, "hidden")][kind] for p in pairs),
            "hidden_hit_plain_miss": sum(res[(p, "hidden")][kind] and not res[(p, "plain")][kind] for p in pairs),
            "by_technique": {t: {"plain": rate("plain", kind, lambda x, t=t: x["technique"] == t),
                                 "hidden": rate("hidden", kind, lambda x, t=t: x["technique"] == t)}
                             for t in ("dot", "chosung", "roman", "paraphrase")},
            "by_type": {t: {"plain": rate("plain", kind, lambda x, t=t: x["type"] == t),
                            "hidden": rate("hidden", kind, lambda x, t=t: x["type"] == t)}
                        for t in ("AGE", "LOC_ADMIN", "LOC_FACILITY", "JOB", "FAM")},
        }
    summary["subject_of_hits"] = dict(collections.Counter(f"{v}:{res[(p, v)]['subject']}" for p in pairs for v in ("plain", "hidden")
                                                          if res[(p, v)]["loose"]))
    summary["per_pair"] = {p: {v: {k: res[(p, v)][k] for k in ("strict", "loose", "subject", "found")} for v in ("plain", "hidden")}
                           for p in pairs}
    summary["meta"] = {"checkpoint_sha256": hashlib.sha256((Path(a.checkpoint) / "model.safetensors").read_bytes()).hexdigest(),
                       "threshold": 0.7, "rules": c1_rules.enabled(), "torch": torch.__version__,
                       "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (out / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: summary[k] for k in ("pairs", "strict", "loose", "subject_of_hits")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
