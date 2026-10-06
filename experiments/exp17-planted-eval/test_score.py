"""exp17 채점기 — 1:1 매칭과 post_id 검사 (#311 리뷰)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import evaluate, load_preds  # noqa: E402


def _gold(planted, distractors=()):
    return [{"post_id": "P1", "planted": planted, "distractors": list(distractors)}]


def _clue(start, end, typ="LOC_ADMIN", subject="self", variant="v"):
    return {"start": start, "end": end, "type": typ, "subject": subject, "variant": variant}


def test_one_prediction_counts_for_one_gold_only():
    """예측 하나가 정답 둘과 모두 IoU ≥ 0.5 여도 TP 는 하나다."""
    gold = _gold([_clue(0, 4), _clue(1, 5)])
    preds = {"P1": [{"text_id": "body", "start": 0, "end": 5, "type": "LOC_ADMIN"}]}
    assert evaluate(gold, preds)["recall_all"] == 0.5


def test_greedy_prefers_higher_iou_pair():
    """(IoU, 정답, 예측) 내림차순 — 더 잘 맞는 쌍이 먼저 짝지어져 둘 다 맞는다."""
    gold = _gold([_clue(0, 4), _clue(4, 8)])
    preds = {"P1": [{"text_id": "body", "start": 0, "end": 4, "type": "LOC_ADMIN"},
                    {"text_id": "body", "start": 3, "end": 8, "type": "LOC_ADMIN"}]}
    assert evaluate(gold, preds)["recall_all"] == 1.0


def test_trap_subject_uses_matched_prediction():
    gold = _gold([_clue(0, 4, subject="other")])
    preds = {"P1": [{"text_id": "body", "start": 0, "end": 4, "type": "LOC_ADMIN", "subject": "self"}]}
    trap = evaluate(gold, preds)["trap_other"]
    assert trap["caught"] == 1 and trap["judged_self"] == 1


def _write(tmp_path, rows):
    p = tmp_path / "preds.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return str(p)


def test_missing_post_id_fails(tmp_path):
    path = _write(tmp_path, [{"post_id": "P1", "spans": []}])
    with pytest.raises(ValueError, match="누락"):
        load_preds(path, {"P1", "P2"})


def test_extra_post_id_fails(tmp_path):
    path = _write(tmp_path, [{"post_id": "P1", "spans": []}, {"post_id": "X9", "spans": []}])
    with pytest.raises(ValueError, match="추가"):
        load_preds(path, {"P1"})


def test_duplicate_post_id_fails(tmp_path):
    path = _write(tmp_path, [{"post_id": "P1", "spans": []}, {"post_id": "P1", "spans": []}])
    with pytest.raises(ValueError, match="중복"):
        load_preds(path, {"P1"})


def test_missing_spans_field_fails_but_empty_list_is_ok(tmp_path):
    with pytest.raises(ValueError, match="spans"):
        load_preds(_write(tmp_path, [{"post_id": "P1"}]), {"P1"})
    assert load_preds(_write(tmp_path, [{"post_id": "P1", "spans": []}]), {"P1"}) == {"P1": []}


def test_tie_order_does_not_depend_on_input_order():
    """정답 순서를 뒤집어도 결과가 같다 — 좌표순 정렬 후 매칭 (Codex 10/6)."""
    a, b = _clue(0, 2), _clue(1, 3)
    preds = {"P1": [{"text_id": "body", "start": 0, "end": 1, "type": "LOC_ADMIN"},
                    {"text_id": "body", "start": 0, "end": 3, "type": "LOC_ADMIN"}]}
    assert evaluate(_gold([a, b]), preds)["recall_all"] == evaluate(_gold([b, a]), preds)["recall_all"]


def test_duplicate_span_in_post_fails(tmp_path):
    row = {"text_id": "body", "start": 0, "end": 5, "type": "LOC_ADMIN"}
    with pytest.raises(ValueError, match="두 번"):
        load_preds(_write(tmp_path, [{"post_id": "P1", "spans": [row, dict(row)]}]), {"P1"})


def test_trap_self_leak_counted_even_if_other_matched():
    gold = _gold([_clue(0, 4, subject="other")])
    preds = {"P1": [{"text_id": "body", "start": 0, "end": 4, "type": "LOC_ADMIN", "subject": "other"},
                    {"text_id": "body", "start": 0, "end": 5, "type": "LOC_ADMIN", "subject": "self"}]}
    assert evaluate(gold, preds)["trap_other"]["judged_self"] == 1


def test_trap_unknown_subject_is_not_self():
    gold = _gold([_clue(0, 4, subject="other")])
    preds = {"P1": [{"text_id": "body", "start": 0, "end": 4, "type": "LOC_ADMIN"}]}
    trap = evaluate(gold, preds)["trap_other"]
    assert trap["judged_self"] == 0 and trap["judged_unknown"] == 1


def test_matched_prediction_not_counted_as_distractor_fp():
    gold = _gold([_clue(0, 4, typ="AGE")], distractors=[{"start": 4, "end": 8}])
    preds = {"P1": [{"text_id": "body", "start": 0, "end": 8, "type": "AGE"}]}
    out = evaluate(gold, preds)
    assert out["recall_all"] == 1.0 and out["distractor_age_fp"] == "0/1"
