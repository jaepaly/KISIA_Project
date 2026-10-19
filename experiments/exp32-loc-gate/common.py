"""exp32 공용 — 셋 불러오기. 교사 프롬프트 · 판정 적용은 exp30 그대로 (README §2).

셋: d1e(새 합성 판정셋) · d2(사람 검수 골드 · test 제외 275편)
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP30 = ROOT / "experiments" / "exp30-review-distill"
EXP31 = ROOT / "experiments" / "exp31-distill-v2"

_spec = importlib.util.spec_from_file_location("exp30_common", EXP30 / "common.py")
c30 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c30)

LABELS, SYSTEM, PROMPT_HASH = c30.LABELS, c30.SYSTEM, c30.PROMPT_HASH
prompt, parse, decisions, apply = c30.prompt, c30.parse, c30.decisions, c30.apply
LOC = {"LOC_ADMIN", "LOC_FACILITY"}


def d2_ids() -> set[str]:
    return set(json.load(open(HERE / "data" / "d2_post_ids.json", encoding="utf-8"))["post_ids"])


def load(name: str) -> list[dict]:
    """[{post_id, body}]."""
    if name == "d1e":
        rows = [json.loads(l) for l in open(HERE / "data" / "posts.jsonl", encoding="utf-8")]
        return [{"post_id": r["post_id"], "body": r["texts"]["body"]} for r in rows if not r.get("excluded")]
    if name == "d2":
        gold = c30._gold_rows()
        rows = [{"post_id": p, "body": gold[p]["texts"]["body"]} for p in sorted(d2_ids())]
        assert len(rows) == 275
        return rows
    raise ValueError(name)


def gold_d2() -> dict[str, list[dict]]:
    gold = c30._gold_rows()
    return {p: [s for s in gold[p]["spans"] if s["text_id"] == "body"] for p in d2_ids()}


def gate(spans: list[dict], dec: list[str] | None, types: set[str] = LOC) -> list[dict]:
    """학생 판정을 types 유형 후보에만 쓴다 — 나머지는 1단 subject 그대로 (README §3 · H 구성)."""
    if dec is None:
        return spans
    out = []
    for s, d in zip(spans, dec):
        if s["type"] not in types:
            out.append(s)
        elif d != "drop":
            out.append(dict(s, subject=d))
    return out
