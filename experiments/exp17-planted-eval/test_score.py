"""exp17 채점기 — 1:1 매칭과 post_id 검사 (#311 리뷰)."""
import importlib.util
import json
from pathlib import Path

import pytest

# 다른 실험에도 score.py 가 있어(exp09) 이름으로 import 하면 CI 에서 섞인다 — 파일 경로로 불러온다
_spec = importlib.util.spec_from_file_location("exp17_score", Path(__file__).resolve().parent / "score.py")
_score = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_score)
evaluate, load_preds = _score.evaluate, _score.load_preds


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


def test_excluded_clue_is_not_scored_and_does_not_consume_prediction():
    """exp17b — 제외 단서는 채점에서 빠지고, 예측을 빼앗지도 않는다 (#314)."""
    excluded = dict(_clue(0, 5), excluded=True)
    gold = _gold([excluded, _clue(1, 5)])
    preds = {"P1": [{"text_id": "body", "start": 0, "end": 5, "type": "LOC_ADMIN"}]}
    out = evaluate(gold, preds)
    assert out["recall_all"] == 1.0 and out["unplanned_spans_per_post"] == 0


def test_recall_by_group():
    gold = _gold([dict(_clue(0, 4), group="aimed"), dict(_clue(10, 14), group="unaimed")])
    preds = {"P1": [{"text_id": "body", "start": 0, "end": 4, "type": "LOC_ADMIN"}]}
    assert evaluate(gold, preds)["recall_by_group"] == {"aimed": "1/1", "unaimed": "0/1"}


def test_typed_distractor_counts_its_own_type():
    """exp17d — JOB 함정(「방학이라」)을 JOB 으로 잡으면 JOB 함정 오탐. 유형 없는 함정은 지금처럼 AGE 로 센다."""
    gold = _gold([], [{"start": 0, "end": 4, "text": "방학이라", "type": "JOB"},
                      {"start": 10, "end": 14, "text": "서른 그릇"}])
    preds = {"P1": [{"text_id": "body", "start": 0, "end": 3, "type": "JOB"},
                    {"text_id": "body", "start": 10, "end": 12, "type": "AGE"}]}
    r = evaluate(gold, preds)
    assert r["distractor_fp_by_type"] == {"AGE": "1/1", "JOB": "1/1"}
    assert r["distractor_age_fp"] == "1/1"
    # AGE 로 잡은 JOB 함정은 JOB 오탐이 아니다
    r = evaluate(gold, {"P1": [{"text_id": "body", "start": 0, "end": 4, "type": "AGE"}]})
    assert r["distractor_fp_by_type"]["JOB"] == "0/1"


def test_untyped_distractors_keep_old_output():
    """exp17 · 17b · 17c 는 출력 키가 그대로다 — distractor_fp_by_type 이 생기지 않는다."""
    r = evaluate(_gold([], [{"start": 0, "end": 4, "text": "서른 해"}]), {"P1": []})
    assert r["distractor_age_fp"] == "0/1" and "distractor_fp_by_type" not in r


def test_typed_distractor_touch_and_excluded():
    """JOB 함정은 짧게 걸쳐도 오탐 · 전수 검토에서 뺀 함정은 분모에도 안 들어간다 (Codex 10/12)."""
    gold = _gold([], [{"start": 0, "end": 9, "text": "치과 진료 받으러", "type": "JOB"},
                      {"start": 20, "end": 24, "text": "방학이라", "type": "JOB", "excluded": "직업 문맥"}])
    r = evaluate(gold, {"P1": [{"text_id": "body", "start": 0, "end": 2, "type": "JOB"},
                               {"text_id": "body", "start": 20, "end": 24, "type": "JOB"}]})
    assert r["distractor_fp_by_type"]["JOB"] == "1/1"


def test_self_attribution_counted_apart_from_recall():
    """본인 단서를 other 로 잡으면 재현율은 맞지만 본인 귀속에서 빠진다."""
    gold = _gold([dict(_clue(0, 4, typ="JOB"), group="job_self"), dict(_clue(10, 14, typ="JOB"), group="job_self")])
    preds = {"P1": [{"text_id": "body", "start": 0, "end": 4, "type": "JOB", "subject": "self"},
                    {"text_id": "body", "start": 10, "end": 14, "type": "JOB", "subject": "other"}]}
    r = evaluate(gold, preds)
    assert r["recall_by_group"]["job_self"] == "2/2" and r["self_attributed_by_group"]["job_self"] == "1/2"


def test_other_title_short_self_prediction_is_leak():
    """exp17d 남의 직함 — 「팀장님께서」에서 「팀장」만 self 로 잡아도 본인 판정(오탐)으로 센다."""
    gold = _gold([dict(_clue(0, 5, typ="JOB", subject="other"), group="job_title_other")])
    r = evaluate(gold, {"P1": [{"text_id": "body", "start": 0, "end": 2, "type": "JOB", "subject": "self"}]})
    assert r["trap_other"]["judged_self"] == 1


def test_typed_age_distractor_keeps_iou_rule():
    """exp17d 의 AGE 함정은 type 이 있어도 예전처럼 IoU ≥ 0.5 로 센다."""
    gold = _gold([], [{"start": 0, "end": 6, "text": "스물한 개", "type": "AGE"}])
    r = evaluate(gold, {"P1": [{"text_id": "body", "start": 0, "end": 1, "type": "AGE"}]})
    assert r["distractor_age_fp"] == "0/1"
