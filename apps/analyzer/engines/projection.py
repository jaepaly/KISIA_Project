"""조치별 「바꾸면 같은 조건의 사람 몇 명」 — 비공개와 같은 k 계산을 위치 태그 지우기 · 바꿔 쓰기에도 쓴다.

비공개는 k_by_post(글을 빼고 k 를 다시 센다)로 화면에 사람 수가 나오는데, 위치 태그 · 바꿔 쓰기는 노출 위험도만 있어
조치끼리 효과를 비교할 수 없었다. 여기서는 각 조치를 「글 묶음을 이렇게 바꾼 상태」로 만들어 엔진의 k 함수에 넘긴다.
어떤 상태로 바꾸는지는 추천 엔진(kopl.c4_stage2.recommend)이 projected_delta 를 셀 때와 같다 — 단독 효과:

- unpublish: 대상 글을 뺀다
- activity_meta: 비공개 대상이 아닌 글의 위치 태그를 뗀다 (recommend 의 ``risk(ids, no_meta=tagged)``)
- rewrite: 대상 글의 명시(explicit) 스팬을 지운다 (recommend 의 ``risk(ids, rewrite=explicit_posts)``) — 다 고쳤을 때의 상한
- 바꿔 쓰기 후보(``rewrites``)의 스팬 하나: 그 스팬만 지운다. 「단서가 남음」 후보도 지운 것으로 센다(상한)

계약 밖 · 화면 전용 응답 칸(``k_by_action``)이다 — stage2-io 의 Action 에는 사람 수 칸이 없다.
엔진에 따라 k 함수만 다르다 (real: C2 k 엔진 · mock: 목 specificity). 이 파일은 모델·사전을 불러오지 않는다.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

# 바꿔 쓰기 후보 스팬을 몇 곳까지 셀지 — 한 곳마다 k 를 한 번 다시 센다. 화면은 이 순서(rewrites 순)대로 카드를 그린다
MAX_SPANS = 12

# {post_id: 바뀐 글(None = 비공개로 뺌)} → k (산출 불가면 None)
KFn = Callable[[Mapping[str, "dict[str, Any] | None"]], "float | None"]


def _post_refs(action: Mapping[str, Any]) -> list[str]:
    return list(dict.fromkeys(str(t["ref"]) for t in action.get("targets") or [] if t.get("kind") == "post"))


def project(kposts: Sequence[Mapping[str, Any]], stage2_output: Mapping[str, Any] | None, k_of: KFn, *,
            max_spans: int = MAX_SPANS) -> dict[str, Any] | None:
    """kposts: [{post_id, spans, geo_tag}] (엔진의 k 입력 그대로). 추천이 없으면 by_action 이 빈다."""
    if not kposts:
        return None
    by_id = {str(p["post_id"]): p for p in kposts}
    out_doc = stage2_output or {}
    actions = list(((out_doc.get("recommendation") or {}).get("actions")) or [])
    hidden = [pid for a in actions if a.get("action_type") == "unpublish" for pid in _post_refs(a) if pid in by_id]

    base = k_of({})
    by_action: dict[str, Any] = {}
    for a in actions:
        kind = a.get("action_type")
        if kind in by_action:
            continue
        if kind == "unpublish":
            change = {pid: None for pid in hidden}
        elif kind == "activity_meta":
            change = {pid: {**p, "geo_tag": None} for pid, p in by_id.items() if pid not in hidden and p.get("geo_tag")}
        elif kind == "rewrite":
            change = {pid: {**by_id[pid], "spans": [s for s in by_id[pid].get("spans") or [] if s.get("level") != "explicit"]}
                      for pid in _post_refs(a) if pid in by_id}
        else:
            continue
        by_action[kind] = k_of(change) if change else base

    by_span: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for r in out_doc.get("rewrites") or []:
        key = (str(r.get("post_id")), str(r.get("span_id")))
        if key in seen or key[0] not in by_id:
            continue
        seen.add(key)
        if len(by_span) >= max_spans:
            break
        p = by_id[key[0]]
        spans = [s for s in p.get("spans") or [] if s.get("span_id") != key[1]]
        if len(spans) == len(p.get("spans") or []):
            continue  # 그 스팬이 탐지 결과에 없다 — 셀 수 없다
        by_span.append({"post_id": key[0], "span_id": key[1], "k_after": k_of({key[0]: {**p, "spans": spans}})})
    return {"k": base, "by_action": by_action, "by_span": by_span}
