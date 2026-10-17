"""exp31 — 판정 · 회귀 셋을 학습 · 판정 전에 고정한다 (README §2).

    PYTHONIOENCODING=utf-8 python experiments/exp31-distill-v2/plan.py d5
    PYTHONIOENCODING=utf-8 python experiments/exp31-distill-v2/plan.py d1d --old28 <exp28 · exp28b data 가 든 experiments 폴더>

d5  = 검수하지 않은 교사 라벨 골드 중 test · D2 · D3 · D4 를 뺀 body 스팬 1개 이상 글 **전부**(175편 · 뽑지 않는다). 학생 학습에서 뺀다.
d1d = 규칙 · 학생 결과를 보지 않은 워커가 설계한 표현(data/design.json)으로 exp29 D1c 와 같은 묶음을 만든다.
      이전 판정셋 · exp30 학습 보강 글에 부분 문자열로 있는 표현이 있으면 멈춘다. 셋마다 파일이 실제로 있는지 확인한다
      (exp29 plan.py 는 이 브랜치에 없는 exp28 · exp28b 를 조용히 건너뛰었다 — README §7).
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP30 = ROOT / "experiments" / "exp30-review-distill"
SEED = 20261021
USED = ["exp17-planted-eval", "exp17b-heldout-eval", "exp17c-final-eval", "exp17d-job-eval", "exp17e-job-dev",
        "exp27-adversarial", "exp28-context-review", "exp28b-context-review-v2", "exp29-media-place-rule", "exp30-review-distill"]


def d5() -> int:
    test = set(json.load(open(ROOT / "data/corpus/v0/splits/test_post_ids.json", encoding="utf-8"))["post_ids"])
    assert len(test) == 255
    out = test.copy()
    for name in ("d3", "d4"):
        ids = set(json.load(open(EXP30 / "data" / f"{name}_post_ids.json", encoding="utf-8"))["post_ids"])
        assert len(ids) == 300
        out |= ids
    pick = set()
    for f in sorted(glob.glob(str(ROOT / "data/corpus/v0/gold/*_spans.jsonl"))):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            pid = d.get("post_id")
            if pid and "spans" in d and not d.get("reviewed") and pid not in out and any(s["text_id"] == "body" for s in d["spans"]):
                pick.add(pid)
    (HERE / "data").mkdir(exist_ok=True)
    (HERE / "data" / "d5_post_ids.json").write_text(
        json.dumps({"rule": "unreviewed gold · body span ≥ 1 · minus test · D2 · D3 · D4 · all", "post_ids": sorted(pick)},
                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"D5 {len(pick)}편")
    return 0


def d1d(old28: Path) -> int:
    d = json.load(open(HERE / "data" / "design.json", encoding="utf-8"))
    assert (len(d["A"]), len(d["T"]), len(d["V"]), len(d["C_topics"])) == (40, 64, 32, 12)
    exprs = [x["text"] for k in ("A", "T", "V") for x in d[k]]
    assert len(set(exprs)) == len(exprs)
    old = ""
    for name in USED:
        base = old28 if name.startswith("exp28") else ROOT / "experiments"
        files = glob.glob(str(base / name / "data" / "*.jsonl")) + glob.glob(str(base / name / "data" / "*.json"))
        assert files, f"{name} 데이터 파일이 없다"
        old += "".join(Path(f).read_text(encoding="utf-8") for f in files)
    clash = [e for e in exprs if e in old]
    if clash:
        print("이전 셋 · 학습 보강과 겹침:", clash)
        return 1
    rng = random.Random(SEED)
    topics, voices = d["topics"], d["voices"]
    rows = []

    def add(group: str, i: int, topic: str, planted=(), traps=(), reverse=()) -> None:
        rows.append({"post_id": f"P31_{group}{i:02d}", "group": group, "topic": topic, "voice": rng.choice(voices),
                     "planted": [{"text": x["text"], "type": x["type"], "how": x["how"]} for x in planted],
                     "traps": [{"text": x["text"], "kind": x["kind"], "wrong": x["wrong"], "how": x["how"]} for x in traps],
                     "reverse": [{"text": x["text"], "kind": x["kind"], "type": x["type"], "how": x["how"]} for x in reverse]})

    for i, x in enumerate(d["A"], 1):
        add("A", i, rng.choice(topics), planted=[x])
    t = d["T"][:]
    rng.shuffle(t)
    for i in range(32):
        add("T", i + 1, rng.choice(topics), traps=t[2 * i: 2 * i + 2])
    v = d["V"][:]
    rng.shuffle(v)
    for i in range(16):
        add("V", i + 1, rng.choice(topics), reverse=v[2 * i: 2 * i + 2])
    for i, tp in enumerate(d["C_topics"], 1):
        add("C", i, tp)
    with open(HERE / "data" / "plan.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"글 {len(rows)} · 표현 {len(exprs)} · 겹침 0 (대조 셋 {len(USED)}개 · {len(old):,}자)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["d5", "d1d"])
    ap.add_argument("--old28", type=Path, default=Path("C:/Users/dor12/wt/old28/experiments"))
    a = ap.parse_args()
    return d5() if a.what == "d5" else d1d(a.old28)


if __name__ == "__main__":
    sys.exit(main())
