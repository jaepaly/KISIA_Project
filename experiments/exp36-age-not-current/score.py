"""exp36 채점 (README §2 — 구현 결과 전 고정). exp35 score.py 와 같은 틀(독립 파일)에 코퍼스 1단 전수를 더했다.

    PYTHONIOENCODING=utf-8 python experiments/exp36-age-not-current/score.py --base <main 의 attributes.py> [--new src/kopl/c1_span/attributes.py] [--corpus <exp30~32 결과가 있는 experiments 폴더>]

판정셋: data/heldout/pos.jsonl(Q1 정답 other · Q2 정답 unknown) · neg.jsonl(neg 정답 self · pos-hard). excluded 줄은 뺀다.
코퍼스: 1단(A0) 결과 a0_pool · a0_d4 · a0_d5 · a0_d2 의 스팬에 A · R 을 대 보고 바뀐 것을 results/corpus_changes.jsonl 에 남긴다(D 가 읽는다).
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def mod(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def rows(name: str) -> list[dict]:
    return [r for r in (json.loads(l) for l in open(HERE / "data" / "heldout" / name, encoding="utf-8")) if not r.get("excluded")]


def run(m, c: dict) -> str:
    a = c["sentence"].index(c["span"])
    return m.subject_of(c["type"], c["span"], c["sentence"], a, a + len(c["span"]))


def test_ids() -> set[str]:
    t = set(json.load(open(ROOT / "data/corpus/v0/splits/test_post_ids.json", encoding="utf-8"))["post_ids"])
    assert len(t) == 255
    return t


def gold():
    test = test_ids()
    for f in sorted(glob.glob(str(ROOT / "data/corpus/v0/gold/*_spans.jsonl"))):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            if not d.get("post_id") or "spans" not in d or d["post_id"] in test:
                continue
            for s in d["spans"]:
                text = (d.get("texts") or {}).get(s["text_id"])
                if text is not None:
                    yield d["post_id"], bool(d.get("reviewed")), s, text, "".join(list(text)[s["start"]:s["end"]])


def worst_time(m) -> float:
    worst = 0.0
    for text in (" " * 5000 + "(14살)", "아이찡" + "(" * 3000 + "14살)", "열다섯 살 " * 1500 + "때", ("때 " * 2500) + "열다섯"):
        span = "14살" if "14살" in text else "열다섯"
        a = text.rindex(span)
        t = time.perf_counter()
        m.subject_of("AGE", span, text, a, a + len(span))
        worst = max(worst, time.perf_counter() - t)
    return round(worst, 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--new", type=Path, default=ROOT / "src/kopl/c1_span/attributes.py")
    ap.add_argument("--corpus", type=Path, default=Path("C:/Users/dor12/wt/exp29/experiments"))
    a = ap.parse_args()
    A, R = mod(a.base, "attr_base"), mod(a.new, "attr_new")
    out: dict = {"patterns": {}}
    for pat in ("Q1", "Q2"):
        pos = [c for c in rows("pos.jsonl") if c["pattern"] == pat]
        rev = [c for c in rows("neg.jsonl") if c["pattern"] == pat]
        p = {"pos_n": len(pos), "pos_A": 0, "pos_R": 0, "rev_n": len(rev), "rev_A": 0, "rev_R": 0, "rev_new_wrong": [], "pos_R_wrong": []}
        for c in pos:
            ra, rr = run(A, c), run(R, c)
            p["pos_A"] += ra == c["subject"]
            p["pos_R"] += rr == c["subject"]
            if rr != c["subject"]:
                p["pos_R_wrong"].append(f'{c["id"]}:{rr}')
        for c in rev:
            ra, rr = run(A, c), run(R, c)
            p["rev_A"] += ra == c["subject"]
            p["rev_R"] += rr == c["subject"]
            if ra == c["subject"] and rr != c["subject"]:
                p["rev_new_wrong"].append(f'{c["id"]}:{rr}')
        p["pos_rate"] = round(p["pos_R"] / p["pos_n"], 3) if p["pos_n"] else None
        p["pass"] = p["pos_n"] > 0 and p["pos_rate"] >= 0.75 and len(p["rev_new_wrong"]) <= 1
        out["patterns"][pat] = p
    g = {w: {"n": 0, "A_agree": 0, "R_agree": 0, "lost": 0, "fixed": 0, "lost_items": []} for w in ("reviewed", "all")}
    for pid, rev, s, text, piece in gold():
        sa = A.subject_of(s["type"], piece, text, s["start"], s["end"])
        sr = R.subject_of(s["type"], piece, text, s["start"], s["end"])
        for w in ("reviewed", "all"):
            if w == "reviewed" and not rev:
                continue
            x = g[w]
            x["n"] += 1
            x["A_agree"] += sa == s["subject"]
            x["R_agree"] += sr == s["subject"]
            if sa == s["subject"] and sr != s["subject"]:
                x["lost"] += 1
                x["lost_items"].append(f"{pid}:{s['type']}:{piece}:{sa}→{sr}")
            x["fixed"] += sa != s["subject"] and sr == s["subject"]
    out["gold"] = g
    # 코퍼스 1단 전수 — 바뀐 스팬을 남긴다(판정 5 는 D 가 읽고 README 에 적는다)
    test = test_ids()
    bodies = {}
    for pid, rev, s, text, piece in gold():
        if s["text_id"] == "body":
            bodies[pid] = text
    for f in sorted(glob.glob(str(ROOT / "data/corpus/v0/gold/*_spans.jsonl"))):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            if d.get("post_id") and "texts" in d:
                bodies.setdefault(d["post_id"], d["texts"].get("body", ""))
    n_post = n_span = 0
    changes = []
    seen = set()
    for rel in ("exp30-review-distill/results/a0_pool.jsonl", "exp30-review-distill/results/a0_d4.jsonl",
                "exp31-distill-v2/results/a0_d5.jsonl", "exp32-loc-gate/results/a0_d2.jsonl"):
        for line in open(a.corpus / rel, encoding="utf-8"):
            d = json.loads(line)
            pid = d.get("post_id")
            if not pid or pid in test or pid in seen or pid not in bodies:
                continue
            seen.add(pid)
            n_post += 1
            body = bodies[pid]
            for s in d["spans"]:
                n_span += 1
                sa = A.subject_of(s["type"], s["text"], body, s["start"], s["end"])
                sr = R.subject_of(s["type"], s["text"], body, s["start"], s["end"])
                if sa != sr:
                    changes.append({"post_id": pid, "type": s["type"], "text": s["text"], "A": sa, "R": sr,
                                    "ctx": body[max(0, s["start"] - 50): s["end"] + 40].replace("\n", " ")})
    (HERE / "results").mkdir(exist_ok=True)
    with open(HERE / "results" / "corpus_changes.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for c in changes:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    out["corpus"] = {"posts": n_post, "spans": n_span, "changed": len(changes)}
    out["time_worst_sec"] = {"A": worst_time(A), "R": worst_time(R)}
    P = out["patterns"]
    out["checks"] = {
        "patterns_pass": {k: v["pass"] for k, v in P.items()},
        "rev_new_wrong_total_le_3": sum(len(v["rev_new_wrong"]) for v in P.values()) <= 3,
        "rev_R_ge_A": sum(v["rev_R"] for v in P.values()) >= sum(v["rev_A"] for v in P.values()),
        "gold": g["reviewed"]["lost"] <= 1 and g["all"]["lost"] <= 5,
        "corpus_wrong_le_2": "D 가 corpus_changes.jsonl 을 읽고 README 에 적는다",
        "time_le_0.05": out["time_worst_sec"]["R"] <= 0.05,
    }
    (HERE / "results" / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
