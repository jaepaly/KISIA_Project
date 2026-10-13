"""닫힌 식 = 실제 LOO — 정답 파일이 아니라 지금 엔진으로 LOO 를 그 자리에서 돌려 비교한다 (정답이 낡아도 잡히게)."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("closed_form", HERE / "closed_form.py")
cf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cf)

from gen_contribution_targets import generate_target, load_spans  # noqa: E402  (closed_form 이 scripts 를 경로에 넣는다)


def test_closed_form_equals_live_loo_for_every_persona() -> None:
    test = cf.test_post_ids()
    checked = 0
    for path in sorted(cf.TARGETS.glob("*.json")):
        spans = {pid: s for pid, s in load_spans(cf.GOLD, path.stem).items() if pid not in test}
        loo = {r["post_id"]: r["delta"] for r in generate_target(path.stem, spans)["output"]["contributions"]}
        closed = cf.closed_form_deltas(spans)
        assert closed.keys() == loo.keys()
        for pid in loo:  # loo.py 의 반올림 방식과 무관하게 0.01 이내
            assert abs(closed[pid] - loo[pid]) <= 0.0100001, (pid, closed[pid], loo[pid])
        checked += len(loo)
    assert checked == 331


def test_ranked_follows_contract_order() -> None:
    rows = cf.ranked({"b": -5.0, "a": -5.0, "c": 0.0, "d": -7.5})
    assert [(r["post_id"], r["rank"]) for r in rows] == [("d", 1), ("a", 2), ("b", 3), ("c", 4)]
