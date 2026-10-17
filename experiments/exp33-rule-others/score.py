"""exp33 채점 (README §3 — 규칙 구현 전 고정).

    PYTHONIOENCODING=utf-8 python experiments/exp33-rule-others/score.py --base <main 의 attributes.py> [--new src/kopl/c1_span/attributes.py]

A = --base(main 규칙) · R = --new(이 브랜치 규칙). 두 파일을 따로 불러 같은 입력에 subject_of 를 부른다.
입력: data/cases.jsonl(excluded 제외) · 골드 data/corpus/v0/gold/*_spans.jsonl(test 255편 제외 · 모든 채널).
출력: results/metrics.json · results/gold_changes.jsonl(골드에서 A 와 R 이 다른 스팬 전부) · 표준 출력.
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def mod(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def cases() -> list[dict]:
    rows = [json.loads(l) for l in open(HERE / "data" / "cases.jsonl", encoding="utf-8")]
    return [r for r in rows if not r.get("excluded")]


def run_case(m, c: dict) -> str:
    s = c["sentence"]
    a = s.index(c["span"])
    return m.subject_of(c["type"], c["span"], s, a, a + len(c["span"]))


def gold_spans():
    test = set(json.load(open(ROOT / "data/corpus/v0/splits/test_post_ids.json", encoding="utf-8"))["post_ids"])
    assert len(test) == 255
    for f in sorted(glob.glob(str(ROOT / "data/corpus/v0/gold/*_spans.jsonl"))):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            pid = d.get("post_id")
            if not pid or "spans" not in d or pid in test:
                continue
            for s in d["spans"]:
                text = (d.get("texts") or {}).get(s["text_id"])
                if text is None:
                    continue
                cps = list(text)   # 오프셋은 코드포인트 단위
                yield pid, bool(d.get("reviewed")), s, "".join(cps), "".join(cps[s["start"]:s["end"]])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--new", type=Path, default=ROOT / "src/kopl/c1_span/attributes.py")
    a = ap.parse_args()
    A, R = mod(a.base, "attr_base"), mod(a.new, "attr_new")
    out: dict = {"cases": {}, "gold": {}}
    per: dict = {}
    for c in cases():
        k = per.setdefault(f'{c["pattern"]}-{c["kind"]}', {"n": 0, "A": 0, "R": 0, "R_not_self": 0, "A_wrong_ids": [], "R_wrong_ids": []})
        pa, pr = run_case(A, c), run_case(R, c)
        k["n"] += 1
        k["A"] += pa == c["subject"]
        k["R"] += pr == c["subject"]
        k["R_not_self"] += pr != "self"
        if pa != c["subject"]:
            k["A_wrong_ids"].append(f'{c["id"]}:{pa}')
        if pr != c["subject"]:
            k["R_wrong_ids"].append(f'{c["id"]}:{pr}')
    out["cases"] = per
    # 골드 회귀 — 사람 검수(reviewed)와 전체(교사 라벨 포함)를 따로
    g = {w: {"n": 0, "A_agree": 0, "R_agree": 0, "changed": 0, "lost": 0, "fixed": 0} for w in ("reviewed", "all")}
    with open(HERE / "results" / "gold_changes.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for pid, rev, s, text, piece in gold_spans():
            sa = A.subject_of(s["type"], piece, text, s["start"], s["end"])
            sr = R.subject_of(s["type"], piece, text, s["start"], s["end"])
            for w in ("reviewed", "all"):
                if w == "reviewed" and not rev:
                    continue
                x = g[w]
                x["n"] += 1
                x["A_agree"] += sa == s["subject"]
                x["R_agree"] += sr == s["subject"]
                if sa != sr:
                    x["changed"] += 1
                    x["lost"] += sa == s["subject"]
                    x["fixed"] += sr == s["subject"]
            if sa != sr:
                f.write(json.dumps({"post_id": pid, "reviewed": rev, "type": s["type"], "text": piece, "gold": s["subject"], "A": sa, "R": sr,
                                    "ctx": text[max(0, s["start"] - 40): s["end"] + 30]}, ensure_ascii=False) + "\n")
    out["gold"] = g
    pos = [v for k, v in per.items() if k.endswith("-pos")]
    neg = [v for k, v in per.items() if k.endswith("-neg")]
    pos_rate = {k: round(v["R"] / v["n"], 3) for k, v in per.items() if k.endswith("-pos")}
    out["checks"] = {
        "pos_each_pattern_ge_0.75": all(r >= 0.75 for r in pos_rate.values()),
        "neg_R_ge_A": sum(v["R"] for v in neg) >= sum(v["A"] for v in neg),
        # 반례에서 A 가 맞힌 것을 R 이 틀리면 안 된다(id 기준)
        "neg_no_new_loss": {i.split(":")[0] for v in neg for i in v["R_wrong_ids"]} <= {i.split(":")[0] for v in neg for i in v["A_wrong_ids"]},
        "gold_reviewed_lost_le_1": g["reviewed"]["lost"] <= 1,
        "gold_all_lost_le_5": g["all"]["lost"] <= 5,
        "gold_all_R_ge_A": g["all"]["R_agree"] >= g["all"]["A_agree"],
    }
    out["pass"] = all(out["checks"].values())
    (HERE / "results" / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
