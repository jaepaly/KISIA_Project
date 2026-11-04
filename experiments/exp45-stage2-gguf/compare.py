"""exp09 v2 — NF4 저장 결과(qwen_cfg_v2.jsonl · 어댑터 c045d353 · 10/27) ↔ GGUF 재실행(qwen_cfg_v2_gguf.jsonl) 칸 비교.

    PYTHONIOENCODING=utf-8 PYTHONPATH="src;." python experiments/exp44-stage2-gguf/compare.py

- 원시 판정(score.py 와 같은 파싱 · 앱 검증 없이)과 앱 판정(validate_findings · None 이면 앱은 규칙 폴백) 두 층에서 735칸 일치
- 파싱 실패 · 잘림 · 앱 폴백 · 근거 일치(같은 판정 칸에서 근거 span_id 집합이 같은가)
- 불일치 칸은 그 속성 유형의 입력 스팬(가명 토큰 · 등급 · 주체)과 골드 원문(코퍼스 v0 가상 인물)을 함께 적는다
출력: results/compare_exp09.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP09 = ROOT / "experiments/exp09-external-agreement"
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(EXP09), str(ROOT / "experiments/exp08-stage2-sft")]

from kopl.c4_stage2 import infer  # noqa: E402
from kopl.c4_stage2.rules import ATTRS, TYPE_TO_ATTR  # noqa: E402
from run_config import config_input, sha256  # noqa: E402


def load(name: str) -> dict[str, dict]:
    rows = [json.loads(l) for l in (EXP09 / "data" / name).read_text(encoding="utf-8").splitlines() if l.strip()]
    return {r["persona_id"]: r for r in rows}


def gold_text() -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    corpus = ROOT / "data/corpus/v0/gold"
    for path in [*sorted((corpus / "blind").glob("*_spans.jsonl")), *sorted(corpus.glob("*_spans.jsonl"))]:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            row = json.loads(line) if line.strip() else {}
            for s in row.get("spans") or []:
                out.setdefault((row["post_id"], s["span_id"]), s.get("text"))
    return out


def main() -> int:
    inputs = load("inputs.jsonl")
    nf4, gg = load("qwen_cfg_v2.jsonl"), load("qwen_cfg_v2_gguf.jsonl")
    meta = json.loads((EXP09 / "data/qwen_cfg_v2_meta.json").read_text(encoding="utf-8"))
    assert meta["adapter_sha256"].startswith("c045d353") and meta["inputs_sha256"] == sha256(EXP09 / "data/inputs.jsonl")
    texts = gold_text()
    layers = {"raw": Counter(), "app": Counter()}
    stats = {k: Counter() for k in ("nf4", "gguf")}
    ev_same = Counter()
    diffs = []
    for pid in sorted(inputs):
        _, _, entries = config_input("v2", inputs[pid])
        spans = {(e["post_id"], s["span_id"]): s for e in entries for s in e["spans"]}
        side = {}
        for name, rec in (("nf4", nf4.get(pid)), ("gguf", gg.get(pid))):
            raw = (rec or {}).get("raw") or ""
            app = infer.validate_findings(infer.parse_findings(raw), entries)
            st = stats[name]
            st["persons"] += 1
            st["parse_fail"] += (rec or {}).get("findings") is None
            st["truncated"] += bool((rec or {}).get("truncated"))
            st["app_fallback"] += app is None
            st["sec_total"] += (rec or {}).get("sec") or 0
            side[name] = {"raw": (rec or {}).get("findings") or {}, "app": app or {}}
        for attr in ATTRS:
            for layer in ("raw", "app"):
                a = (side["nf4"][layer].get(attr) or {}).get("verdict", "invalid")
                b = (side["gguf"][layer].get(attr) or {}).get("verdict", "invalid")
                layers[layer]["cells"] += 1
                layers[layer]["same"] += a == b
                if layer == "app" and a == b:
                    ea = {(e["post_id"], e["span_id"]) for e in side["nf4"]["app"][attr]["evidence"]} if a != "invalid" else set()
                    eb = {(e["post_id"], e["span_id"]) for e in side["gguf"]["app"][attr]["evidence"]} if b != "invalid" else set()
                    ev_same["cells"] += 1
                    ev_same["same"] += ea == eb
                if layer == "raw" and a != b:
                    related = [{"post_id": k[0], "span_id": k[1], "token": s["text"], "type": s["type"], "level": s["level"],
                                "subject": s["subject"], "gold_text": texts.get(k)}
                               for k, s in spans.items() if TYPE_TO_ATTR.get(s["type"]) == attr]
                    diffs.append({"persona_id": pid, "attr": attr, "nf4": a, "gguf": b,
                                  "rule_target": inputs[pid]["rule_target"][attr]["verdict"],
                                  "nf4_app": (side["nf4"]["app"].get(attr) or {}).get("verdict", "fallback"),
                                  "gguf_app": (side["gguf"]["app"].get(attr) or {}).get("verdict", "fallback"),
                                  "nf4_evidence": [e.get("span_id") for e in (side["nf4"]["raw"].get(attr) or {}).get("evidence") or []],
                                  "gguf_evidence": [e.get("span_id") for e in (side["gguf"]["raw"].get(attr) or {}).get("evidence") or []],
                                  "spans": related})
    out = {
        "nf4_file_sha256": sha256(EXP09 / "data/qwen_cfg_v2.jsonl"),
        "gguf_file_sha256": sha256(EXP09 / "data/qwen_cfg_v2_gguf.jsonl"),
        "verdict_agreement": {k: {"same": v["same"], "cells": v["cells"], "rate": round(v["same"] / v["cells"], 4)}
                              for k, v in layers.items()},
        "evidence_same_given_same_verdict": {**ev_same, "rate": round(ev_same["same"] / ev_same["cells"], 4)},
        "stats": {k: {**v, "sec_total": round(v["sec_total"], 1), "sec_mean": round(v["sec_total"] / v["persons"], 2)}
                  for k, v in stats.items()},
        "diffs": diffs,
    }
    (HERE / "results/compare_exp09.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("verdict_agreement", "evidence_same_given_same_verdict", "stats")},
                     ensure_ascii=False, indent=1))
    for d in diffs:
        print(d["persona_id"], d["attr"], "NF4", d["nf4"], "GGUF", d["gguf"], "규칙", d["rule_target"],
              [(s["gold_text"], s["level"], s["subject"]) for s in d["spans"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
