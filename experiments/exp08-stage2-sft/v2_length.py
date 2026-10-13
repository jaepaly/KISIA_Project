"""2단 v2 길이 확인 (W9 D 5번) — 학습 데이터 · 앱 입력의 토큰 길이 분포와 최대 길이별 탈락 수.

    PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 python experiments/exp08-stage2-sft/v2_length.py

1. v1 학습 데이터(data/v1_train · v1_dev) 원본 그대로 — v1 은 max_len 1024 로 학습했다
2. 실제 크기 계정 — 115명 전체 글(test 글 제외) · 스팬 = 교사 라벨 + 검수 골드 · 앱과 같은 가명화(`pseudonymize_spans`) ·
   앱과 같은 고르기(`select_for_model`)를 상한별로 · 정답 findings 는 고른 스팬으로 다시 계산
   - 「빈 글 포함」 = 지금 앱 입력(스팬 없는 글도 목록에 남는다) · 상한 24/6
   - 그 밖 = 스팬 없는 글을 뺀 입력
토큰 수는 Qwen3-4B chat template(enable_thinking=False) 기준 · system 은 앱의 SYSTEM_V1.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(HERE)]
from transformers import AutoTokenizer  # noqa: E402

from kopl.c4_stage2.infer import SYSTEM_V1, pseudonymize_spans, select_for_model  # noqa: E402
from make_sft_v1 import findings_from_spans  # noqa: E402

tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-4B")
LIMITS = (1024, 1408, 2048, 2560)


def ntok(messages: list[dict]) -> tuple[int, int]:
    prompt = tok.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    full = tok.apply_chat_template(messages, tokenize=False, enable_thinking=False)
    p = len(tok(prompt, add_special_tokens=False)["input_ids"])
    return len(tok(full, add_special_tokens=False)["input_ids"]), len(tok(full, add_special_tokens=False)["input_ids"]) - p


def pct(xs: list[int], q: float) -> int:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1)))]


def summarize(rows: list[dict]) -> dict:
    tot = [r["total"] for r in rows]
    cut = pct([r["posts"] for r in rows], .75)
    long = [r for r in rows if r["posts"] >= cut]
    return {"n": len(rows), "posts_median": statistics.median(r["posts"] for r in rows),
            "spans_median": statistics.median(r["spans"] for r in rows), "spans_max": max(r["spans"] for r in rows),
            "total_median": statistics.median(tot), "total_p90": pct(tot, .9), "total_max": max(tot),
            "completion_max": max(r["completion"] for r in rows),
            **{f"over_{L}": sum(t > L for t in tot) for L in LIMITS},
            "long_accounts": {"posts_ge": cut, "n": len(long), **{f"over_{L}": sum(r["total"] > L for r in long) for L in LIMITS}}}


def example(posts: list[dict], findings: dict) -> list[dict]:
    return [{"role": "system", "content": SYSTEM_V1},
            {"role": "user", "content": json.dumps({"user_ref": "u_000000000000", "profile": None, "posts": posts}, ensure_ascii=False)},
            {"role": "assistant", "content": json.dumps({"findings": findings, "rewrites": []}, ensure_ascii=False)}]


def main() -> int:
    out: dict = {}
    for split in ("v1_train", "v1_dev"):
        rows = []
        for line in (HERE / f"data/{split}.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                msgs = json.loads(line)["messages"]
                user = json.loads(msgs[1]["content"])
                t, c = ntok(msgs)
                rows.append({"total": t, "completion": c, "posts": len(user["posts"]),
                             "spans": sum(len(p["spans"]) for p in user["posts"])})
        out[f"{split} 원본"] = summarize(rows)

    test_ids = set(json.loads((ROOT / "data/corpus/v0/splits/test_post_ids.json").read_text(encoding="utf-8"))["post_ids"])
    gold: dict[str, list[dict]] = {}
    for f in sorted((ROOT / "data/corpus/v0/gold").glob("*_spans.jsonl")):
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            r = json.loads(line) if line.strip() else {}
            if "post_id" in r:
                gold[r["post_id"]] = r.get("spans") or []
    accounts = []
    for f in sorted((ROOT / "data/corpus/v0/posts").glob("*.jsonl")):
        posts = [json.loads(l) for l in f.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
        posts = [p for p in posts if "post_id" in p and p["post_id"] not in test_ids]
        if posts:
            accounts.append([{"post_id": p["post_id"], "spans": pseudonymize_spans(
                {"texts": p.get("texts") or {}, "spans": gold.get(p["post_id"], [])})} for p in posts])

    for cap, per, keep_empty in ((24, 6, True), (24, 6, False), (20, 5, False), (18, 5, False), (16, 4, False), (12, 3, False)):
        rows = []
        for entries in accounts:
            sel = select_for_model(entries, max_spans=cap, max_per_type=per)
            findings = findings_from_spans([(e["post_id"], e["spans"]) for e in sel])
            if not keep_empty:
                sel = [e for e in sel if e["spans"]]
            t, c = ntok(example(sel, findings))
            rows.append({"total": t, "completion": c, "posts": len(entries), "spans": sum(len(e["spans"]) for e in sel)})
        out[f"실제 계정 상한 {cap}/{per}" + (" 빈 글 포함(지금 앱)" if keep_empty else "")] = summarize(rows)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
