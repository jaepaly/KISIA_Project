import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("score.py")
SPEC = importlib.util.spec_from_file_location("contribution_approx_score", MODULE_PATH)
assert SPEC and SPEC.loader
score = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(score)


def rows(values: dict[str, float]) -> list[dict]:
    ordered = sorted(values.items(), key=lambda item: (-abs(item[1]), item[0]))
    return [{"post_id": pid, "delta": delta, "rank": rank} for rank, (pid, delta) in enumerate(ordered, 1)]


def write_gold(path: Path, baseline: float, values: dict[str, float], *, method: str = "loo") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    contribution_rows = rows(values)
    path.write_text(json.dumps({
        "input": {"method": method, "post_ids": sorted(values)},
        "output": {"baseline_risk": baseline, "contributions": contribution_rows},
    }), encoding="utf-8")


def write_prediction(path: Path, values: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows(values)), encoding="utf-8")


def test_evaluate_abs_delta_ties_and_excludes_zero_baseline(tmp_path: Path) -> None:
    gold, predictions = tmp_path / "gold", tmp_path / "predictions"
    write_gold(gold / "A01.json", 20.0, {"p1": -3, "p2": -2, "p3": -1, "p4": 0, "p5": 0})
    write_prediction(predictions / "A01.json", {"p1": -3, "p2": -2, "p3": -1, "p4": -0.2, "p5": -0.1})
    write_gold(gold / "A02.json", 0.0, {"z1": 0, "z2": 0})

    result = score.evaluate(gold, predictions)

    assert result["n_personas"] == 1
    assert result["excluded_zero_baseline"] == ["A02"]
    assert result["macro_spearman_rho_abs_delta"] > 0.8
    assert result["macro_top3_rank_agreement"] == 1.0
    assert result["target_spearman_ge_0_8"] is True


def test_gold_constant_is_separate_and_prediction_constant_is_failure(tmp_path: Path) -> None:
    gold, predictions = tmp_path / "gold", tmp_path / "predictions"
    write_gold(gold / "A01.json", 10.0, {"p1": -2, "p2": -1})
    write_prediction(predictions / "A01.json", {"p1": 0, "p2": 0})
    write_gold(gold / "A02.json", 10.0, {"z1": 0, "z2": 0})
    write_prediction(predictions / "A02.json", {"z1": 0, "z2": 0})

    result = score.evaluate(gold, predictions)

    assert result["n_personas_for_spearman"] == 1
    assert result["n_personas_gold_constant"] == 1
    assert result["n_personas_prediction_constant_failure"] == 1
    assert result["macro_spearman_rho_abs_delta"] == 0.0


def test_top3_reports_contract_and_tie_aware_scores(tmp_path: Path) -> None:
    gold, predictions = tmp_path / "gold", tmp_path / "predictions"
    write_gold(gold / "A01.json", 10.0, {"p1": -3, "p2": -2, "p3": -1, "p4": -1})
    write_prediction(predictions / "A01.json", {"p1": -3, "p2": -2, "p3": -0.9, "p4": -1.0})

    person = score.evaluate(gold, predictions)["people"][0]

    assert person["top3_rank_agreement"] == pytest.approx(2 / 3)
    assert person["top3_tie_aware_recall"] == 1.0


@pytest.mark.parametrize("bad_delta", ["1", None, float("inf"), True])
def test_prediction_delta_must_be_finite_number(tmp_path: Path, bad_delta) -> None:
    path = tmp_path / "A01.json"
    path.write_text(json.dumps([{"post_id": "p1", "delta": bad_delta, "rank": 1}]), encoding="utf-8")
    with pytest.raises(ValueError, match="delta는 유한한 숫자"):
        score.load_prediction(path)


@pytest.mark.parametrize("bad_rank", [1.9, "1", True])
def test_prediction_rank_must_be_integer(tmp_path: Path, bad_rank) -> None:
    path = tmp_path / "A01.json"
    path.write_text(json.dumps([{"post_id": "p1", "delta": -1.0, "rank": bad_rank}]), encoding="utf-8")
    with pytest.raises(ValueError, match="rank는 정수"):
        score.load_prediction(path)


def test_prediction_rejects_rank_delta_disagreement(tmp_path: Path) -> None:
    path = tmp_path / "A01.json"
    path.write_text(json.dumps([
        {"post_id": "p1", "delta": -1.0, "rank": 1},
        {"post_id": "p2", "delta": -2.0, "rank": 2},
    ]), encoding="utf-8")
    with pytest.raises(ValueError, match=r"rank가 abs\(delta\)"):
        score.load_prediction(path)


def test_gold_requires_loo_and_matching_post_ids(tmp_path: Path) -> None:
    path = tmp_path / "A01.json"
    write_gold(path, 10.0, {"p1": -1}, method="approx")
    with pytest.raises(ValueError, match="input.method는 loo"):
        score.load_gold(path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["input"] = {"method": "loo", "post_ids": ["other"]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="input.post_ids와 contributions"):
        score.load_gold(path)


def test_evaluate_rejects_post_id_mismatch(tmp_path: Path) -> None:
    gold, predictions = tmp_path / "gold", tmp_path / "predictions"
    write_gold(gold / "A01.json", 10.0, {"p1": -2, "p2": -1})
    write_prediction(predictions / "A01.json", {"p1": -2, "other": -1})
    with pytest.raises(ValueError, match="post_id 불일치"):
        score.evaluate(gold, predictions)


def test_sign_accuracy_and_signed_delta_mae(tmp_path: Path) -> None:
    gold, predictions = tmp_path / "gold", tmp_path / "predictions"
    write_gold(gold / "A01.json", 10.0, {"p1": -2, "p2": -1})
    write_prediction(predictions / "A01.json", {"p1": 2, "p2": -0.5})

    person = score.evaluate(gold, predictions)["people"][0]

    assert person["sign_accuracy"] == 0.5
    assert person["signed_delta_mae"] == pytest.approx(2.25)
