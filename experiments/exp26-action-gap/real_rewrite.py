"""exp26 §5 — 실제 바꿔 쓰기 후보를 적용한 효과 (모사 vs 실제 · 같은 계정 · 같은 대상). 정의는 README (결과 전 커밋 0b70fc0).

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp26-action-gap/real_rewrite.py --checkpoint <1단 v2 폴더>

위험은 세 경우 모두 1단 v2 앱 경로 탐지(c1_rules.detect · 임계값 0.7 · 규칙 켬) 스팬으로 앱 위험 경로(gap.py)를 거쳐 계산한다.
출력: results/real_rewrite.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import statistics
import sys
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT / "src", ROOT / "experiments" / "exp06-finetune", ROOT / "apps" / "analyzer" / "engines"):
    sys.path.insert(0, str(p))

_spec = importlib.util.spec_from_file_location("exp26_gap", HERE / "gap.py")
gap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gap)

from kopl.c2_specificity.engine import risk_by_axis  # noqa: E402
from kopl.c4_stage2 import infer as s2  # noqa: E402
from kopl.c4_stage2.rewrite import suggest  # noqa: E402


def to_record(pid: str, texts: dict) -> dict:
    rec = {"post_id": pid}
    for k in ("title", "body"):
        if texts.get(k):
            rec[k] = texts[k]
    caps = sorted((int(k.split(":")[1]), v) for k, v in texts.items() if k.startswith("photo_caption:"))
    if caps:
        rec["photo_captions"] = [v for _, v in caps]
    return rec


def nfc_texts(texts: dict) -> dict:
    return {k: unicodedata.normalize("NFC", v) for k, v in texts.items() if isinstance(v, str) and v}


def is_target(s: dict) -> bool:
    return s.get("subject") == "self" and s.get("level") == "explicit"


def apply_rewrites(texts: dict, spans: list[dict]) -> tuple[dict, list[dict], int]:
    """채널마다 첫 후보로 바꾼다 → (새 채널, 바꾼 자리[{text_id, type, start, end}] 최종 좌표, 후보 없는 대상 수)."""
    new, placed, no_cand = dict(texts), [], 0
    by_ch: dict[str, list[dict]] = {}
    for s in spans:
        if is_target(s):
            by_ch.setdefault(s["text_id"], []).append(s)
    for tid, items in by_ch.items():
        text = texts[tid]
        chosen, last_end = [], -1
        for s in sorted(items, key=lambda x: (x["start"], -(x["end"] - x["start"]))):  # 겹치면 앞선 것 · 같으면 긴 것
            if s["start"] < last_end:
                continue
            c = suggest(s, text)  # 바꾸기 전 원문 · 원래 offset 으로 먼저 다 만든다
            if not c:
                no_cand += 1
                continue
            chosen.append((s, c[0]["suggestion"]))
            last_end = s["end"]
        out = text
        for s, rep in sorted(chosen, key=lambda x: -x[0]["start"]):  # 뒤에서부터
            out = out[: s["start"]] + rep + out[s["end"]:]
        shift = 0
        for s, rep in sorted(chosen, key=lambda x: x[0]["start"]):  # 최종 좌표
            start = s["start"] + shift
            placed.append({"text_id": tid, "type": s["type"], "start": start, "end": start + len(rep)})
            shift += len(rep) - (s["end"] - s["start"])
        new[tid] = out
    return new, placed, no_cand


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

    def detect(pid: str, texts: dict) -> list[dict]:
        return c1_rules.detect(det, to_record(pid, texts), resolve)["spans"]

    def vec(spans: list[dict], pid: str) -> dict:
        return risk_by_axis(s2._app_conditions(spans, pid))

    t0 = time.time()
    rows, totals = [], {"targets": 0, "no_candidate": 0, "applied": 0, "redetected": 0, "posts_rewritten": 0}
    for n, acc in enumerate(gap.load_accounts(), 1):
        states = {"orig": [], "sim": [], "real": []}
        for p in acc["posts"]:
            pid, texts = p["post_id"], nfc_texts(p["texts"])
            spans = detect(pid, texts)
            geo_cond = s2._app_geo_condition(p["geo_tag"], pid) if p.get("geo_tag") else None
            geo = risk_by_axis([geo_cond]) if geo_cond else None
            orig = vec(spans, pid)
            targets = [s for s in spans if is_target(s)]
            sim = vec([s for s in spans if not is_target(s)], pid) if targets else orig
            real = orig
            if targets:
                new_texts, placed, no_cand = apply_rewrites(texts, spans)
                totals["targets"] += len(targets)
                totals["no_candidate"] += no_cand
                totals["applied"] += len(placed)
                if placed:
                    totals["posts_rewritten"] += 1
                    new_spans = detect(pid, new_texts)
                    real = vec(new_spans, pid)
                    for pl in placed:
                        if any(s["text_id"] == pl["text_id"] and s["type"] == pl["type"]
                               and s["start"] < pl["end"] and pl["start"] < s["end"] for s in new_spans):
                            totals["redetected"] += 1
            for key, v in (("orig", orig), ("sim", sim), ("real", real)):
                states[key].append({"post_id": pid, "orig": v, "rew": v, "explicit": False, "geo": geo})
        r = {k: gap.account_risk(v) for k, v in states.items()}
        rows.append({"persona_id": acc["persona_id"], "n_posts": len(acc["posts"]), **{k: round(v, 4) for k, v in r.items()}})
        print(f"{n} {acc['persona_id']} {r['orig']:.2f} → 모사 {r['sim']:.2f} · 실제 {r['real']:.2f} ({time.time() - t0:.0f}s)", flush=True)

    def drops(key: str, base_min: float = 0.0) -> list[float]:
        return [(x["orig"] - x[key]) / x["orig"] for x in rows if x["orig"] > base_min]

    def summ(v):
        return {"n": len(v), "mean": round(statistics.fmean(v), 4), "median": round(statistics.median(v), 4)} if v else {"n": 0}

    paired = [(x["orig"] - x["real"]) / x["orig"] - (x["orig"] - x["sim"]) / x["orig"] for x in rows if x["orig"] > 0]
    out = {
        "fingerprint": {**gap.fingerprint(), "checkpoint": a.checkpoint,
                        "checkpoint_sha256": hashlib.sha256((Path(a.checkpoint) / "model.safetensors").read_bytes()).hexdigest()},
        "totals": totals,
        "no_candidate_rate": round(totals["no_candidate"] / totals["targets"], 4) if totals["targets"] else None,
        "redetect_rate": round(totals["redetected"] / totals["applied"], 4) if totals["applied"] else None,
        "drop_all": {"sim": summ(drops("sim")), "real": summ(drops("real")), "real_minus_sim": summ(paired)},
        "drop_over_target": {"sim": summ(drops("sim", gap.TARGET)), "real": summ(drops("real", gap.TARGET))},
        "accounts": rows,
    }
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "real_rewrite.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                                                        encoding="utf-8", newline="\n")
    print(json.dumps({k: out[k] for k in ("totals", "no_candidate_rate", "redetect_rate", "drop_all", "drop_over_target")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
