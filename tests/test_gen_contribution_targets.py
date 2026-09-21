"""기여도 증류 타깃 생성기 회귀 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.gen_contribution_targets import (
    build_evidence_indexes,
    generate_target,
    generate_targets,
    load_spans,
    user_ref_for,
)


def gold_span(
    span_id: str,
    span_type: str,
    text: str,
    *,
    level: str = "explicit",
    subject: str = "self",
) -> dict[str, object]:
    return {
        "span_id": span_id,
        "text_id": "body",
        "start": 0,
        "end": len(text),
        "text": text,
        "type": span_type,
        "level": level,
        "subject": subject,
    }


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "schema_version": "1.0",
        "corpus_version": "v0",
        "created": "2026-09-21",
    }
    lines = [json.dumps(header, ensure_ascii=False)]
    lines.extend(json.dumps(record, ensure_ascii=False) for record in records)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_user_ref_matches_seed_rule() -> None:
    assert user_ref_for("A01") == "u_16a36e86f6fe"


def test_load_spans_merges_reviewed_top_level_and_blind(
    tmp_path: Path,
) -> None:
    gold = tmp_path / "gold"
    write_jsonl(
        gold / "A01_spans.jsonl",
        [
            {
                "post_id": "A01_b01",
                "reviewed": True,
                "spans": [gold_span("A01_b01_s01", "AGE", "서른여덟")],
            },
            {
                "post_id": "A01_b02",
                "reviewed": False,
                "spans": [gold_span("A01_b02_s01", "AGE", "마흔")],
            },
        ],
    )
    write_jsonl(
        gold / "blind" / "A01_spans.jsonl",
        [
            {
                "post_id": "A01_b03",
                "reviewed": True,
                "spans": [],
            }
        ],
    )

    loaded = load_spans(gold, "A01")
    assert sorted(loaded) == ["A01_b01", "A01_b03"]
    assert loaded["A01_b03"] == []


def test_generate_target_connects_conditions_to_loo() -> None:
    spans = {
        "A01_b01": [gold_span("A01_b01_s01", "AGE", "서른여덟")],
        "A01_b02": [
            gold_span(
                "A01_b02_s01",
                "INCOME",
                "활동비가 빠듯했다",
                level="implicit",
            )
        ],
        "A01_b03": [],
    }

    result = generate_target("A01", spans)
    output = result["output"]
    by_post = {
        item["post_id"]: item
        for item in output["contributions"]
    }

    assert result["input"]["user_ref"] == user_ref_for("A01")
    assert result["input"]["post_ids"] == [
        "A01_b01",
        "A01_b02",
        "A01_b03",
    ]
    assert output["baseline_risk"] == pytest.approx(21.43)
    assert by_post["A01_b01"]["delta"] == pytest.approx(-14.29)
    assert by_post["A01_b02"]["delta"] == pytest.approx(-7.14)
    assert by_post["A01_b03"]["delta"] == 0.0
    assert by_post["A01_b01"]["clue_ids"] == ["A01_b01_s01"]
    assert by_post["A01_b03"]["top_spans"] == []


def test_duplicate_span_id_is_rejected() -> None:
    duplicate = gold_span("same", "AGE", "38")
    with pytest.raises(ValueError, match="중복"):
        build_evidence_indexes({"p1": [duplicate, duplicate]})


def test_generate_targets_writes_only_personas_with_gold(
    tmp_path: Path,
) -> None:
    gold = tmp_path / "gold"
    personas = tmp_path / "personas"
    out = tmp_path / "out"
    personas.mkdir()
    (personas / "A01.json").write_text("{}", encoding="utf-8")
    (personas / "A02.json").write_text("{}", encoding="utf-8")
    write_jsonl(
        gold / "A01_spans.jsonl",
        [
            {
                "post_id": "A01_b01",
                "reviewed": True,
                "spans": [gold_span("A01_b01_s01", "AGE", "38")],
            }
        ],
    )

    generated, skipped = generate_targets(gold, personas, out)

    assert generated == 1
    assert skipped == ["A02"]
    payload = json.loads((out / "A01.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["input"]["method"] == "loo"
