"""C3 LOO 기여도 엔진 계약 검증."""

import pytest

from kopl.c3_contribution import leave_one_out


def weighted_risk(weights):
    return lambda ids: min(100.0, sum(weights[post_id] for post_id in ids))


def test_loo_delta_rank_and_evidence() -> None:
    result = leave_one_out(
        user_ref="u_deadbeef",
        post_ids=["p2", "p1", "p3"],
        risk_fn=weighted_risk({"p1": 10.0, "p2": 30.0, "p3": 5.0}),
        clue_index={"p2": ["p2#0"]},
        span_index={"p2": [{"span_id": "p2_s01", "text_id": "body"}]},
    )
    assert result["output"]["baseline_risk"] == 45.0
    rows = result["output"]["contributions"]
    assert [row["post_id"] for row in rows] == ["p2", "p1", "p3"]
    assert [row["delta"] for row in rows] == [-30.0, -10.0, -5.0]
    assert rows[0]["clue_ids"] == ["p2#0"]
    assert rows[0]["top_spans"] == [{"span_id": "p2_s01", "text_id": "body"}]


def test_order_independent_and_tie_break_by_post_id() -> None:
    risk = weighted_risk({"a": 10.0, "b": 10.0})
    a = leave_one_out(user_ref="u_deadbeef", post_ids=["b", "a"], risk_fn=risk)
    b = leave_one_out(user_ref="u_deadbeef", post_ids=["a", "b"], risk_fn=risk)
    assert a == b
    assert [row["post_id"] for row in a["output"]["contributions"]] == ["a", "b"]


def test_removed_posts_risk_after() -> None:
    result = leave_one_out(
        user_ref="u_deadbeef",
        post_ids=["p1", "p2"],
        risk_fn=weighted_risk({"p1": 20.0, "p2": 30.0}),
        removed_post_ids=["p2"],
    )
    assert result["input"]["removed_post_ids"] == ["p2"]
    assert result["output"]["risk_after"] == 20.0


def test_residual_risk_is_floor() -> None:
    result = leave_one_out(
        user_ref="u_deadbeef",
        post_ids=["p1"],
        risk_fn=lambda ids: 10.0 if ids else 0.0,
        residual_risk=7.0,
        user_scoped=[
            {
                "source": "profile_bio",
                "delta": -7.0,
                "top_spans": [
                    {"span_id": "bio_s01", "text_id": "profile_bio"}
                ],
            }
        ],
    )
    row = result["output"]["contributions"][0]
    assert row["risk_without"] == 7.0
    assert row["delta"] == -3.0
    assert result["output"]["greedy_path"] == [
        {"remove": "p1", "risk_after": 7.0}
    ]


def test_greedy_recomputes_interactions() -> None:
    def risk(ids):
        values = {
            (): 0.0,
            ("a",): 20.0,
            ("b",): 15.0,
            ("c",): 10.0,
            ("a", "b"): 50.0,
            ("a", "c"): 40.0,
            ("b", "c"): 30.0,
            ("a", "b", "c"): 90.0,
        }
        return values[ids]

    result = leave_one_out(
        user_ref="u_deadbeef", post_ids=["a", "b", "c"], risk_fn=risk
    )
    assert result["output"]["greedy_path"] == [
        {"remove": "a", "risk_after": 30.0},
        {"remove": "b", "risk_after": 10.0},
        {"remove": "c", "risk_after": 0.0},
    ]


def test_greedy_stops_when_removal_does_not_improve() -> None:
    result = leave_one_out(
        user_ref="u_deadbeef",
        post_ids=["p1", "p2"],
        risk_fn=lambda ids: 25.0,
    )
    assert result["output"]["greedy_path"] == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"user_ref": "raw-user"}, "user_ref"),
        ({"post_ids": []}, "한 개 이상"),
        ({"post_ids": ["p1", "p1"]}, "중복"),
        ({"removed_post_ids": ["missing"]}, "부분집합"),
        ({"residual_risk": 1.0}, "user_scoped"),
    ],
)
def test_invalid_inputs(kwargs, message) -> None:
    base = {
        "user_ref": "u_deadbeef",
        "post_ids": ["p1"],
        "risk_fn": lambda ids: 10.0,
    }
    base.update(kwargs)
    with pytest.raises(ValueError, match=message):
        leave_one_out(**base)


@pytest.mark.parametrize("bad", [-1.0, 101.0, float("nan"), float("inf")])
def test_invalid_risk_result_rejected(bad) -> None:
    with pytest.raises(ValueError, match="0~100"):
        leave_one_out(
            user_ref="u_deadbeef",
            post_ids=["p1"],
            risk_fn=lambda ids: bad,
        )
