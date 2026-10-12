from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "risk_correlation_sensitivity",
    HERE / "sensitivity.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("sensitivity.py를 불러올 수 없습니다")
sensitivity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sensitivity)


def test_candidates_to_spans_restores_text_and_attributes() -> None:
    post = {"texts": {"body": "오늘은 강남역으로 출근한다"}}

    spans = sensitivity.candidates_to_spans(
        "T01_b01",
        post,
        [
            {
                "text_id": "body",
                "start": 4,
                "end": 7,
                "type": "LOC_FACILITY",
            }
        ],
        resolver=lambda _texts, candidate: {
            "level": "explicit" if candidate["text"] == "강남역" else "implicit",
            "subject": "self",
        },
    )

    assert spans == [
        {
            "text_id": "body",
            "start": 4,
            "end": 7,
            "type": "LOC_FACILITY",
            "text": "강남역",
            "span_id": "T01_b01_pred_001",
            "level": "explicit",
            "subject": "self",
        }
    ]


def test_candidates_to_spans_rejects_bad_offset() -> None:
    with pytest.raises(ValueError, match="오프셋"):
        sensitivity.candidates_to_spans(
            "T01_b01",
            {"texts": {"body": "짧은 글"}},
            [
                {
                    "text_id": "body",
                    "start": 0,
                    "end": 99,
                    "type": "JOB",
                }
            ],
        )


def test_load_predictions_requires_exact_post_set(tmp_path: Path) -> None:
    path = tmp_path / "pred.jsonl"
    path.write_text(
        '{"post_id":"p1","candidates":[]}\n',
        encoding="utf-8",
    )
    assert sensitivity.load_predictions(path, ["p1"]) == {"p1": []}
    with pytest.raises(ValueError, match="글 집합 불일치"):
        sensitivity.load_predictions(path, ["p1", "p2"])


def test_replace_risks_preserves_rows(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    destination = tmp_path / "result.csv"
    with source.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "persona_id", "window_size", "our_risk", "attribute"
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "persona_id": "B08",
                "window_size": 1,
                "our_risk": 99,
                "attribute": "age",
            }
        )

    sensitivity.replace_risks(
        source, destination, {("B08", 1): 12.34}
    )

    with destination.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["our_risk"] == "12.34"
    assert rows[0]["attribute"] == "age"


def _windows(trajectories: dict[str, list[float]], scores: dict[str, list[float]]) -> list[dict]:
    return [{"persona_id": p, "window_size": w, "our_risk": r, "success_count": scores[p][i]}
            for p, rs in trajectories.items() for i, (w, r) in enumerate(zip((1, 2, 3), rs))]


def test_person_block_permutation_moves_whole_trajectory() -> None:
    """인물마다 위험도 수준이 성공과 맞으면 작은 p · 인물 순서와 무관하면 큰 p. 한 인물의 윈도우는 함께 움직인다."""
    personas = [f"P{i}" for i in range(8)]
    aligned = sensitivity.person_block_permutation(
        _windows({p: [i, i + 0.1, i + 0.2] for i, p in enumerate(personas)},
                 {p: [i, i, i] for i, p in enumerate(personas)}), repetitions=999, seed=1)
    assert aligned["p_one_sided"] < 0.01 and aligned["personas"] == 8
    # 위험도 궤적이 모든 인물에서 같으면 인물을 바꿔도 통계량이 같다 → p = 1
    flat = sensitivity.person_block_permutation(
        _windows({p: [1.0, 2.0, 3.0] for p in personas}, {p: [i, i + 1, i + 2] for i, p in enumerate(personas)}),
        repetitions=199, seed=1)
    assert flat["p_one_sided"] == 1.0


def test_person_block_permutation_rejects_missing_cells() -> None:
    rows = _windows({"A": [1.0, 2.0, 3.0], "B": [1.0, 2.0, 3.0]}, {"A": [1, 2, 3], "B": [1, 2, 3]})
    with pytest.raises(ValueError):
        sensitivity.person_block_permutation(rows[:-1])
