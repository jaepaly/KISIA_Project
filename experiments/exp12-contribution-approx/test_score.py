import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("score.py")
SPEC = importlib.util.spec_from_file_location("contribution_approx_score", MODULE_PATH)
assert SPEC and SPEC.loader
score = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(score)


def write_gold(path: Path, baseline: float, order: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"post_id": post_id, "delta": -float(len(order) - rank + 1), "rank": rank}
        for rank, post_id in enumerate(order, 1)
    ]
    path.write_text(
        json.dumps({"output": {"baseline_risk": baseline, "contributions": rows}}),
        encoding="utf-8",
    )


def write_prediction(path: Path, order: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"post_id": post_id, "delta": -float(len(order) - rank + 1), "rank": rank}
        for rank, post_id in enumerate(order, 1)
    ]
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_evaluate_perturbed_predictions_and_excludes_zero_baseline(tmp_path: Path) -> None:
    gold = tmp_path / "gold"
    predictions = tmp_path / "predictions"
    write_gold(gold / "A01.json", 20.0, ["p1", "p2", "p3", "p4"])
    write_prediction(predictions / "A01.json", ["p1", "p3", "p2", "p4"])
    write_gold(gold / "A02.json", 0.0, ["z1", "z2"])

    result = score.evaluate(gold, predictions)

    assert result["n_personas"] == 1
    assert result["excluded_zero_baseline"] == ["A02"]
    assert result["macro_spearman_rho"] == pytest.approx(0.8)
    assert result["macro_top3_agreement"] == 1.0
    assert result["target_spearman_ge_0_8"] is True


def test_top3_agreement_uses_available_posts_for_small_persona(tmp_path: Path) -> None:
    gold = tmp_path / "gold"
    predictions = tmp_path / "predictions"
    write_gold(gold / "A01.json", 10.0, ["p1", "p2"])
    write_prediction(predictions / "A01.json", ["p2", "p1"])

    result = score.evaluate(gold, predictions)

    assert result["macro_top3_agreement"] == 1.0
    assert result["macro_spearman_rho"] == pytest.approx(-1.0)


def test_evaluate_rejects_post_id_mismatch(tmp_path: Path) -> None:
    gold = tmp_path / "gold"
    predictions = tmp_path / "predictions"
    write_gold(gold / "A01.json", 10.0, ["p1", "p2"])
    write_prediction(predictions / "A01.json", ["p1", "other"])

    with pytest.raises(ValueError, match="post_id 불일치"):
        score.evaluate(gold, predictions)


def test_prediction_rank_must_be_complete(tmp_path: Path) -> None:
    path = tmp_path / "A01.json"
    path.write_text(
        json.dumps([
            {"post_id": "p1", "delta": -2.0, "rank": 1},
            {"post_id": "p2", "delta": -1.0, "rank": 3},
        ]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="rank는 1부터"):
        score.load_prediction(path)
