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
