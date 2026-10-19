"""exp30 — 교사(Claude · 프롬프트 v3)가 1단 후보마다 self · other · unknown · drop 을 정한다 (README §1). 이 PC 에서 돈다.

    export PYTHONIOENCODING=utf-8 PYTHONPATH=src   (ANTHROPIC_AUTH_TOKEN · ANTHROPIC_BASE_URL 은 환경변수 · KISIA 키)
    python experiments/exp30-review-distill/teacher.py --set pool          # 학습용 (글 5편씩)
    python experiments/exp30-review-distill/teacher.py --set d1c           # 참고 — 교사 자체(T3 · 판정셋)

입력: results/a0_{set}.jsonl. 출력: results/teacher_{set}.jsonl — 글마다 {post_id, decisions|null, raw}
이어 돌리면 이미 받은 글은 건너뛴다. 후보가 없는 글은 부르지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import common
from kopl.c5_corpus import llm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True)
    ap.add_argument("--model", default="claude-opus-4-8")
    ap.add_argument("--batch", type=int, default=5)
    a = ap.parse_args()
    a0 = [json.loads(l) for l in open(common.HERE / "results" / f"a0_{a.set}.jsonl", encoding="utf-8")]
    body = {r["post_id"]: r["body"] for r in common.load(a.set)}
    out = common.HERE / "results" / f"teacher_{a.set}.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(l)["post_id"] for l in open(out, encoding="utf-8") if "post_id" in l}
    todo = [r for r in a0 if r["spans"] and r["post_id"] not in done]
    client = llm.LLMClient("anthropic", model=a.model, temperature=0.0, max_tokens=2048, max_retries=1)
    with open(out, "a", encoding="utf-8", newline="\n") as f:
        if not done:
            f.write(json.dumps({"meta": {"model": a.model, "prompt_hash": common.PROMPT_HASH, "batch": a.batch}}, ensure_ascii=False) + "\n")
        for i in range(0, len(todo), a.batch):
            chunk = todo[i:i + a.batch]
            keys = [f"P{j + 1}" for j in range(len(chunk))]
            user = common.prompt([(k, body[r["post_id"]], r["spans"]) for k, r in zip(keys, chunk)])
            time.sleep(2.5)  # 게이트웨이 한도 분당 30회
            for wait in (65, 65, 65, 0):
                try:
                    raw = client.complete(common.SYSTEM, user)
                    break
                except llm.LLMError as e:
                    if not any(c in str(e) for c in ("429", "502", "503", "504")) or not wait:
                        raise
                    print(f"  한도 — {wait}초 뒤 다시", flush=True)
                    time.sleep(wait)
            v = common.parse(raw)
            for k, r in zip(keys, chunk):
                dec = common.decisions(v, k, len(r["spans"]))
                f.write(json.dumps({"post_id": r["post_id"], "decisions": dec, "raw": raw if dec is None else None}, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{min(i + a.batch, len(todo))}/{len(todo)}", flush=True)
    print(json.dumps({"calls": client.calls, "usage": client.usage}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
