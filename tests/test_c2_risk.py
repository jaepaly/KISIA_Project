"""C2 7축 위험도 계산 계약 검증."""

import pytest

from kopl.c2_specificity import risk_by_axis, risk_total


def condition(axis: str, resolution: int) -> dict[str, object]:
    return {
        "axis": axis,
        "kind": "test",
        "value": "fixture",
        "resolution": resolution,
        "confidence": 1.0,
        "source_post_ids": ["p1"],
    }


def test_empty_conditions_have_zero_risk() -> None:
    assert risk_total([]) == 0.0
    assert risk_by_axis([]) == {
        "location": 0.0,
        "age": 0.0,
        "sex": 0.0,
        "occupation": 0.0,
        "family": 0.0,
        "commute": 0.0,
        "income": 0.0,
    }


def test_risk_total_uses_seven_axis_weighted_average() -> None:
    conditions = [
        condition("location", 4),
        condition("age", 3),
    ]

    scores = risk_by_axis(conditions)
    assert scores["location"] == 100.0
    assert scores["age"] == 100.0
    assert risk_total(conditions) == pytest.approx(200.0 / 7.0)


def test_same_axis_uses_narrowest_resolution_once() -> None:
    conditions = [
        condition("occupation", 1),
        condition("occupation", 3),
        condition("occupation", 2),
    ]

    assert risk_by_axis(conditions)["occupation"] == 100.0
    assert risk_total(conditions) == pytest.approx(100.0 / 7.0)


def test_all_axis_maximum_is_bounded() -> None:
    conditions = [
        condition("location", 4),
        condition("age", 3),
        condition("sex", 1),
        condition("occupation", 3),
        condition("family", 3),
        condition("commute", 2),
        condition("income", 1),
    ]

    assert risk_total(conditions) == pytest.approx(
        (100.0 + 100.0 + 60.0 + 100.0 + 85.0 + 75.0 + 50.0) / 7.0
    )
    assert 0.0 <= risk_total(conditions) <= 100.0


@pytest.mark.parametrize(
    ("conditions", "error", "message"),
    [
        ([condition("unknown", 1)], ValueError, "axis"),
        ([condition("sex", 2)], ValueError, "resolution"),
        ([condition("age", True)], TypeError, "정수"),
        ([{"axis": "age"}], TypeError, "정수"),
        (["not-an-object"], TypeError, "객체"),
        ("not-a-sequence-of-conditions", TypeError, "시퀀스"),
    ],
)
def test_invalid_conditions_are_rejected(conditions, error, message) -> None:
    with pytest.raises(error, match=message):
        risk_total(conditions)
