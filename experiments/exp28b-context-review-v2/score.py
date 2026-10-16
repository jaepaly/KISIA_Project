"""exp28b 채점 — exp28 score.py 와 같고, G 는 D3(교사 라벨 골드 300편)에서 잰다. D2 는 참고 (README §4).

    PYTHONIOENCODING=utf-8 python experiments/exp28b-context-review-v2/score.py

`excluded` 가 달린 글은 뺀다. 출력: results/metrics.json · 표준 출력에 표
"""
from __future__ import annotations

import glob
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RES = HERE / "results"


def iou(a: dict, b: dict) -> float:
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter / union if union else 0.0


def touch(a: dict, b: dict) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


def partial(g: dict, spans: list[dict]) -> dict | None:
    return next((s for s in spans if s["type"] == g["type"] and iou(g, s) >= 0.5), None)


def load(path: Path) -> tuple[dict, dict]:
    meta, rows = {}, {}
    for line in path.open(encoding="utf-8"):
        d = json.loads(line)
        if "meta" in d:
            meta = d["meta"]
        else:
            rows[d["post_id"]] = d
    return meta, rows


def score_d1(posts: list[dict], pred: dict) -> dict:
    t_hit = t_all = r_hit = r_all = x_hit = x_self = x_all = 0
    extra = []
    for p in posts:
        spans = pred[p["post_id"]]["spans"]
        selfs = [s for s in spans if s["subject"] == "self"]
        for t in p["traps"]:
            t_all += 1
            t_hit += any(s["type"] in t["wrong"] and touch(s, t) for s in selfs)
        for g in p["planted"]:
            if p["group"] == "A":
                r_all += 1
                r_hit += partial(g, selfs) is not None
            else:
                x_all += 1
                x_hit += any(touch(s, g) for s in spans)
                x_self += any(touch(s, g) for s in selfs)
        extra.append(sum(1 for s in selfs if not any(touch(s, x) for x in p["planted"] + p["traps"])))
    by = lambda grp: round(statistics.mean(e for e, p in zip(extra, posts) if p["group"] == grp), 3)
    secs = [pred[p["post_id"]].get("sec", 0) for p in posts]
    q = sorted(secs)
    return {"T": f"{t_hit}/{t_all}", "T_n": t_hit, "R": f"{r_hit}/{r_all}", "R_n": r_hit, "X": f"{x_hit}/{x_all}", "X_n": x_hit,
            "X_self": f"{x_self}/{x_all}", "P": round(statistics.mean(extra), 3), "P_by_group": {g: by(g) for g in "ABC"},
            "L_median": round(statistics.median(secs), 2), "L_p90": round(q[int(0.9 * (len(q) - 1))], 2),
            "parse_fail": sum(1 for p in posts if pred[p["post_id"]].get("parsed") is False)}


def d2_gold() -> dict:
    test = set(json.load(open(ROOT / "data/corpus/v0/splits/test_post_ids.json", encoding="utf-8"))["post_ids"])
    assert len(test) == 255
    gold = {}
    for f in sorted(glob.glob(str(ROOT / "data/corpus/v0/gold/*_spans.jsonl"))):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            if d.get("reviewed") and "spans" in d and d["post_id"] not in test and d["texts"].get("body"):
                gold[d["post_id"]] = [s for s in d["spans"] if s["text_id"] == "body"]
    return gold


def d3_gold() -> dict:
    want = set(json.load(open(HERE / "data" / "d3_post_ids.json", encoding="utf-8"))["post_ids"])
    gold = {}
    for f in sorted(glob.glob(str(ROOT / "data/corpus/v0/gold/*_spans.jsonl"))):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            if d.get("post_id") in want:
                gold[d["post_id"]] = [s for s in d["spans"] if s["text_id"] == "body"]
    assert len(gold) == 300
    return gold


def score_g(gold: dict, a0: dict, pred: dict) -> dict:
    base = dropped = both = flipped = 0
    for pid, gs in gold.items():
        for g in gs:
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
            "G_flip": f"{flipped}/{both}", "G_flip_rate": round(flipped / both, 4) if both else None}


def recall_d2(gold: dict, pred: dict) -> str:
    n = sum(len(v) for v in gold.values())
    hit = sum(partial(g, pred[pid]["spans"]) is not None for pid, gs in gold.items() for g in gs)
    return f"{hit}/{n} ({hit / n:.3f})"


def main() -> int:
    posts = [json.loads(l) for l in open(HERE / "data" / "posts.jsonl", encoding="utf-8")]
    posts = [p for p in posts if not p.get("excluded")]
    gold2, gold3 = d2_gold(), d3_gold()
    _, a0_d1 = load(RES / "a0_d1.jsonl")
    _, a0_d2 = load(RES / "a0_d2.jsonl")
    _, a0_d3 = load(RES / "a0_d3.jsonl")
    out = {"posts": len(posts), "by_group": {g: sum(p["group"] == g for p in posts) for g in "ABC"},
           "configs": {"A0": {**score_d1(posts, a0_d1), "D3_recall": recall_d2(gold3, a0_d3), "D2_recall": recall_d2(gold2, a0_d2)}}}
    for f in sorted(RES.glob("A_*_d1.jsonl")) + sorted(RES.glob("AX_d1.jsonl")):
        name = f.stem[:-3]
        meta, pred = load(f)
        m = {**score_d1(posts, pred), "prompt_hash": meta.get("prompt_hash")}
        for tag, gold, a0 in (("D3", gold3, a0_d3), ("D2", gold2, a0_d2)):
            p = RES / f"{name}_{tag.lower()}.jsonl"
            if p.exists():
                _, pr = load(p)
                if len(pr) == len(gold):
                    m[tag] = score_g(gold, a0, pr)
                    m[f"{tag}_recall"] = recall_d2(gold, pr)
        out["configs"][name] = m

    a0 = out["configs"]["A0"]
    for name, m in out["configs"].items():
        if name == "A0":
            continue
        g = m.get("D3") or {}
        m["checks"] = {"T": m["T_n"] * 2 <= a0["T_n"], "R": m["R_n"] >= a0["R_n"] - 2, "X": m["X_n"] * 2 >= int(m["X"].split("/")[1]),
                       "P": m["P"] <= a0["P"] * 1.5, "L": m["L_median"] <= 15,
                       "G": g.get("G_drop_rate") is not None and g["G_drop_rate"] <= 0.03 and g["G_flip_rate"] <= 0.03}
        m["candidate"] = all(m["checks"].values())
    (RES / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"글 {out['posts']} {out['by_group']}")
    print(f"{'구성':8} {'T':>7} {'R':>7} {'X':>7} {'P':>6} {'L중앙':>6} {'D3버림':>9} {'D3뒤집':>9} {'D3재현':>18} {'D2버림':>9}  후보")
    for name, m in out["configs"].items():
        d3, d2 = m.get("D3") or {}, m.get("D2") or {}
        print(f"{name:8} {m['T']:>7} {m['R']:>7} {m['X']:>7} {m['P']:>6} {m['L_median']:>6} {d3.get('G_drop', '-'):>9} {d3.get('G_flip', '-'):>9} "
              f"{m.get('D3_recall', '-'):>18} {d2.get('G_drop', '-'):>9}  {m.get('candidate', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
