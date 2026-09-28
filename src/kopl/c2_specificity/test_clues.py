"""골드 스팬 → specificity condition 변환 회귀 테스트."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

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
    decade_half = span_to_condition(
        span("AGE", "40대 초반", level="explicit"),
        "p1",
    )
    decade_ambiguous = span_to_condition(
        span("AGE", "30대", level="explicit"),
        "p1",
    )

    assert exact is not None
    assert exact["kind"] == "age_exact"
    assert exact["resolution"] == 3

    assert decade_half is not None
    assert decade_half["kind"] == "age_band"
    assert decade_half["value"] == "40-44"
    assert decade_half["resolution"] == 1

    assert decade_ambiguous is not None
    assert decade_ambiguous["kind"] == "age_hint"
    assert decade_ambiguous["resolution"] == 1


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


# R2: 하나의 5세 구간으로 정규화 가능한 표현만 age_band
def test_age_band_maps_to_valid_five_year_enum() -> None:
    cases = [
        ("40대 초반", "40-44"),
        ("40대 후반", "45-49"),
        ("30대 초반", "30-34"),
        ("30대 후반", "35-39"),
        ("20대 초반", "20-24"),
        ("스물 초반", "20-24"),
        ("마흔 후반", "45-49"),
        ("60대 후반", "65-69"),
    ]
    for text, expected in cases:
        cond = span_to_condition(span("AGE", text), "p1")
        assert cond is not None, text
        assert cond["kind"] == "age_band", text
        assert cond["value"] == expected, text
        assert cond["resolution"] == 1, text


# R3: 하나의 5세 구간으로 확정할 수 없는 표현 → age_hint
def test_ambiguous_age_expressions_become_age_hint() -> None:
    ambiguous = ["경로당", "야자", "중년", "반오십", "이 나이에", "30대", "40대"]
    for text in ambiguous:
        cond = span_to_condition(span("AGE", text), "p1")
        assert cond is not None, text
        assert cond["kind"] == "age_hint", text
        assert cond["value"] == text, text
        assert cond["resolution"] == 1, text


# R4: 정확한 나이 표현 → age_exact / resolution 3
def test_precise_age_expressions_become_age_exact() -> None:
    for text in ["세 살", "아홉 살", "1988년생", "삼십팔 세", "삼십팔 살"]:
        cond = span_to_condition(span("AGE", text), "p1")
        assert cond is not None, text
        assert cond["kind"] == "age_exact", text
        assert cond["resolution"] == 3, text


# R5: 단일 5세 구간으로 확정 불가 표현은 age_exact로 오분류하지 않는다
def test_imprecise_age_expressions_not_classified_as_age_exact() -> None:
    not_exact = [
        "서른 중반",
        "스물 넘은",
        "고3",
        "초6",
        "2학년",
        "90년대",
        "20~29세",
        "일년 선배",
        "열람실",
    ]
    for text in not_exact:
        cond = span_to_condition(span("AGE", text), "p1")
        if cond is not None:
            assert cond["kind"] != "age_exact", text


# R6: 빈 text 또는 빈 post_id는 계약 위반 condition을 만들지 않는다
def test_empty_text_or_post_id_produces_no_condition() -> None:
    assert span_to_condition(span("AGE", ""), "p1") is None
    assert span_to_condition(span("AGE", "서른여덟"), "") is None
    assert build_conditions([span("AGE", "서른여덟")], "") == []


# COMMUTE: 특정 노선·역 vs 일반 교통 표현 resolution 구분
def test_commute_route_resolution() -> None:
    assert span_to_condition(span("COMMUTE", "832번 버스"), "p1")["resolution"] == 2
    assert span_to_condition(
        span("COMMUTE", "수인분당선 매탄권선역 1번 출구 퇴근길"), "p1"
    )["resolution"] == 2
    assert span_to_condition(span("COMMUTE", "지하철역에서"), "p1")["resolution"] == 1
    assert span_to_condition(span("COMMUTE", "광역버스에서"), "p1")["resolution"] == 1


# FAM: 다양한 학년 표기가 모두 resolution 3
def test_family_grade_detail_resolution() -> None:
    grade_texts = [
        "초2", "중2", "중2 아들",
        "초등학교 2학년", "중학교 2학년", "고등학교 2학년",
        "2학년",
    ]
    for text in grade_texts:
        cond = span_to_condition(span("FAM", text), "p1")
        assert cond is not None, text
        assert cond["resolution"] == 3, text


# 배우자 호칭: 조사 결합 또는 단어 끝만 married 조건 생성
def test_spouse_term_josa_boundary() -> None:
    # 집사람이 SPOUSE_TERMS에 추가됨
    for text in ["집사람", "집사람이", "집사람이랑"]:
        conditions = build_conditions([span("SEX", text)], "p1")
        married = [c for c in conditions if c.get("value") == "married"]
        assert len(married) == 1, f"'{text}' should produce married condition"

    # 조사 없이 뒤에 존칭·접미사가 붙으면 married 아님
    for text in ["신부님", "신랑감"]:
        conditions = build_conditions([span("SEX", text)], "p1")
        married = [c for c in conditions if c.get("value") == "married"]
        assert len(married) == 0, f"'{text}' should NOT produce married condition"


# 시설 별칭: 역 접미사 없는 별칭의 부분 문자열 오분류 방지
def test_facility_alias_not_partial_matched() -> None:
    for text in ["수유실", "국수집", "도심 도서관"]:
        cond = span_to_condition(span("LOC_FACILITY", text), "p1")
        assert cond is None, f"'{text}' should not be matched as station"


# 계약 검증: jsonschema로 생성 condition이 스키마를 위반하지 않는지 확인
try:
    import jsonschema as _jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

_SCHEMA_PATH = Path(__file__).parents[3] / "docs" / "contracts" / "specificity.schema.json"


@pytest.mark.skipif(not _HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_conditions_satisfy_contract_schema() -> None:
    import jsonschema

    full_schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    condition_schema = full_schema["$defs"]["condition"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        resolver = jsonschema.RefResolver.from_schema(full_schema)

    def _validate(c: dict) -> None:
        jsonschema.validate(c, condition_schema, resolver=resolver)

    test_spans = [
        span("AGE", "40대 초반"),
        span("AGE", "서른여덟", level="explicit"),
        span("AGE", "30대"),
        span("AGE", "1988년생"),
        span("SEX", "남성"),
        span("JOB", "약사", level="explicit"),
        span("FAM", "중2 아들"),
        span("FAM", "초등학교 2학년"),
        span("COMMUTE", "832번 버스"),
        span("COMMUTE", "지하철역에서"),
        span("INCOME", "활동비가 빠듯했다"),
    ]
    for s in test_spans:
        cond = span_to_condition(s, "p1")
        if cond is not None:
            _validate(cond)
