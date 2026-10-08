"""exp18 시험: 교사 라벨을 「설계본」(심은 단서를 힌트로)으로 다시 붙이면 놓친 단서를 되찾나.

대상: 사람이 검수한 clue 글 69편 — 사람 정답이 있어 효과를 바로 잴 수 있다.
비교: 교사 원본(gold/detect, 탐지본) vs 설계본(이 스크립트) — 둘 다 사람 검수본과 type 일치 + IoU ≥ 0.5.

    PYTHONPATH="src;experiments/exp18-teacher-design" python experiments/exp18-teacher-design/pilot.py --env <KISIA .env>

교사 모델은 탐지본과 같은 claude-opus-4-8 (KISIA 게이트웨이). 결과: results/pilot_design.jsonl · results/pilot_metrics.json
재실행하면 이미 붙인 글은 건너뛴다.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import kisia_env  # noqa: E402

from kopl.c5_corpus import label  # noqa: E402
from kopl.c5_corpus.llm import LLMClient  # noqa: E402

OUT = HERE / "results"


def load_gold(pattern: str) -> dict[str, dict]:
    out = {}
    for path in glob.glob(str(ROOT / pattern)):
        for line in open(path, encoding="utf-8-sig"):
            r = json.loads(line)
            if "post_id" in r:
                out[r["post_id"]] = r
    return out


def posts_by_id() -> dict[str, dict]:
    out = {}
    for path in glob.glob(str(ROOT / "data/corpus/v0/posts/*.jsonl")):
        for line in open(path, encoding="utf-8-sig"):
            if line.strip():
                r = json.loads(line)
                out[r["post_id"]] = r
    return out


def overlap(a: dict, b: dict) -> bool:
    if a["text_id"] != b["text_id"] or a["type"] != b["type"]:
        return False
    inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter > 0 and inter / union >= 0.5


def score(pred: dict[str, list], human: dict[str, list]) -> dict:
    tp = fn = fp = 0
    miss = Counter()
    for pid, gold in human.items():
        p = pred.get(pid, [])
        for g in gold:
            if any(overlap(g, x) for x in p):
                tp += 1
            else:
                fn += 1
                miss[g["type"]] += 1
        fp += sum(1 for x in p if not any(overlap(g, x) for g in gold))
    return {"human_spans": tp + fn, "tp": tp, "fn": fn, "fp": fp,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None, "missed_by_type": dict(miss)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--model", default="claude-opus-4-8")
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--no-hint", action="store_true", help="탐지본(힌트 없음) — 교사 모델만 바꿔 비교할 때")
    ap.add_argument("--tag", default="design", help="결과 파일 이름 (pilot_<tag>.jsonl)")
    a = ap.parse_args()
    print(kisia_env.load(a.env))

    top = load_gold("data/corpus/v0/gold/[A-E]*_spans.jsonl")
    detect = load_gold("data/corpus/v0/gold/detect/*_spans.jsonl")
    posts = posts_by_id()
    targets = sorted(pid for pid, r in top.items() if r.get("reviewed") is True and posts.get(pid, {}).get("kind") == "clue")
    print("대상", len(targets))

    OUT.mkdir(exist_ok=True)
    out_path = OUT / f"pilot_{a.tag}.jsonl"
    done = {json.loads(l)["post_id"]: json.loads(l) for l in out_path.open(encoding="utf-8")} if out_path.exists() else {}
    client = LLMClient("anthropic", model=a.model, temperature=0, max_tokens=2048, max_retries=3)
    with out_path.open("a", encoding="utf-8") as f:
        for pid in targets:
            if pid in done:
                continue
            texts = label.texts_of(posts[pid])
            hint = None if a.no_hint else (posts[pid].get("clue") or [])
            found, dropped = label.call_with_retry(lambda: label.label_one(client, texts, hint), pid)
            rec = {"post_id": pid, "spans": found, "dropped": dropped, "teacher": client.version, "hint_n": len(hint or [])}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            done[pid] = rec
            time.sleep(a.sleep)

    human = {pid: top[pid].get("spans") or [] for pid in targets}
    result = {
        "n_posts": len(targets),
        "teacher_detect": score({pid: detect.get(pid, {}).get("spans") or [] for pid in targets}, human),
        f"teacher_{a.tag}": score({pid: done[pid]["spans"] for pid in targets if pid in done}, human),
        "calls": client.calls, "usage": client.usage,
    }
    (OUT / f"pilot_{a.tag}_metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k.startswith("teacher")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
