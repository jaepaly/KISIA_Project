"""골드 스팬을 C2 특정성 condition으로 변환한다 (#261)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .engine import RegionDictionary
from .facilities import station_aliases, station_lookup
from .model import AGE_BAND_VALUES, LEVEL_CONFIDENCE, REGION_LEVEL_RESOLUTION, SPOUSE_TERMS

TYPE_TO_AXIS = {
    "LOC_ADMIN": "location", "LOC_FACILITY": "location",
    "AGE": "age", "SEX": "sex", "JOB": "occupation",
    "FAM": "family", "COMMUTE": "commute", "INCOME": "income",
}

# 4자리 연도 + 년생: "1988년생" → age_exact
_BIRTH_YEAR_RE = re.compile(
    r"(?<!\d)(?:\d{2}|\d{4})\s*년생(?!\d)"
)
# 숫자 범위 표현: "20~29세" → age_hint (단일 5세 구간 불가)
_AGE_RANGE_RE = re.compile(r"\d+\s*[~∼\-]\s*\d+\s*(?:살|세)")
# 고유어 정확 나이:
#   - 십 단위+일 단위(접미사 불필요): 서른여덟, 마흔다섯
#   - 십 단위 또는 한 자리 + 살/세: 서른 살, 세 살, 아홉 살
_NATIVE_EXACT_AGE_RE = re.compile(
    r"(?:열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)"
    r"(?:한|하나|두|둘|세|셋|네|넷|다섯|여섯|일곱|여덟|아홉)"
    r"|"
    r"(?:열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔|한|두|세|넷|다섯|여섯|일곱|여덟|아홉)"
    r"\s*(?:살|세)"
)
# 한자어 나이 + 살/세: 삼십팔 세, 이십 살 (년 접미사는 나이가 아님)
_SINO_EXACT_AGE_RE = re.compile(
    r"(?:[일이삼사오육칠팔구]?십[일이삼사오육칠팔구]?|[일이삼사오육칠팔구])"
    r"\s*(?:살|세)"
)
# 아라비아 숫자 + 살/세 필수: 38세, 5살 (고3·2학년 등 오분류 방지)
_ARABIC_EXACT_AGE_RE = re.compile(
    r"(?<!\d)(?:[0-9]|[1-9][0-9]|1[0-4][0-9])\s*(?:살|세)(?!\d)"
)
# 연대 절반 표현 (아라비아): 40대 초반 → "40-44", 40대 후반 → "45-49"
_DECADE_HALF_ARABIC_RE = re.compile(r"(\d+)\s*대\s*(초반|후반)")
# 연대 절반 표현 (고유어): 스물 초반 → "20-24", 마흔 후반 → "45-49"
_DECADE_NATIVE_MAP = {
    "열": 10, "스물": 20, "서른": 30, "마흔": 40,
    "쉰": 50, "예순": 60, "일흔": 70, "여든": 80, "아흔": 90,
}
_DECADE_HALF_NATIVE_RE = re.compile(
    r"(열|스물|서른|마흔|쉰|예순|일흔|여든|아흔)\s*(초반|후반)"
)
_FAMILY_DETAIL_RE = re.compile(
    # 전체 학교명 + 학년: "초등학교 2학년", "중학교 3학년"
    r"(?:초등학교|중학교|고등학교)\s*[1-6]\s*학년|"
    # 약어 + 학년/번호: "초2", "중3학년"
    r"(?:초|중|고)\s*[1-6](?:학년)?|"
    # 단독 학년 (FAM 맥락): "2학년"
    r"[1-6]\s*학년|"
    r"(?:첫째|둘째|셋째|넷째|막내)|"
    r"(?:아이|자녀|아들|딸)\s*(?:둘|셋|넷|\d+)"
)
# 숫자 기반 노선·버스 번호만 (역 이름은 사전 조회로 판단)
_COMMUTE_ROUTE_NUMBER_RE = re.compile(r"\d+\s*호선|\d+\s*번(?:\s*버스)?")

# 배우자 호칭 + 허용 후위: 조사 또는 공백·문자열 끝만 허용
# ("신부님"·"신랑감" 배제, "영감하고" 허용)
_SPOUSE_JOSA = (
    r"(?:하고|[이가은는을를과와도의]|로|으로|에서?|한테서?|이?랑|이?고|이?나|이?다"
    r"|이?라도|까지|부터|만|\s|$)"
)
_SPOUSE_TERM_RE = re.compile(
    r"(?:" + r"|".join(re.escape(t) for t in sorted(SPOUSE_TERMS, key=len, reverse=True)) + r")"
    + _SPOUSE_JOSA
)

_DEFAULT_DICTIONARY: RegionDictionary | None = None


def _dictionary() -> RegionDictionary:
    global _DEFAULT_DICTIONARY
    if _DEFAULT_DICTIONARY is None:
        _DEFAULT_DICTIONARY = RegionDictionary()
    return _DEFAULT_DICTIONARY


def _decode_decade_half(text: str) -> str | None:
    """연대 절반 표현을 5세 구간 enum 문자열로 변환한다. 해당 없으면 None."""
    m = _DECADE_HALF_ARABIC_RE.search(text)
    if m:
        decade = int(m.group(1))
        lo = decade if m.group(2) == "초반" else decade + 5
    else:
        m = _DECADE_HALF_NATIVE_RE.search(text)
        if m is None:
            return None
        decade = _DECADE_NATIVE_MAP.get(m.group(1))
        if decade is None:
            return None
        lo = decade if m.group(2) == "초반" else decade + 5
    band = "100+" if lo >= 100 else f"{lo}-{lo + 4}"
    return band if band in AGE_BAND_VALUES else None


def _age_resolution(text: str) -> tuple[int, str, str]:
    """(resolution, kind, value) 를 반환한다.

    kind ∈ {"age_exact", "age_band", "age_hint"}
    age_band 의 value 는 AGE_BAND_VALUES 에 속하는 5세 구간 문자열이다.
    """
    if _AGE_RANGE_RE.search(text):
        return 1, "age_hint", text
    if _BIRTH_YEAR_RE.search(text):
        return 3, "age_exact", text
    band = _decode_decade_half(text)
    if band is not None:
        return 1, "age_band", band
    if (
        _NATIVE_EXACT_AGE_RE.search(text)
        or _SINO_EXACT_AGE_RE.search(text)
        or _ARABIC_EXACT_AGE_RE.search(text)
    ):
        return 3, "age_exact", text
    return 1, "age_hint", text


def _commute_is_specific_route(text: str) -> bool:
    """숫자 노선·버스 번호 또는 사전에 있는 역명이 포함되면 True."""
    if _COMMUTE_ROUTE_NUMBER_RE.search(text):
        return True
    hit = station_lookup(text)
    if hit is not None and not hit.ambiguous and hit.emd is not None:
        return True
    for alias in station_aliases():
        if alias.endswith("역"):
            if alias not in text:
                continue
        else:
            if text != alias:
                continue
        hit = station_lookup(alias)
        if hit is not None and not hit.ambiguous and hit.emd is not None:
            return True
    return False


def _admin_condition(
    text: str,
    dictionary: RegionDictionary,
) -> tuple[int, str, str | None, str | None] | None:
    codes = dictionary.resolve(text)
    if not codes:
        return None

    resolved: list[tuple[int, str]] = []
    for code in codes:
        level = str(dictionary.regions.get(code, {}).get("level", ""))
        resolution = REGION_LEVEL_RESOLUTION.get(level)
        if resolution is not None:
            resolved.append((resolution, code))

    if not resolved:
        return None

    resolution = min(item[0] for item in resolved)

    if len(resolved) > 1:
        return resolution, "administrative_area", text, None

    _, code = resolved[0]
    return resolution, "administrative_area", None, code


def _facility_code(text: str) -> str | None:
    hit = station_lookup(text)
    if hit is not None:
        return hit.emd if not hit.ambiguous and hit.emd is not None else None
    for alias in station_aliases():
        if alias.endswith("역"):
            if alias not in text:
                continue
        else:
            # 역 접미사 없는 별칭은 스팬 전체가 일치할 때만 허용
            if text != alias:
                continue
        hit = station_lookup(alias)
        if hit is not None and not hit.ambiguous and hit.emd is not None:
            return hit.emd
    return None


def _resolved_fields(
    span: Mapping[str, Any],
    dictionary: RegionDictionary,
) -> tuple[int, str, str | None, str | None] | None:
    span_type = str(span["type"])
    text = str(span["text"]).strip()
    if not text:
        return None
    level = str(span["level"])

    if span_type == "LOC_ADMIN":
        result = _admin_condition(text, dictionary)
        if result is None:
            return None
        resolution, kind, value, code = result
        return resolution, kind, value, code
    if span_type == "LOC_FACILITY":
        code = _facility_code(text)
        if code is None:
            return None
        return 4, "facility", None, code
    if span_type == "AGE":
        resolution, kind, value = _age_resolution(text)
        return resolution, kind, value, None
    if span_type == "SEX":
        return 1, "sex", text, None
    if span_type == "JOB":
        resolution = 2 if level == "explicit" else 1
        return resolution, "job_group", text, None
    if span_type == "FAM":
        if _FAMILY_DETAIL_RE.search(text):
            resolution = 3
        elif level in {"explicit", "implicit"}:
            resolution = 2
        else:
            resolution = 1
        return resolution, "family_status", text, None
    if span_type == "COMMUTE":
        resolution = 2 if _commute_is_specific_route(text) else 1
        return resolution, "commute_mode", text, None
    if span_type == "INCOME":
        return 1, "income_band", text, None
    return None


def span_to_condition(
    span: Mapping[str, Any],
    post_id: str,
    *,
    dictionary: RegionDictionary | None = None,
) -> dict[str, Any] | None:
    """골드 스팬 한 개를 condition 한 개로 변환한다. 조건이 아니면 None."""
    if not post_id:
        return None
    subject = str(span["subject"])
    span_type = str(span["type"])
    if subject == "other" or span_type not in TYPE_TO_AXIS:
        return None

    level = str(span["level"])
    if level not in LEVEL_CONFIDENCE:
        raise ValueError(f"허용되지 않은 level: {level!r}")
    if subject not in {"self", "unknown"}:
        raise ValueError(f"허용되지 않은 subject: {subject!r}")

    confidence = LEVEL_CONFIDENCE[level]
    if subject == "unknown":
        confidence *= 0.5

    resolved = _resolved_fields(span, dictionary or _dictionary())
    if resolved is None:
        return None
    resolution, kind, value, geo_code = resolved
    condition: dict[str, Any] = {
        "axis": TYPE_TO_AXIS[span_type],
        "kind": kind,
        "resolution": resolution,
        "confidence": round(confidence, 2),
        "source_post_ids": [post_id],
    }
    if geo_code is not None:
        condition["geo_code"] = geo_code
    else:
        condition["value"] = value
    return condition


def build_conditions(
    spans: Sequence[Mapping[str, Any]],
    post_id: str,
    *,
    dictionary: RegionDictionary | None = None,
) -> list[dict[str, Any]]:
    """한 게시글의 스팬들을 condition 목록으로 만들고 관계 수식자를 적용한다."""
    if not post_id:
        return []
    conditions: list[dict[str, Any]] = []
    usable_rel_work = False
    rel_home_self = False

    for span in spans:
        span_type = str(span["type"])
        subject = str(span["subject"])
        if span_type == "REL_HOME" and subject == "self":
            rel_home_self = True
        if span_type == "REL_WORK" and subject != "other":
            usable_rel_work = True

        condition = span_to_condition(span, post_id, dictionary=dictionary)
        if condition is None:
            continue
        conditions.append(condition)

        text = str(span["text"])
        if span_type == "SEX" and _SPOUSE_TERM_RE.search(text):
            conditions.append({
                "axis": "family",
                "kind": "family_status",
                "value": "married",
                "resolution": 1,
                "confidence": condition["confidence"],
                "source_post_ids": [post_id],
            })

    if rel_home_self:
        for condition in conditions:
            if condition["axis"] == "location":
                condition["confidence"] = 1.0

    if usable_rel_work:
        conditions.append({
            "axis": "commute",
            "kind": "commute_mode",
            "value": "REL_WORK",
            "resolution": 1,
            "confidence": 0.5,
            "source_post_ids": [post_id],
        })

    return conditions
