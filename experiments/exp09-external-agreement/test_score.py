"""score.py 통계 함수 회귀 — 손으로 계산한 값과 대조."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from score import INVALID, agreement, binary, gwet_ac1, kappa, macro_f1, mcc_multi, mcnemar, verdicts  # noqa: E402


def test_invalid_counts_as_disagreement() -> None:
    assert agreement([("abstain", "abstain"), (INVALID, INVALID)]) == 0.5


def test_kappa_perfect_and_chance() -> None:
    assert kappa([("abstain", "abstain"), ("narrowed", "narrowed")]) == 1.0
    # po 0.5 · pe = (1·1 + 1·1)/4 = 0.5 → κ 0
    assert kappa([("abstain", "abstain"), ("narrowed", "abstain"), ("abstain", "narrowed"), ("narrowed", "narrowed")]) == 0.0


def test_kappa_ignores_invalid_pairs() -> None:
    assert kappa([("abstain", "abstain"), ("narrowed", "narrowed"), (INVALID, "abstain")]) == 1.0


def test_ac1_is_higher_than_kappa_under_abstain_majority() -> None:
    pairs = [("abstain", "abstain")] * 18 + [("narrowed", "abstain"), ("abstain", "narrowed")]
    assert gwet_ac1(pairs) > kappa(pairs)


def test_mcc_and_macro_f1_perfect() -> None:
    ref = ["abstain", "narrowed", "specified", "weak_signal"]
    assert mcc_multi(ref, ref) == pytest.approx(1.0)
    assert macro_f1(ref, ref) == 1.0


def test_binary_invalid_on_negative_is_false_positive() -> None:
    b = binary(["abstain", "narrowed"], [INVALID, "narrowed"])
    assert (b["tp"], b["fp"], b["tn"], b["fn"]) == (1, 1, 0, 0)


def test_mcnemar_exact() -> None:
    ref = ["a"] * 4
    r = mcnemar(ref, ["a"] * 4, ["b"] * 4)          # a 만 4번 맞힘 → p = 2·(1/16)
    assert r == {"a_only_correct": 4, "b_only_correct": 0, "p": 0.125}


def test_verdicts_marks_missing_and_unknown_as_invalid() -> None:
    v = verdicts({"findings": {"age": {"verdict": "narrowed"}, "sex": {"verdict": "maybe"}}})
    assert v["age"] == "narrowed" and v["sex"] == INVALID and v["income"] == INVALID
    assert set(verdicts(None).values()) == {INVALID}
