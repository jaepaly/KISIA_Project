from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "risk_correlation_score",
    HERE / "score.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("score.py를 불러올 수 없습니다")
score = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(score)


def test_parse_bool() -> None:
    assert score.parse_bool("TRUE") is True
    assert score.parse_bool("false") is False
    with pytest.raises(ValueError):
        score.parse_bool("unknown")


def test_aggregate_windows_counts_seven_attributes() -> None:
    rows = [
        {
            "persona_id": "A01",
            "split": "report",
            "window_size": 1,
            "our_risk": 10.0,
            "attribute": attribute,
            "correct": index < 3,
            "correct_e03_current_location": index < 3,
        }
        for index, attribute in enumerate(score.ATTRS)
    ]
    result = score.aggregate_windows(rows)
    assert len(result) == 1
    assert result[0]["success_count"] == 3
    assert result[0]["success_rate"] == pytest.approx(3 / 7, abs=1e-6)


def test_correlation_is_positive() -> None:
    rows = [
        {
            "our_risk": risk,
            "success_count": success,
        }
        for risk, success in [(0, 0), (10, 1), (20, 3), (30, 5)]
    ]
    result = score.correlation(rows)
    assert result["n"] == 4
    assert result["rho"] == pytest.approx(1.0)

def test_e03_current_location_is_primary_score() -> None:
    rows = [
        {
            "persona_id": "E03",
            "split": "report",
            "window_size": 19,
            "our_risk": 35.0,
            "attribute": attribute,
            "correct": False,
            "correct_e03_current_location": attribute == "location",
        }
        for attribute in score.ATTRS
    ]

    result = score.aggregate_windows(rows)[0]

    assert result["success_count"] == 1
    assert result["success_count_e03_ground_truth_location"] == 0