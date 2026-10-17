"""exp39 채점 — build: H39 COMMUTE 풀(라벨 없음) · score: A(main attributes) 대 R(이 브랜치).

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp39-commute-unknown/score.py build
    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp39-commute-unknown/score.py score <main attributes.py 경로>
"""
import glob
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP = ROOT / "experiments"
HELD = HERE / "data" / "heldout"
TEST = set(json.load(open(ROOT / "data/corpus/v0/splits/test_post_ids.json", encoding="utf-8"))["post_ids"])
assert len(TEST) == 255
DEV_SOURCES = ["exp30-review-distill/results/a0_pool.jsonl", "exp30-review-distill/results/a0_d4.jsonl",
               "exp31-distill-v2/results/a0_d5.jsonl", "exp32-loc-gate/results/a0_d2.jsonl"]


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def h39_bodies():
    out = {}
    for d in {r["src"] for r in jl(HELD / "a0_h39.jsonl")}:
        for r in jl(EXP / d / "data/posts.jsonl"):
            if r.get("post_id"):
                out[(d, r["post_id"])] = r["texts"]["body"]
    return out


def build():
    bodies = h39_bodies()
    rows = []
    for d in jl(HELD / "a0_h39.jsonl"):
        body = bodies[(d["src"], d["post_id"])]
        for s in d["spans"]:
            if s["type"] != "COMMUTE" or s.get("text_id", "body") != "body":
                continue
            assert body[s["start"]:s["end"]] == s["text"]
            rows.append({"id": f"C{len(rows) + 1:03d}", "src": d["src"], "post_id": d["post_id"], "type": s["type"], "text": s["text"],
                         "start": s["start"], "end": s["end"],
                         "ctx": body[max(0, s["start"] - 40):s["start"]] + "⟦" + s["text"] + "⟧" + body[s["end"]:s["end"] + 30]})
    with open(HELD / "pool.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("pool", len(rows))


def mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def iou(a, b):
    return max(0, min(a["end"], b["end"]) - max(a["start"], b["start"])) / (max(a["end"], b["end"]) - min(a["start"], b["start"]))


def score(main_path):
    A = mod(main_path, "attr_main")
    R = mod(ROOT / "src/kopl/c1_span/attributes.py", "attr_r")
    bodies = h39_bodies()
    pool = jl(HELD / "pool.jsonl")
    lab = {r["id"]: r for r in jl(HELD / "labels.jsonl")}
    assert set(lab) == {r["id"] for r in pool}
    review = {r["id"]: r for r in jl(HELD / "d_review.jsonl")} if (HELD / "d_review.jsonl").exists() else {}
    frag = hit = 0
    wrong = []
    for r in pool:
        body = bodies[(r["src"], r["post_id"])]
        a = A.subject_of("COMMUTE", r["text"], body, r["start"], r["end"])
        b = R.subject_of("COMMUTE", r["text"], body, r["start"], r["end"])
        if lab[r["id"]]["label"] == "fragment":
            frag += 1
            hit += b != "self"
        elif a == "self" and b == "unknown" and not review.get(r["id"], {}).get("overturn"):
            wrong.append(r["id"])
    # 골드 · 코퍼스
    gold, gbody = {}, {}
    for f in glob.glob(str(ROOT / "data/corpus/v0/gold/*_spans.jsonl")):
        for d in jl(f):
            if d.get("post_id") and d["post_id"] not in TEST and "texts" in d:
                gold[d["post_id"]] = [s for s in d.get("spans", []) if s.get("text_id", "body") == "body"]
                gbody[d["post_id"]] = d["texts"].get("body", "")
    gold_changed = [(pid, s["type"], s["text"], A.subject_of(s["type"], s["text"], gbody[pid], s["start"], s["end"]),
                     R.subject_of(s["type"], s["text"], gbody[pid], s["start"], s["end"]))
                    for pid, ss in gold.items() for s in ss]
    gold_changed = [g for g in gold_changed if g[3] != g[4]]
    gold_commute = [g for g in gold_changed if g[1] == "COMMUTE" and g[3] == "self" and g[4] == "unknown"]
    dev_changed, dev_lost = 0, []
    for f in DEV_SOURCES:
        for d in jl(EXP / f):
            pid = d.get("post_id")
            if not pid or pid in TEST or pid not in gbody:
                continue
            for s in d["spans"]:
                if s.get("text_id", "body") != "body":
                    continue
                if A.subject_of(s["type"], s["text"], gbody[pid], s["start"], s["end"]) != R.subject_of(s["type"], s["text"], gbody[pid], s["start"], s["end"]):
                    dev_changed += 1
                    if any(g["type"] == s["type"] and iou(g, s) >= 0.5 for g in gold[pid]):
                        dev_lost.append((pid, s["type"], s["text"]))
    out = {"H39": {"pool": len(pool), "fragment": frag, "recall": hit / frag if frag else None, "wrong": len(wrong), "wrong_ids": wrong},
           "gold": {"changed": gold_changed, "commute_self_to_unknown": len(gold_commute)},
           "dev_corpus": {"changed": dev_changed, "gold_matched": dev_lost}}
    out["pass"] = {"recall": out["H39"]["recall"] is not None and out["H39"]["recall"] >= 0.75, "wrong": len(wrong) <= 5,
                   "gold": len(gold_commute) <= 1 and all(g[1] == "COMMUTE" for g in gold_changed), "dev": len(dev_lost) <= 1}
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results/metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    build() if sys.argv[1] == "build" else score(sys.argv[2])
