"""exp31 채점 (README §4 — 결과 전 고정). 지표 정의는 exp30 score.py 와 같고 셋만 D1d · D5 다.

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp31-distill-v2/score.py

입력: results/{구성}_{d1d|d5}.jsonl. T3 는 teacher_{set}.jsonl 을 a0 에 적용해 여기서 만든다.
출력: results/metrics.json · 표준 출력.
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


def d1d_posts() -> list[dict]:
    rows = [json.loads(l) for l in open(common.HERE / "data" / "posts.jsonl", encoding="utf-8")]
    return [r for r in rows if not r.get("excluded")]


def score_d1d(posts: list[dict], pred: dict, a0: dict) -> dict:
    tm = ta = v_base = v_lost = vt_base = vt_lost = r_hit = r_all = 0
    vk: dict[str, list[int]] = {}
    for p in posts:
        sp = pred[p["post_id"]]["spans"]
        selfs = [s for s in sp if s["subject"] == "self"]
        for t in p["traps"]:
            bad = any(touch(s, t) and s["type"] in t["wrong"] for s in selfs)
            ta += bad
            tm += bad and t["kind"] == "media"
        for v in p.get("reverse", []):
            if any(touch(s, v) and s["subject"] == "self" for s in a0[p["post_id"]]["spans"]):
                lost = not any(touch(s, v) for s in selfs)
                v_base += 1
                v_lost += lost
                k = vk.setdefault(v["kind"], [0, 0])
                k[0] += lost; k[1] += 1
            # 사후 보충 지표(README §9 · Codex): 같은 자리의 다른 유형(「출근길마다」 COMMUTE)이 self 로 남아도 목표 유형을 잃으면 손실
            if any(touch(s, v) and s["subject"] == "self" and s["type"] == v["type"] for s in a0[p["post_id"]]["spans"]):
                vt_base += 1
                vt_lost += not any(touch(s, v) and s["type"] == v["type"] for s in selfs)
        for g in p["planted"]:
            r_all += 1
            m = partial(g, sp)
            r_hit += m is not None and m["subject"] == "self"
    n_media = sum(t["kind"] == "media" for p in posts for t in p["traps"])
    n_traps = sum(len(p["traps"]) for p in posts)
    return {"Tm": f"{tm}/{n_media}", "Tm_n": tm, "Ta": f"{ta}/{n_traps}", "Ta_n": ta, "V": f"{v_lost}/{v_base}", "V_n": v_lost,
            "V_by_kind": {k: f"{a}/{b}" for k, (a, b) in sorted(vk.items())}, "V_typed": f"{vt_lost}/{vt_base}", "R": f"{r_hit}/{r_all}", "R_n": r_hit}


def score_g(gold: dict, a0: dict, pred: dict) -> dict:
    base = dropped = both = flipped = hit = n = 0
    flips: dict[str, int] = {}
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
                if s1["subject"] != g["subject"]:
                    flipped += 1
                    key = f"{g['type']}:{g['subject']}→{s1['subject']}"
                    flips[key] = flips.get(key, 0) + 1
    return {"G_drop": f"{dropped}/{base}", "G_drop_rate": round(dropped / base, 4) if base else None,
            "G_flip": f"{flipped}/{both}", "G_flip_rate": round(flipped / both, 4) if both else None,
            "G_flip_kinds": dict(sorted(flips.items(), key=lambda x: (-x[1], x[0]))), "D5_recall": f"{hit}/{n} ({hit / n:.3f})"}


def checks(m: dict, a: dict) -> dict:
    """exp30 §5 와 같은 여섯 기준. L 을 안 잰 구성(T3 · API)은 None."""
    return {"Ta": m["Ta_n"] <= a["Ta_n"] / 2, "V": m["V_n"] <= 3, "R": m["R_n"] >= a["R_n"] - 2,
            "G_drop": m["G_drop_rate"] <= 0.03, "G_flip": m["G_flip_rate"] <= 0.05,
            "L": m["L_median"] <= 1.0 if "L_median" in m else None}


def main() -> int:
    for name in ("d1d", "d5"):
        make_t3(name)
    posts, gold = d1d_posts(), common.gold_d5()
    a0_1, a0_5 = load(RES / "a0_d1d.jsonl"), load(RES / "a0_d5.jsonl")
    out = {"d1d_posts": len(posts), "configs": {}}
    tags = sorted({p.name.rsplit("_", 1)[0] for p in RES.glob("*_d1d.jsonl")} | {p.name.rsplit("_", 1)[0] for p in RES.glob("*_d5.jsonl")})
    for tag in tags:
        if tag == "teacher":
            continue
        m = {}
        f1, f5 = RES / f"{tag}_d1d.jsonl", RES / f"{tag}_d5.jsonl"
        if f1.exists():
            pred = load(f1)
            m.update(score_d1d(posts, pred, a0_1))
            secs = [r.get("sec") for r in pred.values() if r.get("sec") is not None]
            if secs:
                m["L_median"] = round(statistics.median(secs), 3)
        if f5.exists() and tag != "a0":
            m.update(score_g(gold, a0_5, load(f5)))
        out["configs"][tag] = m
    a = out["configs"]["a0"]
    for tag, m in out["configs"].items():
        if tag != "a0" and "Ta_n" in m and "G_drop_rate" in m:
            m["checks"] = checks(m, a)
            m["pass"] = None if None in m["checks"].values() else all(m["checks"].values())
    # 채택 후보 (README §4): S2 두 seed 가 모두 통과
    s2 = [m.get("pass") for t, m in out["configs"].items() if t.startswith("S2")]
    out["S2_candidate"] = len(s2) == 2 and all(x is True for x in s2)
    (RES / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
