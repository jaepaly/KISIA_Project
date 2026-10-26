"""exp43 measure.py — 일치 판정 · 2단 대조 단위 테스트 (모델 · 코퍼스 없이).

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python -m pytest -q experiments/exp43-self-only-k/test_measure.py
"""
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("exp43_measure", HERE / "measure.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def S(start, end, typ="COMMUTE", text_id="body"):
    return {"start": start, "end": end, "type": typ, "text_id": text_id}


def test_match_is_order_independent():
    """IoU 큰 쌍부터 일대일 — 예측 순서를 뒤집어도 맞은 수가 같다 (Codex 검토: 순서 의존 탐욕은 2→1 이 됐다)."""
    gold = [S(0, 10), S(2, 12)]
    pred = [S(1, 12), S(5, 14)]   # 앞 예측은 두 골드와 다 맞고(0.75 · 0.83) 뒤 예측은 둘째 골드만(0.58)
    # 예전 순서 탐욕: (앞, 뒤) 1개 · (뒤, 앞) 2개. 이제는 IoU 큰 쌍(앞↔둘째)부터라 두 순서 모두 1개
    hits = [sum(g is not None for _, g in m._match(p, gold)) for p in (pred, pred[::-1])]
    assert hits == [1, 1]


def test_match_tie_is_order_independent():
    """IoU 동률이면 좌표 순서로 — 예측 · 골드 순서를 뒤집어도 맞은 수가 같다 (Codex 2차 반례)."""
    pred, gold = [S(0, 2), S(1, 3)], [S(0, 1), S(0, 3)]
    hits = {sum(g is not None for _, g in m._match(p, gg)) for p in (pred, pred[::-1]) for gg in (gold, gold[::-1])}
    assert len(hits) == 1


def test_match_requires_same_type_and_channel():
    gold = [S(0, 10), S(0, 10, "AGE"), S(0, 10, text_id="title")]
    assert [g for _, g in m._match([S(0, 10, "SEX")], gold)] == [None]
    assert m._match([S(0, 10, text_id="title")], gold)[0][1]["text_id"] == "title"
    assert [g for _, g in m._match([S(0, 3)], gold)] == [None]   # IoU 0.3


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _row(user, abstain):
    return {"persona_id": user, "findings": {ax: {"verdict": "abstain" if ax in abstain else "narrowed"}
                                             for ax in m.AXES7}}


def test_consistency_compares_cells_directly(tmp_path):
    dump = tmp_path / "d.json"
    dump.write_text(json.dumps({"users": [
        {"user": "A01", "pred_all": {"conditions": [["age", "age_exact", "x", 3, 1.0, ["p"]]]}},
        {"user": "A02", "pred_all": {"conditions": []}},
    ]}), encoding="utf-8")
    model, rules = tmp_path / "m.jsonl", tmp_path / "r.jsonl"
    everything = set(m.AXES7)
    _write(model, [_row("A01", everything), _row("A02", everything - {"sex"})])
    _write(rules, [_row("A01", everything - {"age"}), _row("A02", everything)])
    r = m.consistency({"x": dump}, {"model": model, "rules": rules}, tmp_path / "o.json")
    assert r["stage2_abstain_cells_differ"] == {"model_vs_rules": ["A01.age", "A02.sex"]}
    assert r["x|stage2_model"]["cells"] == {"abstain_but_k_condition": ["A01.age"],
                                             "judged_but_no_k_condition": ["A02.sex"]}
    assert r["x|stage2_rules"]["cells"] == {}


def test_dump_duplicate_user_is_rejected():
    with pytest.raises(AssertionError):
        m._users({"users": [{"user": "A01"}, {"user": "A01"}]})


def test_consistency_rejects_duplicate_user(tmp_path):
    dump = tmp_path / "d.json"
    dump.write_text(json.dumps({"users": [{"user": "A01", "pred_all": {"conditions": []}}]}), encoding="utf-8")
    dup = tmp_path / "m.jsonl"
    _write(dup, [_row("A01", set()), _row("A01", set())])
    with pytest.raises(AssertionError):
        m.consistency({"x": dump}, {"model": dup}, tmp_path / "o.json")
