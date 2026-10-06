"""C2(특정성 k)·C3(글별 기여도) 실제 엔진 — 서버가 부르는 자리.

- 조건: 탐지된 스팬 → ``kopl.c2_specificity.k_engine.conditions_from_posts`` (본인 단서만 · 위치태그 포함)
- k: ``estimate_k`` — 여러 글을 엮은 k (위치 교집합 · L2 감쇠 · 방어적 최소, #302)
- 기여도: ``kopl.c3_contribution.leave_one_out`` — risk_fn 은 C2 ``risk_total`` (exp10 · 추천 엔진과 같은 위험도)
- 글별 k: ``k_by_post`` — 「이 글을 내리면 후보가 몇 명이 되나」

목 엔진(mock.py)과 같은 함수 모양이다. 원문은 받은 그대로 계산에만 쓰고 저장하지 않는다.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from kopl.c2_specificity.engine import risk_total
from kopl.c2_specificity.k_engine import conditions_from_posts, k_by_post, specificity_document
from kopl.c3_contribution.loo import leave_one_out

# 단서가 하나도 없을 때 계약(conditions minItems 1)을 지키는 자리표시 — confidence 0 이라 k 를 좁히지 않는다
_NONE_DETECTED = {"axis": "occupation", "kind": "none_detected", "value": "NONE",
                  "resolution": 0, "confidence": 0.0}


def _k_posts(posts: Sequence[Mapping[str, Any]], spans_by_post: Mapping[str, Mapping[str, Any]]) -> list[dict]:
    out = []
    for p in posts:
        pid = str(p["post_id"])
        meta = p.get("activity_meta") or {}
        out.append({"post_id": pid,
                    "spans": list((spans_by_post.get(pid) or {}).get("spans") or []),
                    "geo_tag": meta.get("geo_tag")})
    return out


def conditions(posts: Sequence[Mapping[str, Any]], spans_by_post: Mapping[str, Mapping[str, Any]]) -> list[dict]:
    """서버가 specificity 에 넘길 조건 목록. 타인 단서(subject=other)는 빠진다."""
    conds = conditions_from_posts(_k_posts(posts, spans_by_post))
    if conds:
        return conds
    return [{**_NONE_DETECTED, "source_post_ids": [str(p["post_id"]) for p in posts] or ["none"]}]


def specificity(payload: Mapping[str, Any]) -> dict:
    conds = [c for c in payload.get("conditions") or [] if c.get("kind") != "none_detected"]
    doc = specificity_document(str(payload["user_ref"]), conds)
    doc["input"]["conditions"] = list(payload.get("conditions") or [])  # 계약 minItems 1 — 받은 그대로 기록
    return doc


def contribution(user_ref: str, posts: Sequence[Mapping[str, Any]], removed_post_ids: Sequence[str] | None = None, *,
                 spans_by_post: Mapping[str, Mapping[str, Any]] | None = None,
                 max_greedy_remove: int = 3) -> dict:
    """글별 LOO 기여도 (contribution.schema.json). ``spans_by_post`` 가 없으면 단서 0 으로 계산된다."""
    kposts = {p["post_id"]: p for p in _k_posts(posts, spans_by_post or {})}
    ids = sorted(kposts)
    if not ids:  # 글 0편 — 계약(post_ids·contributions minItems 1)을 지키는 빈 결과
        return {"schema_version": "1.0", "engine_version": "c3-loo-empty",
                "input": {"user_ref": user_ref, "post_ids": ["none"], "method": "loo"},
                "output": {"baseline_risk": 0.0, "residual_risk": 0.0,
                           "contributions": [{"post_id": "none", "risk_without": 0.0, "delta": 0.0, "rank": 1,
                                              "clue_ids": [], "top_spans": []}],
                           "user_scoped": [], "greedy_path": [], "approx_error": None,
                           "note": "글이 없어 기여도를 계산하지 않았다"}}
    cache: dict[tuple[str, ...], float] = {}

    def risk_of(selected: Sequence[str]) -> float:
        key = tuple(sorted(selected))
        if key not in cache:
            cache[key] = float(risk_total(conditions_from_posts([kposts[i] for i in key])))
        return cache[key]

    mine = {pid: [s for s in kposts[pid]["spans"] if s.get("subject") != "other"] for pid in ids}
    # clue_ids 와 top_spans 는 같은 본인 스팬을 가리킨다 (#303 리뷰 — W8 완료 조건)
    clue_index = {pid: list(dict.fromkeys(s["span_id"] for s in mine[pid])) for pid in ids}
    span_index = {pid: [{"span_id": sid, "text_id": tid}
                        for sid, tid in dict.fromkeys((s["span_id"], s["text_id"]) for s in mine[pid])] for pid in ids}
    return leave_one_out(user_ref=user_ref, post_ids=ids, risk_fn=risk_of, clue_index=clue_index, span_index=span_index,
                         removed_post_ids=removed_post_ids, max_greedy_remove=min(max_greedy_remove, max(len(ids) - 1, 0)))


def per_post_k(posts: Sequence[Mapping[str, Any]], spans_by_post: Mapping[str, Mapping[str, Any]]) -> dict:
    """화면용 — 글마다 「내리면 k」와 내리는 순서."""
    return k_by_post(_k_posts(posts, spans_by_post))
