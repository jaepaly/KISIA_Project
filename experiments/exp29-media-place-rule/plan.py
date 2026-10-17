"""exp29 — D1c 판정셋 계획 (README §2). 표현은 규칙을 보지 않은 워커가 설계했다(data/design.json · 10/16).

    PYTHONIOENCODING=utf-8 python experiments/exp29-media-place-rule/plan.py

글 묶음: A 40(본인 단서 1개씩) · T 32(함정 2개씩) · V 16(역함정 2개씩) · C 12(단서 없음).
이전 판정셋(exp17 계열 · exp27 · exp28 · exp28b) 글에 부분 문자열로 있는 표현이 있으면 멈춘다.
출력: data/plan.jsonl — {post_id, group, topic, voice, planted, traps, reverse}
"""
from __future__ import annotations

import glob
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SEED = 20261020
USED = ["exp17-planted-eval", "exp17b-heldout-eval", "exp17c-final-eval", "exp17d-job-eval", "exp17e-job-dev",
        "exp27-adversarial", "exp28-context-review", "exp28b-context-review-v2"]


def main() -> int:
    d = json.load(open(HERE / "data" / "design.json", encoding="utf-8"))
    assert (len(d["A"]), len(d["T"]), len(d["V"]), len(d["C_topics"])) == (40, 64, 32, 12)
    exprs = [x["text"] for k in ("A", "T", "V") for x in d[k]]
    old = ""
    for name in USED:
        for f in glob.glob(str(ROOT / "experiments" / name / "data" / "*.jsonl")):
            old += Path(f).read_text(encoding="utf-8")
    clash = [e for e in exprs if e in old]
    if clash:
        print("이전 판정셋과 겹침:", clash)
        return 1
    rng = random.Random(SEED)
    topics, voices = d["topics"], d["voices"]
    rows = []

    def add(group: str, i: int, topic: str, planted=(), traps=(), reverse=()) -> None:
        rows.append({"post_id": f"P29_{group}{i:02d}", "group": group, "topic": topic, "voice": rng.choice(voices),
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
    print(f"글 {len(rows)} · 표현 {len(exprs)} · 겹침 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
