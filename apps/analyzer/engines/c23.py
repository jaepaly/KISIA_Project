"""C2(특정성 k)·C3(글별 기여도) 실제 엔진 — 서버가 부르는 자리.

- 조건: 탐지된 스팬 → ``kopl.c2_specificity.k_engine.conditions_from_posts`` (본인 단서만 · 위치태그 포함)
- k: ``estimate_k`` — 여러 글을 엮은 k (위치 교집합 · L2 감쇠 · 방어적 최소, #302)
- 기여도: ``kopl.c3_contribution.leave_one_out`` — risk_fn 은 C2 ``risk_total`` (exp10 · 추천 엔진과 같은 위험도)
- 글별 k: ``k_by_post`` — 「이 글을 내리면 후보가 몇 명이 되나」
- 조치별 k: ``projected_k`` — 위치 태그를 떼거나 표현을 바꾸면 몇 명이 되나 (projection.py · 같은 k 엔진)
- 결정 단서: ``decisive_clues`` — k 계산 추적(steps)에 실제로 쓰인 단서와 그 근거 스팬 (작성자 확인 「내 얘기 아님」용)

목 엔진(mock.py)과 같은 함수 모양이다. 원문은 받은 그대로 계산에만 쓰고 저장하지 않는다.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from kopl.c2_specificity.engine import risk_total
from kopl.c2_specificity.k_engine import conditions_from_posts, estimate_k, k_by_post, specificity_document
from kopl.c2_specificity.k_engine import _describe as describe_condition  # steps 의 단서 이름을 만드는 바로 그 함수
from kopl.c3_contribution.loo import leave_one_out

from .projection import project

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


def projected_k(posts: Sequence[Mapping[str, Any]], spans_by_post: Mapping[str, Mapping[str, Any]],
                stage2_output: Mapping[str, Any] | None) -> dict | None:
    """화면용 — 조치마다 「바꾸면 k」 (비공개 · 위치 태그 지우기 · 바꿔 쓰기 · 바꿔 쓰기 후보 스팬 하나씩).

    k_by_post 와 같은 계산이다 — 글마다 조건을 한 번 만들어 두고, 바뀐 글만 조건을 다시 만든 뒤 estimate_k 를 부른다.
    """
    kposts = _k_posts(posts, spans_by_post)
    conds = {p["post_id"]: conditions_from_posts([p]) for p in kposts}

    def k_of(change: Mapping[str, Any]) -> float | None:
        out = []
        for pid, c in conds.items():
            if pid not in change:
                out.extend(c)
            elif change[pid] is not None:
                out.extend(conditions_from_posts([change[pid]]))
        return estimate_k(out)["k"]

    return project(kposts, stage2_output, k_of)


# steps 의 condition 문자열에 들어 있는 단서 이름 — k 엔진 _describe 의 모양 「axis:kind «값»」
_CLUE_LABEL = re.compile(r"([a-z_]+):([a-z_]+) «([^»]*)»")
MAX_DECISIVE = 8


def decisive_clues(posts: Sequence[Mapping[str, Any]], spans_by_post: Mapping[str, Mapping[str, Any]],
                   spec_output: Mapping[str, Any] | None, *, limit: int = MAX_DECISIVE) -> list[dict]:
    """화면용 — k 를 실제로 정한 단서(계산 추적 steps 에 이름이 나온 것)와 그 단서를 만든 스팬 · 위치 태그.

    k 엔진은 축마다 후보가 가장 적은 해석 하나를 고르므로, 틀린 스팬 하나가 축 전체를 정할 수 있다. 작성자가
    「내 얘기 아님」으로 확인할 수 있게 결정 단서만 추린다(스팬 수백 개 전체가 아니라).

    근거 찾기 — 스팬 하나만으로 조건을 만들어(conditions_from_posts) 그 이름이 steps 의 단서 이름과 같으면 근거다.
    같은 이름(같은 값)의 스팬은 여러 글에 있어도 모두 근거로 묶는다 — k 엔진이 글마다의 같은 단서를 하나로 합쳐 세기 때문이다.
    조건 이름이 엔진 버전에 따라 바뀌면 근거를 못 찾은 단서는 빠진다(빈 목록이 되어도 화면은 확인 칸을 그리지 않을 뿐).
    """
    labels: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for st in (spec_output or {}).get("steps") or []:
        for m in _CLUE_LABEL.finditer(str(st.get("condition") or "")):
            if m.group(0) not in seen:
                seen.add(m.group(0))
                labels.append((m.group(0), m.group(1), m.group(3)))
    if not labels:
        return []
    want = {lab for lab, _, _ in labels}
    sources: dict[str, list[dict]] = {lab: [] for lab in want}
    for p in _k_posts(posts, spans_by_post):
        pid = p["post_id"]
        for s in p["spans"]:
            if s.get("subject") == "other" or not s.get("span_id"):
                continue
            try:
                made = {describe_condition(c) for c in conditions_from_posts([{"post_id": pid, "spans": [s]}])}
            except (KeyError, TypeError, ValueError):
                continue   # 형식이 어긋난 스팬 — 근거로 쓰지 않는다(엔진 본 계산과 같은 입력이라 보통은 없다)
            for lab in made & want:
                sources[lab].append({"post_id": pid, "span_id": str(s["span_id"]), "text_id": s.get("text_id"),
                                     "start": s.get("start"), "end": s.get("end"), "text": s.get("text"),
                                     "type": s.get("type"), "subject": s.get("subject")})
        if p.get("geo_tag"):
            for c in conditions_from_posts([{"post_id": pid, "spans": [], "geo_tag": p["geo_tag"]}]):
                lab = describe_condition(c)
                if lab in want:
                    sources[lab].append({"post_id": pid, "geo_tag": str(p["geo_tag"])})
    out = [{"label": lab, "axis": axis, "value": value, "sources": sources[lab]}
           for lab, axis, value in labels if sources[lab]]
    return out[:limit]
