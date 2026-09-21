"""골드 스팬 → specificity condition 변환 회귀 테스트."""

from __future__ import annotations

from kopl.c2_specificity import build_conditions, span_to_condition


def span(
    span_type: str,
    text: str,
    *,
    level: str = "implicit",
    subject: str = "self",
) -> dict[str, str]:
    return {
        "type": span_type,
        "text": text,
        "level": level,
        "subject": subject,
    }


def test_location_uses_dictionary_level_not_code_length() -> None:
    sido = span_to_condition(
        span("LOC_ADMIN", "서울특별시", level="explicit"),
        "p1",
    )
    sigungu = span_to_condition(
        span("LOC_ADMIN", "마포구", level="explicit"),
        "p1",
    )
    emd = span_to_condition(
        span("LOC_ADMIN", "성수1가제1동", level="explicit"),
        "p1",
    )

    assert sido is not None and sido["resolution"] == 1
    assert sigungu is not None and sigungu["resolution"] == 2
    assert emd is not None and emd["resolution"] == 3
    assert len(str(sido["geo_code"])) == 10
    assert len(str(sigungu["geo_code"])) == 10


def test_unknown_location_and_general_facility_are_skipped() -> None:
    assert span_to_condition(
        span("LOC_ADMIN", "존재하지않는동"),
        "p1",
    ) is None
    assert span_to_condition(
        span("LOC_FACILITY", "동네 저수지"),
        "p1",
    ) is None


def test_known_station_becomes_facility_condition() -> None:
    condition = span_to_condition(
        span("LOC_FACILITY", "용마산역", level="explicit"),
        "p1",
    )
    assert condition is not None
    assert condition["axis"] == "location"
    assert condition["kind"] == "facility"
    assert condition["resolution"] == 4
    assert len(str(condition["geo_code"])) == 10


def test_age_exact_and_generation_are_separate() -> None:
    exact = span_to_condition(
        span("AGE", "서른여덟", level="explicit"),
        "p1",
    )
    generation = span_to_condition(
        span("AGE", "30대", level="explicit"),
        "p1",
    )

    assert exact is not None
    assert exact["kind"] == "age_exact"
    assert exact["resolution"] == 3
    assert generation is not None
    assert generation["kind"] == "age_band"
    assert generation["resolution"] == 1


def test_job_family_commute_and_income_resolution() -> None:
    job = span_to_condition(
        span("JOB", "약사", level="explicit"),
        "p1",
    )
    family = span_to_condition(
        span("FAM", "중2 아들"),
        "p1",
    )
    commute = span_to_condition(
        span("COMMUTE", "832번 버스"),
        "p1",
    )
    income = span_to_condition(
        span("INCOME", "활동비가 빠듯했다"),
        "p1",
    )

    assert job is not None and job["resolution"] == 2
    assert family is not None and family["resolution"] == 3
    assert commute is not None and commute["resolution"] == 2
    assert income is not None and income["resolution"] == 1


def test_other_is_excluded_and_unknown_halves_confidence() -> None:
    assert span_to_condition(
        span("AGE", "서른", subject="other"),
        "p1",
    ) is None

    condition = span_to_condition(
        span("SEX", "남성", level="implicit", subject="unknown"),
        "p1",
    )
    assert condition is not None
    assert condition["confidence"] == 0.4


def test_spouse_term_adds_family_condition() -> None:
    conditions = build_conditions(
        [span("SEX", "남편", level="implicit")],
        "p1",
    )
    assert [condition["axis"] for condition in conditions] == [
        "sex",
        "family",
    ]
    assert conditions[1]["value"] == "married"
    assert conditions[1]["resolution"] == 1


def test_relationship_spans_are_modifiers() -> None:
    spans = [
        span("LOC_ADMIN", "마포구", level="inferential"),
        span("REL_HOME", "집에서", level="inferential"),
        span("REL_WORK", "출근", level="inferential"),
    ]
    conditions = build_conditions(spans, "p1")

    location = next(
        condition
        for condition in conditions
        if condition["axis"] == "location"
    )
    commute = next(
        condition
        for condition in conditions
        if condition["axis"] == "commute"
    )
    assert location["confidence"] == 1.0
    assert commute == {
        "axis": "commute",
        "kind": "commute_mode",
        "value": "REL_WORK",
        "resolution": 1,
        "confidence": 0.5,
        "source_post_ids": ["p1"],
    }


def test_relation_spans_alone_make_no_direct_condition() -> None:
    assert span_to_condition(span("REL_HOME", "집에서"), "p1") is None
    assert span_to_condition(span("REL_WORK", "회사에서"), "p1") is None
