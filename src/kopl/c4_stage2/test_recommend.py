"""추천 엔진 v1 규칙 검증 — 가짜 엔진(축별 최고 해상도 × 10 의 합)으로 돌린다.

실행:
    python -m pytest src/kopl/c4_stage2/test_recommend.py -v

실제 C2 와의 대조는 exp10 재현으로 한다 — 목표 0 이면 세 조치를 다 쌓으므로
누적 위험도가 exp10 cumulative.after_rewrite.explicit 과 같아야 한다 (README 참조).
"""

import pytest

from kopl.c4_stage2.recommend import recommend, unpublish_k

USER = "u_0123abcd"


def _conds(spans, post_id):
    return [{"axis": s["axis"], "resolution": s["res"]} for s in spans]


def _geo(tag, post_id):
    return {"axis": "location", "resolution": 3}


def _risk(conds):
    best: dict[str, int] = {}
    for c in conds:
        best[c["axis"]] = max(best.get(c["axis"], 0), c["resolution"])
    return float(sum(best.values()) * 10)


def _span(sid, axis, res, level="implicit", text=None, text_id="body"):
    return {"span_id": sid, "axis": axis, "res": res, "level": level, "text": text or sid, "text_id": text_id}


def _run(posts, target=0.0):
    return recommend(user_ref=USER, posts=posts, target_risk=target,
                     conditions_fn=_conds, geo_condition_fn=_geo, risk_fn=_risk)


def test_unpublish_k_matches_exp10() -> None:
    assert [unpublish_k(n) for n in (1, 2, 3, 6, 7, 19, 30)] == [0, 1, 1, 1, 1, 3, 5]


def test_three_steps_cumulative_and_solo() -> None:
    """비공개 → 메타 → 리라이트. projected 는 누적, projected_delta 는 단독."""
    posts = [
        {"post_id": "p1", "geo_tag": None, "spans": [_span("a", "age", 3, "explicit"), _span("i", "income", 2)]},
        {"post_id": "p2", "geo_tag": "x", "spans": [_span("b", "occupation", 1, "explicit")]},
        {"post_id": "p3", "geo_tag": None, "spans": [_span("c", "family", 1)]},
    ]
    out = _run(posts)
    kinds = [a["action_type"] for a in out["actions"]]
    assert kinds == ["unpublish", "activity_meta", "rewrite"]
    assert out["actions"][0]["targets"] == [{"kind": "post", "ref": "p1"}]  # 나이 30 + 소득 20 이 가장 큼
    assert out["projected"]["current_risk"] == 100.0  # 나이 30 + 소득 20 + 직업 10 + 가족 10 + 위치 30
    # 비공개 p1 → 50 · 위치태그 → 20 · p2 명시 직업 → 10
    assert out["projected"]["projected_risk"] == 10.0
    assert out["actions"][1]["projected_delta"] == -30.0  # 태그 단독
    assert out["actions"][2]["projected_delta"] == -10.0  # p2 명시 단독 (p1 은 비공개라 대상 아님)
    assert out["projected"]["reduction_pct"] == 90.0
    assert out["projected"]["target_met"] is False


def test_stops_when_target_met() -> None:
    """목표에 닿으면 다음 조치를 쌓지 않는다 — 최소 조치."""
    posts = [
        {"post_id": "p1", "geo_tag": None, "spans": [_span("a", "age", 3, "explicit"), _span("i", "income", 2)]},
        {"post_id": "p2", "geo_tag": "x", "spans": [_span("b", "occupation", 1, "explicit")]},
        {"post_id": "p3", "geo_tag": None, "spans": [_span("c", "family", 1)]},
    ]
    out = _run(posts, target=60.0)
    assert [a["action_type"] for a in out["actions"]] == ["unpublish"]
    assert out["projected"] == {"current_risk": 100.0, "projected_risk": 50.0,
                                "reduction_pct": 50.0, "target_met": True}


def test_already_below_target_has_no_actions() -> None:
    posts = [{"post_id": "p1", "geo_tag": None, "spans": [_span("a", "family", 1)]},
             {"post_id": "p2", "geo_tag": None, "spans": []}]
    out = _run(posts, target=40.0)
    assert out["actions"] == []
    assert out["projected"]["target_met"] is True


