"""기여도 증류 타깃 생성기 회귀 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.gen_contribution_targets import (
    build_evidence_indexes,
    generate_target,
    generate_targets,
    load_excluded_posts,
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


def test_user_ref_is_deterministic_and_non_identifying() -> None:
    first = user_ref_for("A01")
    assert first == user_ref_for("A01")
    assert first != user_ref_for("A02")
    assert first.startswith("u_")
    assert len(first) == 14


def test_load_spans_ignores_blind_gold(
    tmp_path: Path,
) -> None:
    """blind/ 는 같은 글의 독립 라벨이라 합치지 않는다 — span_id 가 그대로 겹친다."""
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
                "post_id": "A01_b01",
                "reviewed": True,
                "spans": [gold_span("A01_b01_s01", "AGE", "서른여덟")],
            },
            {
                "post_id": "A01_b03",
                "reviewed": True,
                "spans": [],
            },
        ],
    )

    loaded = load_spans(gold, "A01")
    assert sorted(loaded) == ["A01_b01"]
    assert [span["span_id"] for span in loaded["A01_b01"]] == ["A01_b01_s01"]
    # 같은 span_id 가 blind 에도 있지만 합치지 않으므로 중복으로 튕기지 않는다
    build_evidence_indexes(loaded)


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


def test_load_excluded_posts_reads_post_ids(tmp_path: Path) -> None:
    path = tmp_path / "test.jsonl"
    path.write_text(
        '{"post_id": "A01_b01", "kind": "clue"}\n'
        "\n"
        '{"post_id": "A01_b02", "kind": "noise"}\n',
        encoding="utf-8",
    )

    assert load_excluded_posts(path) == {"A01_b01", "A01_b02"}
    assert load_excluded_posts(None) == set()
    with pytest.raises(FileNotFoundError):
        load_excluded_posts(tmp_path / "missing.jsonl")


def test_generate_targets_excludes_listed_posts(
    tmp_path: Path,
) -> None:
    """test split 글을 빼야 D 의 make_sft_v1 글 집합 검사를 통과한다."""
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
            },
            {
                "post_id": "A01_b02",
                "reviewed": True,
                "spans": [gold_span("A01_b02_s01", "AGE", "39")],
            },
        ],
    )
    write_jsonl(
        gold / "A02_spans.jsonl",
        [
            {
                "post_id": "A02_b01",
                "reviewed": True,
                "spans": [gold_span("A02_b01_s01", "AGE", "40")],
            }
        ],
    )

    generated, skipped = generate_targets(
        gold,
        personas,
        out,
        {"A01_b02", "A02_b01"},
    )

    assert generated == 1
    # 남는 글이 없는 인물은 골드가 없는 인물과 같이 건너뛴다
    assert skipped == ["A02"]
    payload = json.loads((out / "A01.json").read_text(encoding="utf-8"))
    assert payload["input"]["post_ids"] == ["A01_b01"]


def test_generate_targets_writes_only_personas_with_gold(
    tmp_path: Path,
) -> None:
    gold = tmp_path / "gold"
    personas = tmp_path / "personas"
    out = tmp_path / "out"
    personas.mkdir()
    (personas / "A01.json").write_text("{}", encoding="utf-8")
    (personas / "A02.json").write_text("{}", encoding="utf-8")
    out.mkdir()
    (out / "A02.json").write_text('{"stale": true}\n', encoding="utf-8")
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
    assert not (out / "A02.json").exists()
    payload = json.loads((out / "A01.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["input"]["method"] == "loo"
