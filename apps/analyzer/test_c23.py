import json
from pathlib import Path

from jsonschema import Draft202012Validator

from apps.analyzer.engines.c23 import (
    conditions_by_post,
    contribution,
    flatten_conditions,
    specificity,
)

ROOT = Path(__file__).resolve().parents[2]


class FakeDictionary:
    population_as_of = "2026-07"
    regions = {
        "4146351000": {
            "name": "신갈동",
            "full_name": "경기도 용인시 기흥구 신갈동",
            "population": 21930,
            "level": "emd",
        }
    }

    def resolve(self, text: str) -> list[str]:
        return ["4146351000"] if text == "신갈동" else []


def schema(name: str) -> dict:
    return json.loads((ROOT / "docs" / "contracts" / name).read_text(encoding="utf-8"))


def span(post_id: str, span_id: str, text: str = "신갈동") -> dict:
    return {
        "span_id": span_id,
        "text_id": "body",
        "start": 0,
        "end": len(text),
        "text": text,
        "type": "LOC_ADMIN",
        "level": "explicit",
        "subject": "self",
        "score": 0.99,
    }


def test_specificity_adapter_passes_contract() -> None:
    by_post = conditions_by_post(
        {"p1": {"spans": [span("p1", "p1_s01")]}},
        dictionary=FakeDictionary(),
    )
    payload = {
        "user_ref": "u_deadbeef",
        "conditions": flatten_conditions(by_post, include_empty_sentinel=True),
    }

    result = specificity(payload, dictionary=FakeDictionary())

    Draft202012Validator(schema("specificity.schema.json")).validate(result)
    assert result["output"]["k"] == 21930
    assert result["output"]["risk_by_axis"]["location"] == 85.0


def test_no_clue_account_returns_unknown_without_breaking_contract() -> None:
    by_post = conditions_by_post({"p1": {"spans": []}}, dictionary=FakeDictionary())
    payload = {
        "user_ref": "u_deadbeef",
        "conditions": flatten_conditions(by_post, include_empty_sentinel=True),
    }

    result = specificity(payload, dictionary=FakeDictionary())

    Draft202012Validator(schema("specificity.schema.json")).validate(result)
    assert result["output"]["k"] is None
    assert result["output"]["k_level"] == "UNKNOWN"
    assert result["output"]["risk"] == 0.0


def test_contribution_uses_real_span_evidence_and_passes_contract() -> None:
    spans = {
        "p1": {"spans": [span("p1", "p1_s01")]},
        "p2": {"spans": []},
    }
    conditions = conditions_by_post(spans, dictionary=FakeDictionary())

    result = contribution(
        "u_deadbeef",
        ["p1", "p2"],
        spans_by_post=spans,
        conditions=conditions,
    )

    Draft202012Validator(schema("contribution.schema.json")).validate(result)
    row = next(item for item in result["output"]["contributions"] if item["post_id"] == "p1")
    assert row["clue_ids"] == ["p1_s01"]
    assert row["top_spans"] == [{"span_id": "p1_s01", "text_id": "body"}]
    assert row["delta"] < 0


def test_contribution_recompute_removed_posts() -> None:
    spans = {
        "p1": {"spans": [span("p1", "p1_s01")]},
        "p2": {"spans": []},
    }
    conditions = conditions_by_post(spans, dictionary=FakeDictionary())

    result = contribution(
        "u_deadbeef",
        ["p1", "p2"],
        spans_by_post=spans,
        conditions=conditions,
        removed_post_ids=["p1"],
    )

    assert result["output"]["risk_after"] == 0.0
