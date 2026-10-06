"""분석 앱과 C2·C3 엔진 사이의 계약 응답 어댑터."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from kopl.c2_specificity import (
    RegionDictionary,
    build_conditions,
    classify_k,
    risk_by_axis,
    risk_total,
)
from kopl.c3_contribution import leave_one_out

SPEC_ENGINE_VERSION = "c2-0.1.0"
DICT_VERSION = "geo-2026-07"


def conditions_by_post(
    spans_by_post: Mapping[str, Mapping[str, Any] | Sequence[Mapping[str, Any]]],
    *,
    dictionary: RegionDictionary | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """탐지 응답 또는 스팬 목록을 글별 C2 조건으로 바꾼다."""
    result: dict[str, list[dict[str, Any]]] = {}
    for post_id, value in spans_by_post.items():
        spans = value.get("spans", []) if isinstance(value, Mapping) else value
        result[post_id] = build_conditions(spans, post_id, dictionary=dictionary)
    return result


def flatten_conditions(
    by_post: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    include_empty_sentinel: bool = False,
) -> list[dict[str, Any]]:
    conditions = [
        dict(condition)
        for post_id in sorted(by_post)
        for condition in by_post[post_id]
    ]
    if conditions or not include_empty_sentinel:
        return conditions
    post_ids = sorted(by_post) or ["empty_account"]
    return [{
        "axis": "occupation",
        "kind": "none_detected",
        "value": "none_detected",
        "resolution": 0,
        "confidence": 0.0,
        "source_post_ids": post_ids,
    }]


def specificity(
    payload: Mapping[str, Any],
    *,
    dictionary: RegionDictionary | None = None,
) -> dict[str, Any]:
    """C2 숫자 API를 specificity.schema.json 응답으로 감싼다."""
    conditions = [dict(item) for item in payload.get("conditions", [])]
    if not conditions:
        raise ValueError("specificity 입력에는 조건이 한 개 이상 필요합니다")

    axes = risk_by_axis(conditions)
    risk = risk_total(conditions)
    region_dictionary = dictionary or RegionDictionary()
    locations = sorted(
        (item for item in conditions if item.get("axis") == "location"),
        key=lambda item: (-int(item.get("resolution", 0)), -float(item.get("confidence", 0))),
    )

    k: int | None = None
    steps: list[dict[str, Any]] = []
    basis = {
        "source": "행정안전부 주민등록 인구통계",
        "as_of": region_dictionary.population_as_of,
        "method": "unresolved",
    }
    for location in locations:
        code = str(location.get("geo_code", ""))
        region = region_dictionary.regions.get(code)
        if region is None:
            continue
        k = max(1, int(region["population"]))
        basis["method"] = "direct"
        steps = [{
            "axis": "location",
            "condition": f"{region.get('full_name', region.get('name', code))}({code})",
            "n_after": k,
            "method": "population_lookup",
        }]
        break

    return {
        "schema_version": "1.0",
        "engine_version": SPEC_ENGINE_VERSION,
        "dict_version": DICT_VERSION,
        "input": dict(payload),
        "output": {
            "k": k,
            "k_level": classify_k(k),
            "basis": basis,
            "risk": round(risk, 2),
            "risk_by_axis": {axis: round(value, 2) for axis, value in axes.items()},
            "floor_applied": False,
            "steps": steps,
            "assumptions": [
                "k는 해석 가능한 최고 해상도 위치 조건의 주민등록 인구다.",
                "7축 위험도는 축별 최고 해상도를 사용하며 같은 축 조건을 중복 곱하지 않는다.",
            ],
        },
    }


def contribution(
    user_ref: str,
    post_ids: Sequence[str],
    *,
    spans_by_post: Mapping[str, Mapping[str, Any] | Sequence[Mapping[str, Any]]],
    conditions: Mapping[str, Sequence[Mapping[str, Any]]],
    removed_post_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """글별 조건을 재사용해 C3 LOO 계약 응답을 만든다."""
    ids = list(post_ids)
    missing = set(ids) - set(conditions)
    if missing:
        raise ValueError("조건이 없는 post_id: " + ", ".join(sorted(missing)))

    def risk_fn(selected: tuple[str, ...]) -> float:
        selected_conditions = [
            condition
            for post_id in selected
            for condition in conditions[post_id]
        ]
        return risk_total(selected_conditions)

    clue_index: dict[str, list[str]] = {}
    span_index: dict[str, list[dict[str, str]]] = {}
    for post_id in ids:
        value = spans_by_post.get(post_id, [])
        spans = value.get("spans", []) if isinstance(value, Mapping) else value
        clue_index[post_id] = [
            str(span["span_id"]) for span in spans if span.get("span_id")
        ]
        span_index[post_id] = [
            {"span_id": str(span["span_id"]), "text_id": str(span["text_id"])}
            for span in spans
            if span.get("span_id") and span.get("text_id")
        ]

    return leave_one_out(
        user_ref=user_ref,
        post_ids=ids,
        risk_fn=risk_fn,
        clue_index=clue_index,
        span_index=span_index,
        removed_post_ids=removed_post_ids,
    )
