"""exp29 · exp30 채점 (exp29 README §4 · exp30 README §5 — 결과 전 고정).

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp30-review-distill/score.py

입력: results/{구성}_{d1c|d4}.jsonl (구성 = a0 · r1 · S1 · T3 …). T3 는 teacher_{set}.jsonl 을 a0 에 적용해 여기서 만든다.
출력: results/metrics.json · 표준 출력 표.
- D1c: Tm(매체 함정 오탐) · Ta(함정 전체 오탐) · V(역함정 self 손실 · 분모 = A0 가 self 로 잡은 자리) · R(본인 단서 재현 · partial match + subject self)
- D4 : G 버림 · G subject 뒤집힘 (exp28b 와 같은 정의) · 재현
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import common

RES = common.HERE / "results"


def iou(a: dict, b: dict) -> float:
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    return inter / (max(a["end"], b["end"]) - min(a["start"], b["start"]))


def touch(s: dict, r: dict) -> bool:
    return s["start"] < r["end"] and r["start"] < s["end"]


def partial(g: dict, spans: list[dict]) -> dict | None:
    c = [s for s in spans if s["type"] == g["type"] and iou(g, s) >= 0.5]
    return max(c, key=lambda s: iou(g, s)) if c else None


def load(path: Path) -> dict:
    return {d["post_id"]: d for d in (json.loads(l) for l in open(path, encoding="utf-8")) if "post_id" in d}


def make_t3(name: str) -> None:
    t = RES / f"teacher_{name}.jsonl"
    if not t.exists():
        return
    a0, dec = load(RES / f"a0_{name}.jsonl"), load(t)
    with open(RES / f"T3_{name}.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for pid, r in a0.items():
            d = dec.get(pid, {}).get("decisions") if r["spans"] else []
            f.write(json.dumps({"post_id": pid, "spans": common.apply(r["spans"], d), "parsed": d is not None}, ensure_ascii=False) + "\n")


def d1c_posts() -> list[dict]:
    rows = [json.loads(l) for l in open(common.EXP29 / "data" / "posts.jsonl", encoding="utf-8")]
    return [r for r in rows if not r.get("excluded")]


def score_d1c(posts: list[dict], pred: dict, a0: dict) -> dict:
    tm = ta = v_base = v_lost = r_hit = r_all = 0
    for p in posts:
        sp = pred[p["post_id"]]["spans"]
        selfs = [s for s in sp if s["subject"] == "self"]
        for t in p["traps"]:
            bad = any(touch(s, t) and s["type"] in t["wrong"] for s in selfs)
            ta += bad
            tm += bad and t["kind"] == "media"
        for v in p.get("reverse", []):
            if any(touch(s, v) and s["subject"] == "self" for s in a0[p["post_id"]]["spans"]):
                v_base += 1
                v_lost += not any(touch(s, v) for s in selfs)
        for g in p["planted"]:
            r_all += 1
            m = partial(g, sp)
            r_hit += m is not None and m["subject"] == "self"
    n_media = sum(t["kind"] == "media" for p in posts for t in p["traps"])
    n_traps = sum(len(p["traps"]) for p in posts)
    return {"Tm": f"{tm}/{n_media}", "Tm_n": tm, "Ta": f"{ta}/{n_traps}", "Ta_n": ta, "V": f"{v_lost}/{v_base}", "V_n": v_lost,
            "R": f"{r_hit}/{r_all}", "R_n": r_hit}


def score_g(gold: dict, a0: dict, pred: dict) -> dict:
    base = dropped = both = flipped = hit = n = 0
    for pid, gs in gold.items():
        for g in gs:
            n += 1
            hit += partial(g, pred[pid]["spans"]) is not None
            s0 = partial(g, a0[pid]["spans"])
            if s0 is None:
                continue
            base += 1
            s1 = partial(g, pred[pid]["spans"])
            if s1 is None:
                dropped += 1
            elif s0["subject"] == g["subject"]:
                both += 1
                flipped += s1["subject"] != g["subject"]
    return {"G_drop": f"{dropped}/{base}", "G_drop_rate": round(dropped / base, 4) if base else None,
            "G_flip": f"{flipped}/{both}", "G_flip_rate": round(flipped / both, 4) if both else None, "D4_recall": f"{hit}/{n} ({hit / n:.3f})"}


def main() -> int:
    for name in ("d1c", "d4"):
        make_t3(name)
    posts, gold = d1c_posts(), common.gold_d4()
    a0_1, a0_4 = load(RES / "a0_d1c.jsonl"), load(RES / "a0_d4.jsonl")
    out = {"d1c_posts": len(posts), "configs": {}}
    tags = sorted({p.name.split("_")[0] for p in RES.glob("*_d1c.jsonl")} | {p.name.split("_")[0] for p in RES.glob("*_d4.jsonl")})
    for tag in tags:
        if tag == "teacher":
            continue
        m = {}
        f1, f4 = RES / f"{tag}_d1c.jsonl", RES / f"{tag}_d4.jsonl"
        if f1.exists():
            pred = load(f1)
            m.update(score_d1c(posts, pred, a0_1))
            secs = [r.get("sec") for r in pred.values() if r.get("sec") is not None]
            if secs:
                m["L_median"] = round(statistics.median(secs), 3)
        if f4.exists() and tag != "a0":
            m.update(score_g(gold, a0_4, load(f4)))
        out["configs"][tag] = m
    a = out["configs"].get("a0", {})
    for tag, m in out["configs"].items():
        if tag in ("a0",) or "Ta_n" not in m or not a:
            continue
        if tag == "r1":   # exp29 §4
            m["checks"] = {"Tm": m["Tm_n"] <= a["Tm_n"] / 2, "V": m["V_n"] <= 2, "R": m["R_n"] >= a["R_n"]}
        elif "G_drop_rate" in m:   # exp30 §5
            m["checks"] = {"Ta": m["Ta_n"] <= a["Ta_n"] / 2, "V": m["V_n"] <= 3, "R": m["R_n"] >= a["R_n"] - 2,
                           "G_drop": m["G_drop_rate"] <= 0.03, "G_flip": m["G_flip_rate"] <= 0.05,
                           "L": m["L_median"] <= 1.0 if "L_median" in m else None}   # 지연을 안 잰 구성(T3 · API)은 판정하지 않는다
        if "checks" in m:
            m["candidate"] = None if None in m["checks"].values() else all(m["checks"].values())
    (RES / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
