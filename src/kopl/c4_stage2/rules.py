"""2단 판정 규칙 — 스팬만으로 7속성 verdict 를 정한다 (#279 판정 기준).

2단 학습 타깃(exp08 make_sft_v1.findings_from_spans)과 같은 규칙이다. 제품에서는
모델을 못 쓸 때(GPU·어댑터 없음, 출력 파싱 실패)의 폴백으로 쓴다.

    본인(subject=self) 스팬만 센다 — explicit 이 하나라도 있으면 specified ·
    아니면 implicit 이 하나라도 있으면 narrowed · 아니면 inferential 만 있는데
    서로 다른 글 2편 이상이면 narrowed · inferential 이 글 1편뿐이면 weak_signal ·
    단서가 없으면 abstain
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")

# label-schema §3-2 스팬 유형 → 속성. make_sft_v1.TYPE_TO_ATTR 과 같다
TYPE_TO_ATTR = {
    "AGE": "age",
    "SEX": "sex",
    "LOC_ADMIN": "location",
    "LOC_FACILITY": "location",
    "JOB": "occupation",
    "REL_WORK": "occupation",
    "FAM": "family",
    "REL_HOME": "family",  # 학습 타깃과 같게 둔다 — 바꾸면 v1 어댑터와 폴백 판정이 어긋난다
    "COMMUTE": "commute",
    "INCOME": "income",
}

CONFIDENCE = {
    "specified": 0.9,
    "narrowed_implicit": 0.7,
    "narrowed_inferential": 0.6,
    "weak_signal": 0.4,
    "abstain": 0.1,
}


def findings_from_spans(posts: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """``posts``: ``[{"post_id", "spans": [{span_id, type, level, subject, ...}]}]`` → 계약 findings."""
    out: dict[str, dict[str, Any]] = {}
    for attr in ATTRS:
        cands: list[tuple[str, str, str]] = []  # (level, post_id, span_id)
        for post in posts:
            for s in post.get("spans") or []:
                if TYPE_TO_ATTR.get(str(s.get("type"))) != attr or s.get("subject") != "self":
                    continue
                if s.get("level") in ("explicit", "implicit", "inferential"):
                    cands.append((s["level"], post["post_id"], s["span_id"]))
        levels = {lv for lv, _, _ in cands}
        if not cands:
            verdict, conf = "abstain", CONFIDENCE["abstain"]
        elif "explicit" in levels:
            verdict, conf = "specified", CONFIDENCE["specified"]
        elif "implicit" in levels:
            verdict, conf = "narrowed", CONFIDENCE["narrowed_implicit"]
        elif len({pid for lv, pid, _ in cands if lv == "inferential"}) >= 2:
            verdict, conf = "narrowed", CONFIDENCE["narrowed_inferential"]
        else:
            verdict, conf = "weak_signal", CONFIDENCE["weak_signal"]
        out[attr] = {
            "verdict": verdict,
            "confidence": conf,
            "cross_post": len({pid for _, pid, _ in cands}) >= 2,
            "evidence": [{"post_id": pid, "span_id": sid} for _, pid, sid in cands],
        }
    return out
