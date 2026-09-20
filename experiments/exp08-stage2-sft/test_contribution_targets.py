"""contribution_targets 회귀 — 픽스처는 loo.leave_one_out() 이 만든 계약 준수 문서."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src"))

from contribution_targets import (  # noqa: E402
    approximator_targets,
    load_contribution,
    post_deltas,
    recommendation_from_contribution,
    validate_contribution,
)

FIXTURE = HERE / "fixtures" / "contribution_A01.json"


@pytest.fixture
def doc() -> dict:
    return load_contribution(FIXTURE)


def test_fixture_matches_loo_output(doc: dict) -> None:
    """픽스처가 loo.py 출력과 같은지 — 계약이 바뀌면 여기서 먼저 깨진다."""
    from kopl.c3_contribution.loo import leave_one_out

    w = {"A01_b01": 40.0, "A01_b02": 25.0, "A01_b03": 20.0, "A01_b04": 5.0, "A01_b05": 0.0}
    spans = {p: [{"span_id": f"{p}_s01", "text_id": "body"}] for p in w if w[p] > 0}
    rebuilt = leave_one_out(
        user_ref=doc["input"]["user_ref"], post_ids=list(w),
        risk_fn=lambda ids: min(100.0, sum(w[i] for i in ids)),
        clue_index={p: [s["span_id"] for s in ss] for p, ss in spans.items()},
        span_index=spans,
    )
    assert rebuilt == doc


def test_post_deltas_are_non_positive(doc: dict) -> None:
    d = post_deltas(doc)
    assert set(d) == set(doc["input"]["post_ids"])
    assert all(v <= 0 for v in d.values())
    assert d["A01_b01"] == -40.0 and d["A01_b05"] == 0.0


def test_approximator_targets_follow_rank(doc: dict) -> None:
    t = approximator_targets(doc)
    assert [x["rank"] for x in t] == [1, 2, 3, 4, 5]
    assert t[0]["post_id"] == "A01_b01"


def test_recommendation_follows_greedy_path(doc: dict) -> None:
    rec = recommendation_from_contribution(doc, max_actions=3)
    refs = [a["targets"][0]["ref"] for a in rec["actions"]]
    assert refs == ["A01_b01", "A01_b02", "A01_b03"]
    assert [a["projected_delta"] for a in rec["actions"]] == [-40.0, -25.0, -20.0]
    assert rec["projected"] == {
        "current_risk": 90.0, "projected_risk": 5.0, "reduction_pct": 94.4, "target_met": False,
    }
    assert all(a["action_type"] == "unpublish" and a["burden"] == "low" for a in rec["actions"])


def test_recommendation_user_scoped_becomes_meta_action(doc: dict) -> None:
    d = copy.deepcopy(doc)
    d["output"]["residual_risk"] = 10.0
    d["output"]["user_scoped"] = [{"source": "profile_bio", "delta": 10.0, "top_spans": []}]
    rec = recommendation_from_contribution(d, max_actions=1)
    assert rec["actions"][-1]["targets"] == [{"kind": "profile", "ref": "profile_bio"}]
    assert rec["actions"][-1]["action_type"] == "activity_meta"
    assert rec["actions"][-1]["projected_delta"] == -10.0
    # b01 내리면 50 → 프로필 조치 -10 → 40. 남은 몫 10 도 프로필 조치로 0 이 되지만 40 > 0 이라 미도달
    assert rec["projected"]["projected_risk"] == 40.0
    assert rec["projected"]["target_met"] is False


def test_projected_delta_is_standalone_not_greedy_marginal() -> None:
    """조치끼리 상호작용하면 greedy 한계효과 ≠ 단독 LOO delta. 계약(Action.projected_delta = 단독)을 따른다."""
    from kopl.c3_contribution.loo import leave_one_out

    w = {"X_b01": 60.0, "X_b02": 50.0, "X_b03": 20.0}
    d = leave_one_out(user_ref="u_0123456789ab", post_ids=list(w),
                      risk_fn=lambda ids: min(100.0, sum(w[i] for i in ids)))
    validate_contribution(d)
    assert d["output"]["baseline_risk"] == 100.0                      # 상한에 걸려 있다
    assert {r["post_id"]: r["delta"] for r in d["output"]["contributions"]} == \
        {"X_b01": -30.0, "X_b02": -20.0, "X_b03": 0.0}
    rec = recommendation_from_contribution(d, max_actions=2)
    steps = [(a["targets"][0]["ref"], a["projected_delta"]) for a in rec["actions"]]
    assert steps[0] == ("X_b01", -30.0)
    assert steps[1] == ("X_b02", -20.0)           # greedy 한계효과는 -50 이지만 단독 효과 -20 을 쓴다
    assert rec["projected"]["projected_risk"] == 20.0   # 누적은 projected_risk 가 들고 간다 (100→70→20)


def test_recommendation_validator_rejects_bad_action(doc: dict) -> None:
    from contribution_targets import _recommendation_validator

    rec = recommendation_from_contribution(doc)
    bad = copy.deepcopy(rec)
    bad["actions"][0]["projected_delta"] = 5.0          # 양수 금지
    assert list(_recommendation_validator().iter_errors(bad))
    bad = copy.deepcopy(rec)
    bad["actions"][0]["targets"][0]["kind"] = "comment"  # enum 밖
    assert list(_recommendation_validator().iter_errors(bad))
    assert not list(_recommendation_validator().iter_errors(rec))


def test_invariants_reject_broken_rank(doc: dict) -> None:
    d = copy.deepcopy(doc)
    d["output"]["contributions"][0]["rank"], d["output"]["contributions"][1]["rank"] = 2, 1
    with pytest.raises(ValueError, match=r"\(6\)"):
        validate_contribution(d)


def test_invariants_reject_missing_post(doc: dict) -> None:
    d = copy.deepcopy(doc)
    d["output"]["contributions"].pop()
    with pytest.raises(ValueError, match=r"\(5\)"):
        validate_contribution(d)


def test_schema_violation_is_reported(doc: dict) -> None:
    d = copy.deepcopy(doc)
    d["output"]["baseline_risk"] = 120.0
    with pytest.raises(ValueError, match="계약 위반"):
        validate_contribution(d)


def test_fixture_is_valid_json_on_disk() -> None:
    json.loads(FIXTURE.read_text(encoding="utf-8"))
