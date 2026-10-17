"""exp31 공용 — exp30 의 교사 프롬프트 v3 · 판정 적용을 그대로 쓰고, 새 셋만 더한다 (README §2).

셋: d1d(새 판정셋) · d5(새 회귀 셋 175편) · aug2(대조 보강 합성 글) — 학습용 exp30 셋(pool · aug)은 exp30 결과 파일을 읽는다.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP30 = ROOT / "experiments" / "exp30-review-distill"

_spec = importlib.util.spec_from_file_location("exp30_common", EXP30 / "common.py")
c30 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c30)

LABELS, SYSTEM, PROMPT_HASH = c30.LABELS, c30.SYSTEM, c30.PROMPT_HASH
prompt, parse, decisions, apply = c30.prompt, c30.parse, c30.decisions, c30.apply   # 교사 프롬프트는 exp30 v3 그대로


def d5_ids() -> set[str]:
    return set(json.load(open(HERE / "data" / "d5_post_ids.json", encoding="utf-8"))["post_ids"])


def load(name: str) -> list[dict]:
    """[{post_id, body}]."""
    if name in ("d1d", "aug2"):
        f = HERE / "data" / ("posts.jsonl" if name == "d1d" else "aug2_posts.jsonl")
        rows = [json.loads(l) for l in open(f, encoding="utf-8")]
        return [{"post_id": r["post_id"], "body": r["texts"]["body"]} for r in rows if not r.get("excluded")]
    if name == "d5":
        gold = c30._gold_rows()
        rows = [{"post_id": p, "body": gold[p]["texts"]["body"]} for p in sorted(d5_ids())]
        assert len(rows) == 175
        return rows
    raise ValueError(name)


def gold_d5() -> dict[str, list[dict]]:
    gold = c30._gold_rows()
    return {p: [s for s in gold[p]["spans"] if s["text_id"] == "body"] for p in d5_ids()}
