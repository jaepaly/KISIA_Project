"""게시물별 위험 기여도를 Leave-One-Out 방식으로 계산한다.

C2 다축 위험도 계산기는 아직 공개 API가 고정되지 않았으므로, 이 모듈은
게시물 ID 집합을 받아 0~100 위험도를 반환하는 ``risk_fn``을 주입받는다.
이렇게 하면 C2 구현이 바뀌어도 LOO의 순위·부호·greedy 계약은 유지된다.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

ENGINE_VERSION = "c3-0.1.0"
_USER_REF_RE = re.compile(r"^u_[0-9a-f]{8,}$")
# contribution.schema.json 계약 확정 시 맞춰 변경
_MAX_TOP_SPANS = 3

RiskFunction = Callable[[tuple[str, ...]], float]
SpanRef = Mapping[str, str]


def _validate_score(value: Any, *, name: str) -> float:
    """위험도 계약 범위(0~100)의 유한 실수인지 확인한다."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name}는 0~100 사이의 숫자여야 합니다.")
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 100.0:
        raise ValueError(f"{name}는 0~100 사이의 유한한 숫자여야 합니다: {value!r}")
    return score


def _normalize_ids(post_ids: Sequence[str]) -> tuple[str, ...]:
    """게시물 ID를 검증하고 호출 순서와 무관하도록 정렬한다."""
    ids = tuple(post_ids)
    if not ids:
        raise ValueError("post_ids는 한 개 이상이어야 합니다.")
    if any(not isinstance(post_id, str) or not post_id for post_id in ids):
        raise ValueError("post_id는 빈 문자열이 아닌 문자열이어야 합니다.")
    if len(set(ids)) != len(ids):
        raise ValueError("post_ids에 중복이 있습니다.")
    return tuple(sorted(ids))


def _normalize_clue_ids(
    clue_index: Mapping[str, Sequence[str]], post_id: str
) -> list[str]:
    clue_ids = list(clue_index.get(post_id, ()))
    if any(not isinstance(clue_id, str) or not clue_id for clue_id in clue_ids):
        raise ValueError(f"{post_id}의 clue_id는 빈 문자열이 아닌 문자열이어야 합니다.")
    if len(set(clue_ids)) != len(clue_ids):
        raise ValueError(f"{post_id}의 clue_ids에 중복이 있습니다.")
    return clue_ids


