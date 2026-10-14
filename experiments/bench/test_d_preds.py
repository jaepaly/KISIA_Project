"""1단 예측 읽기 검증 — spans 가 없으면 조용히 비우지 않고 멈춘다 · 중복 post_id 거부 (#359 B 리뷰)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import d_downstream  # noqa: E402
import d_preds  # noqa: E402
import d_risk_action  # noqa: E402
import d_stage2  # noqa: E402

SPAN = {"text_id": "body", "start": 0, "end": 2, "type": "AGE", "text": "마흔", "level": "explicit", "subject": "self"}


def _write(tmp_path: Path, rows: list) -> Path:
    p = tmp_path / "preds.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


# 세 하류 단계가 모두 같은 검증을 거친다
READERS = {
    "d_preds": d_preds.read_pred_rows,
    "d_stage2": d_stage2.read_preds,
    "d_downstream": d_downstream._read_preds,
    "d_risk_action": lambda p: d_risk_action.read_preds(p, test_ids=frozenset()),
}


@pytest.mark.parametrize("name", READERS)
def test_exp06_candidates_format_stops(tmp_path: Path, name: str) -> None:
    """exp06 의 candidates 형식을 그대로 넣으면 — 예전엔 탐지 0 으로 지나갔다. 이제 멈춘다."""
    p = _write(tmp_path, [{"post_id": "U1_a", "candidates": [SPAN]}])
    with pytest.raises(ValueError, match="spans 필드가 없다"):
        READERS[name](p)


@pytest.mark.parametrize("name", READERS)
@pytest.mark.parametrize("bad", [None, "AGE", {"0": SPAN}])
def test_spans_not_list_stops(tmp_path: Path, name: str, bad) -> None:
    p = _write(tmp_path, [{"post_id": "U1_a", "spans": bad}])
    with pytest.raises(ValueError, match="리스트가 아니다"):
        READERS[name](p)


@pytest.mark.parametrize("name", READERS)
def test_duplicate_post_id_stops(tmp_path: Path, name: str) -> None:
    p = _write(tmp_path, [{"post_id": "U1_a", "spans": [SPAN]}, {"post_id": "U1_a", "spans": []}])
    with pytest.raises(ValueError, match="같은 post_id"):
        READERS[name](p)


@pytest.mark.parametrize("name", READERS)
def test_empty_spans_is_normal(tmp_path: Path, name: str) -> None:
    """탐지가 정말 없는 글은 spans: [] — 이것은 정상이고 글은 그대로 남는다."""
    p = _write(tmp_path, [{"post_id": "U1_a", "spans": []}, {"post_id": "U1_b", "spans": [SPAN]}])
    out = READERS[name](p)
    ids = sorted(out) if isinstance(out, dict) else sorted(r["post_id"] for r in out)
    assert ids == ["U1_a", "U1_b"]


def test_bad_post_id_and_span_type(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="post_id"):
        d_preds.read_pred_rows(_write(tmp_path, [{"post_id": "", "spans": []}]))
    with pytest.raises(ValueError, match="객체"):
        d_preds.read_pred_rows(_write(tmp_path, [{"post_id": "U1_a", "spans": ["마흔"]}]))
