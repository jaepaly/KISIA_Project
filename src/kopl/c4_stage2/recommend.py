"""추천 엔진 v1 — 조치 조합을 규칙으로 만들어 stage2-io 의 recommendation 을 채운다.

exp10(조치 3단계 재현, #281)의 규칙을 제품 코드로 옮긴 것이다. 모델 호출은 없다.

    비공개 → 활동 메타(위치태그) → 리라이트(명시 단서) 순으로 쌓고,
    누적 위험도가 목표 이하가 되면 거기서 멈춘다 (최소 조치).

- 비공개: C3 ``leave_one_out`` 의 ``greedy_path`` 앞 k편. k 는 exp10 과 같다 —
  글 수의 3/19(선행 PoC 「이 글 3개를 비공개하면」, R1 19편 중 3편), 최소 1편, 최소 1편은 공개로 남긴다.
  greedy 도중 목표에 닿으면 그 편수에서 자른다.
- 활동 메타: 공개로 남은 글의 위치태그를 떼는 것. 계약 targets 는 ``meta_field: geo_tag`` 하나다.
- 리라이트: 공개로 남은 글의 **명시(explicit) 단서 스팬**을 지운 것으로 모사한다 (exp10 본 지표와 같다).
  실제 문장을 바꾸는 리라이터는 W9 — 그 전까지 이 조치의 효과는 「명시 단서를 다 고쳤을 때」의 상한에 가깝다.

``projected_delta`` 는 조치 **단독** 효과다 (같은 대상에 그 조치만 했을 때 − 현재). 조합 전체의
효과는 ``projected`` 에 누적으로 담는다. 화면이 「이 조치만 하면」과 「전부 하면」을 둘 다 보여줄 수 있게.

프로필 소개란(``profile``)·삭제 권고(``exceptional``)·최적해 격차는 v1 범위 밖이다.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

ENGINE_VERSION = "c4-recommend-0.1.0"

# exp10 build_inputs.py UNPUBLISH_FRACTION 과 같은 값 — 바꾸면 exp10 재현 수치와 어긋난다
UNPUBLISH_FRACTION = 3 / 19
# plan.md §2 조치 메뉴 — 부담: 비공개 낮음 · 메타 중간 · 리라이트 높음(뼈대 표현) / 중간
_BURDEN_ORDER = {"low": 0, "medium": 1, "high": 2}
_DEFAULT_TARGET = 40.0

ConditionsFn = Callable[[Sequence[Mapping[str, Any]], str], list[dict[str, Any]]]
GeoConditionFn = Callable[[str, str], "dict[str, Any] | None"]
RiskFn = Callable[[Sequence[Mapping[str, Any]]], float]


class C2Engine:
    """C2 조건 생성·위험도를 한데 묶는다. 사전 로딩이 무거워 처음 쓸 때 한 번만 만든다."""

    def __init__(self) -> None:
        from kopl.c2_specificity import clues, engine, model

        self._clues = clues
        self._dictionary = engine.RegionDictionary()
        self._risk_total = engine.risk_total
        self._level_resolution = model.REGION_LEVEL_RESOLUTION

    def conditions(self, spans: Sequence[Mapping[str, Any]], post_id: str) -> list[dict[str, Any]]:
        return self._clues.build_conditions(spans, post_id, dictionary=self._dictionary)

    def geo_condition(self, tag: str, post_id: str) -> dict[str, Any] | None:
        """위치태그 → location condition. 후보가 하나일 때만 geo_code (exp10 · #272 7번 규칙)."""
        info = self._dictionary.resolve_info(tag)
        codes = list(info["codes"])
        cond: dict[str, Any] = {"axis": "location", "kind": "administrative_area", "value": tag}
        resolution = 2
        if str(info["resolution"]) == "unique" and len(codes) == 1:
            cond["geo_code"] = codes[0]
            level = str(self._dictionary.regions.get(codes[0], {}).get("level", ""))
            resolution = self._level_resolution.get(level, 2)
        cond.update({"resolution": resolution, "confidence": 1.0, "source_post_ids": [post_id]})
        return cond

    def risk(self, conditions: Sequence[Mapping[str, Any]]) -> float:
        return self._risk_total(conditions)


_DEFAULT_ENGINE: C2Engine | None = None


def _default_engine() -> C2Engine:
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        _DEFAULT_ENGINE = C2Engine()
    return _DEFAULT_ENGINE


def unpublish_k(n: int) -> int:
    """비공개 최대 편수 — exp10 과 같은 규칙. 글이 1편이면 0."""
    if n < 2:
        return 0
    return min(max(1, math.floor(UNPUBLISH_FRACTION * n + 0.5)), n - 1)


def _is_skeleton(spans: Sequence[Mapping[str, Any]], target: Mapping[str, Any]) -> bool:
    """계약 Action.burden — 같은 표현이 한 글에서 두 번 이상 나오거나 제목과 본문에 함께 나오면 뼈대."""
    text = target.get("text")
    if not text:
        return False
    same = [s for s in spans if s.get("text") == text]
    channels = {str(s.get("text_id", "")).split(":")[0] for s in same}
    return len(same) >= 2 or {"title", "body"} <= channels


def _round(x: float) -> float:
    return round(x, 2)


def recommend(
    *,
    user_ref: str,
    posts: Sequence[Mapping[str, Any]],
    target_risk: float = _DEFAULT_TARGET,
    conditions_fn: ConditionsFn | None = None,
    geo_condition_fn: GeoConditionFn | None = None,
    risk_fn: RiskFn | None = None,
) -> dict[str, Any]:
    """한 사용자의 글 묶음에 대한 기본 추천을 stage2-io ``recommendation`` 형식으로 낸다.

    ``posts`` 원소: ``{"post_id", "spans": [1단 스팬(type·text·level·subject·span_id·text_id)], "geo_tag": str | None}``.
    스팬의 level·subject 는 판정값이어야 한다 — 임시값(implicit/self)이면 위험도도 그만큼 틀린다.
    엔진 함수 셋은 테스트용 주입 자리다. 비우면 C2 를 쓴다.
    """
    from kopl.c3_contribution import leave_one_out

    if conditions_fn is None or geo_condition_fn is None or risk_fn is None:
        eng = _default_engine()
        conditions_fn = conditions_fn or eng.conditions
        geo_condition_fn = geo_condition_fn or eng.geo_condition
        risk_fn = risk_fn or eng.risk
    if not posts:
        raise ValueError("posts 는 한 편 이상이어야 한다")
    if not 0.0 <= float(target_risk) <= 100.0:
        raise ValueError("target_risk 는 0~100")

    by_id = {str(p["post_id"]): p for p in posts}
    if len(by_id) != len(posts):
        raise ValueError("post_id 중복")
    ids = sorted(by_id)
    geo = {pid: (geo_condition_fn(by_id[pid]["geo_tag"], pid) if by_id[pid].get("geo_tag") else None)
           for pid in ids}

    def risk(visible: Sequence[str], *, no_meta: Sequence[str] = (), rewrite: Sequence[str] = ()) -> float:
        """visible 글만 · no_meta 글은 위치태그 뗌 · rewrite 글은 명시 스팬 지움."""
        conds: list[dict[str, Any]] = []
        for pid in visible:
            spans = list(by_id[pid].get("spans") or [])
            if pid in rewrite:
                spans = [s for s in spans if s.get("level") != "explicit"]
            conds.extend(conditions_fn(spans, pid))
            if geo[pid] is not None and pid not in no_meta:
                conds.append(geo[pid])
        return float(risk_fn(conds))

    current = risk(ids)
    target = float(target_risk)
    actions: list[dict[str, Any]] = []
    level = current  # 누적 위험도

    # ① 비공개 — LOO greedy 앞 k편, 목표에 닿으면 거기서 자른다
    hidden: list[str] = []
    k = unpublish_k(len(ids))
    if level > target and k:
        loo = leave_one_out(user_ref=user_ref, post_ids=ids,
                            risk_fn=lambda sel: risk(sel), max_greedy_remove=k)
        for step in loo["output"]["greedy_path"]:
            hidden.append(step["remove"])
            # greedy_path.risk_after 는 소수 둘째 자리로 반올림돼 있다 — 판정은 반올림 전 값으로
            if risk([pid for pid in ids if pid not in set(hidden)]) <= target:
                break
    public = [pid for pid in ids if pid not in set(hidden)]
    if hidden:
        after = risk(public)
        actions.append({
            "action_type": "unpublish",
            "burden": "low",
            "certainty": "highest",
            "targets": [{"kind": "post", "ref": pid} for pid in hidden],
            "projected_delta": _round(min(0.0, after - current)),  # 첫 단계라 단독 = 누적
            "rationale": f"위험도 기여가 큰 글 {len(hidden)}편 — 이 글만 비공개해도 {_round(current)} → {_round(after)}",
        })
        level = after

    # ② 활동 메타 — 공개로 남은 글의 위치태그
    tagged = [pid for pid in public if geo[pid] is not None]
    explicit_posts = [pid for pid in public
                      if any(s.get("level") == "explicit" for s in by_id[pid].get("spans") or [])]
    if level > target and tagged:
        after = risk(public, no_meta=tagged)
        solo = risk(ids, no_meta=tagged)
        # 본문에 같은 축 단서가 있으면 태그만 떼서는 안 내려가지만, 리라이트 뒤에는 태그가 그 축의 마지막 단서가 된다
        helps_rewrite = bool(explicit_posts) and (
            risk(public, no_meta=tagged, rewrite=explicit_posts) < risk(public, rewrite=explicit_posts))
        if after < level or solo < current or helps_rewrite:
            actions.append({
                "action_type": "activity_meta",
                "burden": "medium",
                "certainty": "high",
                "targets": [{"kind": "meta_field", "ref": "geo_tag"}],
                "projected_delta": _round(min(0.0, solo - current)),
                "rationale": f"공개 글 {len(tagged)}편에 붙은 위치태그를 떼기",
            })
            level = after
            meta_done = tagged
        else:
            meta_done = []
    else:
        meta_done = []

    # ③ 리라이트 — 공개 글의 명시 단서
    if level > target and explicit_posts:
        after = risk(public, no_meta=meta_done, rewrite=explicit_posts)
        solo = risk(ids, rewrite=explicit_posts)
        if after < level or solo < current:
            skeleton = any(
                _is_skeleton(by_id[pid].get("spans") or [], s)
                for pid in explicit_posts for s in by_id[pid].get("spans") or []
                if s.get("level") == "explicit"
            )
            n_spans = sum(1 for pid in explicit_posts for s in by_id[pid].get("spans") or []
                          if s.get("level") == "explicit")
            actions.append({
                "action_type": "rewrite",
                "burden": "high" if skeleton else "medium",
                "certainty": "medium",
                "targets": [{"kind": "post", "ref": pid} for pid in explicit_posts],
                "projected_delta": _round(min(0.0, solo - current)),
                "rationale": f"글 {len(explicit_posts)}편의 명시 단서 {n_spans}곳을 바꾸기 (효과는 단서를 다 고쳤을 때 기준)",
            })
            level = after

    actions.sort(key=lambda a: _BURDEN_ORDER[a["burden"]])  # 안정 정렬 — 같은 부담이면 쌓은 순서
    return {
        "actions": actions,
        "projected": {
            "current_risk": _round(current),
            "projected_risk": _round(level),
            "reduction_pct": None if current <= 0 else _round(100.0 * (current - level) / current),
            "target_met": level <= target,
        },
        "optimality_gap_pct": None,
    }