def _normalize_spans(
    span_index: Mapping[str, Sequence[SpanRef]], post_id: str
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ref in span_index.get(post_id, ()):
        span_id = ref.get("span_id")
        text_id = ref.get("text_id")
        if not isinstance(span_id, str) or not span_id:
            raise ValueError(f"{post_id}의 span_id가 올바르지 않습니다.")
        if not isinstance(text_id, str) or not text_id:
            raise ValueError(f"{post_id}의 text_id가 올바르지 않습니다.")
        key = (span_id, text_id)
        if key in seen:
            raise ValueError(f"{post_id}의 top_spans에 중복이 있습니다: {key!r}")
        seen.add(key)
        refs.append({"span_id": span_id, "text_id": text_id})
    return refs[:_MAX_TOP_SPANS]


def leave_one_out(
    *,
    user_ref: str,
    post_ids: Sequence[str],
    risk_fn: RiskFunction,
    clue_index: Mapping[str, Sequence[str]] | None = None,
    span_index: Mapping[str, Sequence[SpanRef]] | None = None,
    residual_risk: float = 0.0,
    user_scoped: Sequence[Mapping[str, Any]] | None = None,
    removed_post_ids: Sequence[str] | None = None,
    max_greedy_remove: int | None = None,
) -> dict[str, Any]:
    """전체 위험도와 게시물별 LOO 기여도를 계약 형식으로 반환한다.

    ``risk_fn``은 정렬된 게시물 ID 튜플을 받아 0~100 위험도를 반환한다.
    게시물 제거만으로 사용자 단위 위험인 ``residual_risk`` 아래로 내려가지
    않도록 모든 결과에 하한을 적용한다.
    """
    if not isinstance(user_ref, str) or _USER_REF_RE.fullmatch(user_ref) is None:
        raise ValueError("user_ref는 'u_' 뒤에 8자리 이상 소문자 16진수가 와야 합니다.")
    if not callable(risk_fn):
        raise TypeError("risk_fn은 호출 가능한 함수여야 합니다.")

    ids = _normalize_ids(post_ids)
    id_set = set(ids)
    residual = _validate_score(residual_risk, name="residual_risk")
    clues = clue_index or {}
    spans = span_index or {}
    normalized_user_scoped: list[dict[str, Any]] = []
    for item in user_scoped or ():
        source = item.get("source")
        if source not in {"profile_bio", "nickname", "activity_pattern"}:
            raise ValueError(f"허용되지 않은 user_scoped source: {source!r}")
        delta_value = item.get("delta", 0.0)
        if (
            isinstance(delta_value, bool)
            or not isinstance(delta_value, (int, float))
            or not math.isfinite(float(delta_value))
            or abs(float(delta_value)) > 100.0
        ):
            raise ValueError("user_scoped delta는 -100~100 사이의 유한한 숫자여야 합니다.")
        raw_delta = float(delta_value)
        refs = _normalize_spans({"user": item.get("top_spans", ())}, "user")
        normalized_user_scoped.append(
            {"source": source, "delta": round(raw_delta, 2), "top_spans": refs}
        )
    if residual > 0.0 and not normalized_user_scoped:
        raise ValueError("residual_risk가 0보다 크면 user_scoped가 한 개 이상 필요합니다.")

    removed = tuple(sorted(removed_post_ids or ()))
    if len(set(removed)) != len(removed):
        raise ValueError("removed_post_ids에 중복이 있습니다.")
    unknown_removed = set(removed) - id_set
    if unknown_removed:
        raise ValueError(
            "removed_post_ids는 post_ids의 부분집합이어야 합니다: "
            + ", ".join(sorted(unknown_removed))
        )

    cache: dict[tuple[str, ...], float] = {}

    def evaluate(selected: Sequence[str]) -> float:
        key = tuple(sorted(selected))
        if key not in cache:
            raw = _validate_score(risk_fn(key), name="risk_fn 반환값")
            cache[key] = max(residual, raw)
        return cache[key]

    baseline = evaluate(ids)
    rows: list[dict[str, Any]] = []
    for post_id in ids:
        without = evaluate(tuple(pid for pid in ids if pid != post_id))
        rows.append(
            {
                "post_id": post_id,
                "risk_without": round(without, 2),
                "delta": round(without - baseline, 2),
                "rank": 0,
                "clue_ids": _normalize_clue_ids(clues, post_id),
                "top_spans": _normalize_spans(spans, post_id),
            }
        )

    rows.sort(key=lambda row: (-abs(row["delta"]), row["post_id"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank

    limit = len(ids) if max_greedy_remove is None else max_greedy_remove
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("max_greedy_remove는 0 이상의 정수여야 합니다.")

    remaining = list(ids)
    current = baseline
    greedy_path: list[dict[str, Any]] = []
    while remaining and len(greedy_path) < limit and current > residual:
        candidates = [
            (
                evaluate(tuple(pid for pid in remaining if pid != candidate)),
                candidate,
            )
            for candidate in remaining
        ]
        best_risk, best_post = min(candidates, key=lambda item: (item[0], item[1]))
        if best_risk >= current - 1e-12:
            break
        remaining.remove(best_post)
        current = best_risk
        greedy_path.append(
            {"remove": best_post, "risk_after": round(current, 2)}
        )

    risk_after: float | None = None
    if removed_post_ids is not None:
        risk_after = round(
            evaluate(tuple(pid for pid in ids if pid not in set(removed))), 2
        )

    return {
        "schema_version": "1.0",
        "engine_version": ENGINE_VERSION,
        "input": {
            "user_ref": user_ref,
            "post_ids": list(ids),
            "method": "loo",
            **({"removed_post_ids": list(removed)} if removed_post_ids is not None else {}),
        },
        "output": {
            "baseline_risk": round(baseline, 2),
            "residual_risk": round(residual, 2),
            "risk_after": risk_after,
            "contributions": rows,
            "user_scoped": normalized_user_scoped,
            "greedy_path": greedy_path,
            "approx_error": None,
            "note": (
                "greedy_path는 매 제거 후 위험도를 재계산한 값이므로 "
                "delta 상위 n개의 단순 합과 일치하지 않을 수 있다."
            ),
        },
    }
