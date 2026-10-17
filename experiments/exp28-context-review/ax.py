"""exp28 참고 — 외부 큰 모델(Claude · KISIA 키)로 보정(AX) · 대체(BX)를 D1 에만 돌린다 (README §2 · 판정에 쓰지 않음).

    export PYTHONIOENCODING=utf-8 PYTHONPATH=src   (ANTHROPIC_AUTH_TOKEN · ANTHROPIC_BASE_URL 은 환경변수)
    python experiments/exp28-context-review/ax.py --mode A --model claude-opus-4-8

프롬프트 · 적용 규칙은 review.py 와 같다. results/a0_d1.jsonl 이 있어야 한다. 출력: results/{AX|BX}_d1.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import review
from kopl.c5_corpus import llm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["A", "B"], required=True)
    ap.add_argument("--model", default="claude-opus-4-8")
    a = ap.parse_args()
    from kopl.c1_span import rules as rules_mod
    from kopl.c1_span.attributes import resolve

    explicit = rules_mod.ExplicitRules()
    rows = review.load_d1()
    a0 = {json.loads(l)["post_id"]: json.loads(l)["spans"] for l in open(review.HERE / "results" / "a0_d1.jsonl", encoding="utf-8")}
    client = llm.LLMClient("anthropic", model=a.model, temperature=0.0, max_tokens=1024, max_retries=1)
    out = review.HERE / "results" / f"{a.mode}X_d1.jsonl"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"meta": {"mode": a.mode, "model": a.model, "prompt_hash": review.PROMPT_HASH, "external": True}}, ensure_ascii=False) + "\n")
        for i, r in enumerate(rows, 1):
            user = review.prompt_a(r["body"], a0[r["post_id"]]) if a.mode == "A" else review.prompt_b(r["body"])
            time.sleep(2.5)  # 게이트웨이 한도 분당 30회
            for wait in (65, 65, 65, 0):
                try:
                    t = time.perf_counter()
                    raw = client.complete(review.SYSTEM, user)
                    break
                except llm.LLMError as e:
                    if "429" not in str(e) or not wait:
                        raise
                    print(f"  한도 — {wait}초 뒤 다시", flush=True)
                    time.sleep(wait)
            sec = time.perf_counter() - t
            v = review.parse(raw)
            spans = review.apply_a(r["body"], a0[r["post_id"]], v) if a.mode == "A" else \
                review.apply_b(r["post_id"], r["body"], v, rules_mod, explicit, resolve)
            f.write(json.dumps({"post_id": r["post_id"], "spans": spans, "parsed": v is not None, "raw": raw, "sec": round(sec, 3)}, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{i}/{len(rows)} {sec:.1f}s", flush=True)
    print(json.dumps({"calls": client.calls, "usage": client.usage}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(review.HERE))
    sys.exit(main())
