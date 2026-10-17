"""exp37 채점 — build: 판정셋 풀(라벨 없음) 만들기 · score: A(main · 버림 없음) 대 R(이 브랜치 is_fragment_span).

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp37-fragment-spans/score.py build
    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp37-fragment-spans/score.py score
"""
import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP = ROOT / "experiments"
HELD = HERE / "data" / "heldout"
TEST = set(json.load(open(ROOT / "data/corpus/v0/splits/test_post_ids.json", encoding="utf-8"))["post_ids"])
assert len(TEST) == 255

# (1단 결과, 본문 파일) — 이번에 처음 여는 합성 셋 7개
H_SOURCES = [
    ("exp28-context-review/results/a0_d1.jsonl", "exp28-context-review/data/posts.jsonl"),
    ("exp28b-context-review-v2/results/a0_d1.jsonl", "exp28b-context-review-v2/data/posts.jsonl"),
    ("exp30-review-distill/results/a0_d1c.jsonl", "exp29-media-place-rule/data/posts.jsonl"),
    ("exp30-review-distill/results/a0_aug.jsonl", "exp30-review-distill/data/aug_posts.jsonl"),
    ("exp31-distill-v2/results/a0_d1d.jsonl", "exp31-distill-v2/data/posts.jsonl"),
    ("exp31-distill-v2/results/a0_aug2.jsonl", "exp31-distill-v2/data/aug2_posts.jsonl"),
    ("exp32-loc-gate/results/a0_d1e.jsonl", "exp32-loc-gate/data/posts.jsonl"),
]
DEV_SOURCES = ["exp30-review-distill/results/a0_pool.jsonl", "exp30-review-distill/results/a0_d4.jsonl",
               "exp31-distill-v2/results/a0_d5.jsonl", "exp32-loc-gate/results/a0_d2.jsonl"]


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def body_of(r):
    if "body" in r:
        return r["body"]
    return (r.get("texts") or {}).get("body")


def in_pool(s):
    return s["type"] == "COMMUTE" or len(s["text"].strip()) <= 2


def build():
    rows = []
    for res, posts in H_SOURCES:
        bodies = {r["post_id"]: body_of(r) for r in jl(EXP / posts) if r.get("post_id")}
        for d in jl(EXP / res):
            if "spans" not in d:
                continue
            body = bodies.get(d["post_id"])
            assert body is not None, (res, d["post_id"])
            for s in d["spans"]:
                if s.get("text_id", "body") != "body" or not in_pool(s):
                    continue
                assert body[s["start"]:s["end"]] == s["text"], (d["post_id"], s)
                rows.append({"id": f"H{len(rows) + 1:04d}", "src": res.split("/")[0], "post_id": d["post_id"],
                             "type": s["type"], "text": s["text"],
                             "ctx": body[max(0, s["start"] - 40):s["start"]] + "⟦" + s["text"] + "⟧" + body[s["end"]:s["end"] + 30]})
    HELD.mkdir(parents=True, exist_ok=True)
    with open(HELD / "pool.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("pool", len(rows), "COMMUTE", sum(r["type"] == "COMMUTE" for r in rows))


def gold_spans():
    out = {}
    for f in glob.glob(str(ROOT / "data/corpus/v0/gold/*_spans.jsonl")):
        for d in jl(f):
            if d.get("post_id") and d["post_id"] not in TEST:
                out[d["post_id"]] = [s for s in d.get("spans", []) if s.get("text_id", "body") == "body"]
    return out


def iou(a, b):
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    return inter / (max(a["end"], b["end"]) - min(a["start"], b["start"]))


def score():
    from kopl.c1_span import rules as R
    pool = {r["id"]: r for r in jl(HELD / "pool.jsonl")}
    labels = {r["id"]: r for r in jl(HELD / "labels.jsonl")}
    assert set(labels) == set(pool), "라벨이 풀과 어긋남"
    review = {r["id"]: r for r in jl(HELD / "d_review.jsonl")} if (HELD / "d_review.jsonl").exists() else {}
    out = {}
    for pat, sel in (("F1", lambda r: r["type"] != "COMMUTE" and len(r["text"].strip()) <= 2), ("F2", lambda r: r["type"] == "COMMUTE")):
        sw = {"F1": "_DROP_F1", "F2": "_DROP_F2"}
        saved = (R._DROP_F1, R._DROP_F2)
        R._DROP_F1, R._DROP_F2 = pat == "F1", pat == "F2"   # 패턴 하나만 켜고 잰다
        rows = [r for r in pool.values() if sel(r)]
        frag = [r for r in rows if labels[r["id"]]["label"] == "fragment"]
        dropped = [r for r in rows if R.is_fragment_span(r["type"], r["text"])]
        wrong = [r for r in dropped if labels[r["id"]]["label"] == "clue" and not review.get(r["id"], {}).get("overturn")]
        rec = sum(R.is_fragment_span(r["type"], r["text"]) for r in frag) / len(frag) if frag else None
        R._DROP_F1, R._DROP_F2 = saved
        need = 0.5 if pat == "F1" else 0.75
        cap = 1 if pat == "F1" else 2
        out[pat] = {"pool": len(rows), "fragment": len(frag), "dropped": len(dropped), "recall": rec,
                    "wrong": len(wrong), "wrong_ids": [r["id"] for r in wrong],
                    "pass": rec is not None and rec >= need and len(wrong) <= cap, "switch": sw[pat]}
    # 골드 회귀 — 배포 기본 스위치 그대로
    gold = gold_spans()
    gold_drop = [(pid, s["type"], s["text"]) for pid, ss in gold.items() for s in ss if R.is_fragment_span(s["type"], s["text"])]
    dev_lost = []
    for f in DEV_SOURCES:
        for d in jl(EXP / f):
            if "spans" not in d or d["post_id"] in TEST or d["post_id"] not in gold:
                continue
            for s in d["spans"]:
                if s.get("text_id", "body") == "body" and R.is_fragment_span(s["type"], s["text"]) and \
                        any(g["type"] == s["type"] and iou(g, s) >= 0.5 for g in gold[d["post_id"]]):
                    dev_lost.append((d["post_id"], s["type"], s["text"]))
    out["gold"] = {"spans": sum(map(len, gold.values())), "gold_text_dropped": gold_drop, "dev_matched_dropped": dev_lost,
                   "pass": len(gold_drop) <= 1 and len(dev_lost) <= 1}
    out["shipping"] = {"_DROP_F1": R._DROP_F1, "_DROP_F2": R._DROP_F2}
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    {"build": build, "score": score}[sys.argv[1]]()
