"""최적해(축별 상한 열거)가 단순 전수 탐색과 같은 답을 내는지 — README §3 「정확성 확인」."""
import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("exp26_gap", HERE / "gap.py")
gap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gap)

AX = gap.AXES


def vec(**kw):
    return {a: float(kw.get(a, 0.0)) for a in AX}


def st(pid, orig, rew=None, geo=None):
    return {"post_id": pid, "orig": orig, "rew": rew if rew is not None else orig, "explicit": rew is not None, "geo": geo}


def same(a, b):
    if a is None or b is None:
        return a is None and b is None
    return a[0] == b[0] and abs(a[1] - b[1]) < 1e-9


SYNTH = [
    # REL_WORK 처럼 명시를 지우면 다른 축(commute)도 같이 내려가는 글
    [st("a", vec(location=85, commute=75, age=100), rew=vec(location=20)), st("b", vec(sex=60, family=55)),
     st("c", vec(occupation=100), rew=vec(occupation=40)), st("d", vec(income=50))],
    # 위치태그만 위치 단서인 글 · 태그가 여러 글에
    [st("a", vec(age=100, sex=60), rew=vec(sex=60), geo=vec(location=55)), st("b", vec(family=85), geo=vec(location=55)),
     st("c", vec(occupation=70, commute=40)), st("d", vec(income=50, age=70), rew=vec(income=50))],
    # 비공개 k 경계 — 리라이트로는 안 내려가는 글이 k 보다 많다
    [st(p, vec(location=100, age=100, occupation=100, family=85)) for p in "abcdefg"],
]


@pytest.mark.parametrize("states", SYNTH)
@pytest.mark.parametrize("w", list(gap.WEIGHTS.values()))
def test_optimum_equals_brute_force_synthetic(states, w) -> None:
    k = gap.unpublish_k(len(states))
    for target in (10.0, 20.0, 30.0, 40.0):
        assert same(gap.optimum(states, k, w, target), gap.brute_force(states, k, w, target)), (target, w)


def test_optimum_equals_brute_force_on_sub_histories() -> None:
    accounts = gap.load_accounts()
    picked = sorted(accounts, key=lambda a: a["persona_id"])[:10]
    checked = 0
    for acc in picked:
        states = [gap.post_state(p) for p in acc["posts"][:7]]  # post_id 순 앞 7편
        k = gap.unpublish_k(len(states))
        for w in gap.WEIGHTS.values():
            for target in (20.0, 30.0, 40.0):
                assert same(gap.optimum(states, k, w, target), gap.brute_force(states, k, w, target)), (acc["persona_id"], w, target)
                checked += 1
    assert checked == 90


def test_account_risk_matches_recommend_engine() -> None:
    acc = sorted(gap.load_accounts(), key=lambda a: a["persona_id"])[0]
    states = [gap.post_state(p) for p in acc["posts"]]
    assert abs(gap.run_recommend(acc)["projected"]["current_risk"] - round(gap.account_risk(states), 2)) <= 0.011