def test_meta_kept_when_it_only_helps_after_rewrite() -> None:
    """본문 명시 위치(3)와 태그(3)가 겹치면 태그만 떼선 안 내려간다 — 리라이트와 같이 해야 내려가므로 메타를 넣는다."""
    posts = [{"post_id": "p1", "geo_tag": "x", "spans": [_span("a", "location", 3, "explicit")]}]
    out = _run(posts)
    assert [a["action_type"] for a in out["actions"]] == ["activity_meta", "rewrite"]
    assert out["actions"][0]["projected_delta"] == 0.0
    assert out["projected"]["projected_risk"] == 0.0


def test_single_post_is_never_unpublished() -> None:
    posts = [{"post_id": "p1", "geo_tag": None, "spans": [_span("a", "age", 3, "explicit")]}]
    out = _run(posts)
    assert [a["action_type"] for a in out["actions"]] == ["rewrite"]


def test_skeleton_expression_is_high_burden() -> None:
    """제목과 본문에 같은 명시 표현 — 계약 Action.burden 뼈대 규칙."""
    posts = [{"post_id": "p1", "geo_tag": None, "spans": [
        _span("a", "location", 2, "explicit", text="X동", text_id="title"),
        _span("b", "location", 2, "explicit", text="X동", text_id="body"),
    ]}]
    out = _run(posts)
    assert out["actions"][0]["burden"] == "high"


def test_burden_sorted_and_contract_shape() -> None:
    posts = [
        {"post_id": "p1", "geo_tag": "x", "spans": [_span("a", "age", 3, "explicit")]},
        {"post_id": "p2", "geo_tag": "y", "spans": [_span("b", "income", 2, "explicit")]},
    ]
    out = _run(posts)
    order = {"low": 0, "medium": 1, "high": 2}
    burdens = [order[a["burden"]] for a in out["actions"]]
    assert burdens == sorted(burdens)
    for a in out["actions"]:
        assert set(a) == {"action_type", "burden", "certainty", "targets", "projected_delta", "rationale"}
        assert a["projected_delta"] <= 0
        assert len(a["rationale"]) <= 300
    assert out["optimality_gap_pct"] is None


def test_input_validation() -> None:
    with pytest.raises(ValueError):
        _run([])
    with pytest.raises(ValueError):
        _run([{"post_id": "p1", "spans": []}, {"post_id": "p1", "spans": []}])
    with pytest.raises(ValueError):
        _run([{"post_id": "p1", "spans": []}], target=120.0)


def test_real_c2_output_matches_contract() -> None:
    """실제 C2 로 낸 출력이 stage2-io.schema.json 의 recommendation 을 통과한다."""
    import json
    from pathlib import Path

    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((Path(__file__).resolve().parents[3] / "docs/contracts/stage2-io.schema.json")
                        .read_text(encoding="utf-8"))
    sub = {"$defs": schema["$defs"], **schema["$defs"]["Stage2Output"]["properties"]["recommendation"]}
    posts = [
        {"post_id": "p1", "geo_tag": "강남구", "spans": [
            {"span_id": "p1_s01", "text_id": "body", "text": "마흔여덟", "type": "AGE",
             "level": "explicit", "subject": "self", "start": 0, "end": 4}]},
        {"post_id": "p2", "geo_tag": None, "spans": [
            {"span_id": "p2_s01", "text_id": "body", "text": "간호사", "type": "JOB",
             "level": "explicit", "subject": "self", "start": 0, "end": 3}]},
    ]
    out = recommend(user_ref=USER, posts=posts, target_risk=0.0)
    jsonschema.validate(out, sub)
    assert out["projected"]["current_risk"] > out["projected"]["projected_risk"]


def test_target_stop_uses_unrounded_risk() -> None:
    """greedy_path.risk_after 는 반올림값 — 목표 경계에서 비공개를 일찍 멈추면 안 된다 (Codex 반례)."""
    third = lambda conds: _risk(conds) / 3
    posts = [{"post_id": f"p{i:02d}", "geo_tag": None, "spans": []} for i in range(13)]  # k = 2
    posts[0]["spans"] = [_span("a", "age", 3)]
    posts[1]["spans"] = [_span("b", "family", 2)]
    posts[2]["spans"] = [_span("c", "occupation", 2)]
    out = recommend(user_ref=USER, posts=posts, target_risk=13.33,
                    conditions_fn=_conds, geo_condition_fn=_geo, risk_fn=third)
    # 첫 제거 후 40/3 = 13.333… — 반올림 13.33 은 목표 이하지만 원값은 목표 초과라 한 편 더 내린다 (20/3)
    assert len(out["actions"][0]["targets"]) == 2
    assert out["projected"]["target_met"] is True
