from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PATH = Path(__file__).with_name("run.py")
SPEC = importlib.util.spec_from_file_location(
    "risk_correlation_run",
    RUN_PATH,
)

assert SPEC is not None
assert SPEC.loader is not None

run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run)


def test_build_windows_uses_expected_sizes(
    monkeypatch,
) -> None:
    posts = [
        {
            "post_id": f"T01_b{i:02d}",
            "created_at": (
                f"2026-01-{i:02d}T00:00:00+09:00"
            ),
        }
        for i in range(1, 20)
    ]

    monkeypatch.setattr(
        run,
        "load_posts",
        lambda _persona_id: posts,
    )
    monkeypatch.setattr(
        run,
        "load_gold_spans",
        lambda _persona_id: {},
    )
    monkeypatch.setattr(
        run,
        "risk_for_posts",
        lambda post_ids, _spans: float(len(post_ids)),
    )

    rows = run.build_windows("T01")

    assert [
        row["window_size"]
        for row in rows
    ] == list(run.WINDOWS)

    assert [
        row["our_risk"]
        for row in rows
    ] == [
        1.0,
        2.0,
        3.0,
        5.0,
        8.0,
        12.0,
        19.0,
    ]

    assert all(
        row["llm_correct"] is None
        for row in rows
    )


def test_persona_sample_and_split_are_fixed() -> None:
    assert run.PERSONAS == (
        "B08",
        "D03",
        "E14",
        "B15",
        "D21",
        "A14",
        "E03",
        "B06",
        "B07",
        "A10",
    )

    assert run.PERSONAS[:5] == (
        "B08",
        "D03",
        "E14",
        "B15",
        "D21",
    )

    assert run.PERSONAS[5:] == (
        "A14",
        "E03",
        "B06",
        "B07",
        "A10",
    )


def test_risk_for_posts_uses_only_selected_posts(
    monkeypatch,
) -> None:
    spans_by_post = {
        "T01_b01": [{"span_id": "s01"}],
        "T01_b02": [{"span_id": "s02"}],
    }
    calls: list[str] = []

    def fake_build_conditions(
        spans,
        post_id,
    ):
        calls.append(post_id)
        return [
            {
                "axis": "age",
                "resolution": len(spans),
            }
        ]

    monkeypatch.setattr(
        run,
        "build_conditions",
        fake_build_conditions,
    )
    monkeypatch.setattr(
        run,
        "risk_total",
        lambda conditions: float(len(conditions)),
    )

    result = run.risk_for_posts(
        ["T01_b02"],
        spans_by_post,
    )

    assert result == 1.0
    assert calls == ["T01_b02"]