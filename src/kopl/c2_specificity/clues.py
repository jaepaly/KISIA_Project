"""골드 스팬을 C2 특정성 condition으로 변환한다 (#261)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .engine import RegionDictionary
from .facilities import station_aliases, station_lookup
from .model import LEVEL_CONFIDENCE, REGION_LEVEL_RESOLUTION, SPOUSE_TERMS

TYPE_TO_AXIS = {
    "LOC_ADMIN": "location", "LOC_FACILITY": "location",
    "AGE": "age", "SEX": "sex", "JOB": "occupation",
    "FAM": "family", "COMMUTE": "commute", "INCOME": "income",
}

_AGE_GENERATION_RE = re.compile(
    r"(?:\d{1,3}\s*대|중년|장년|청년|노년|"
    r"마흔\s*(?:넘|이후)|반오십|\d{4}\s*년생)"
)
_NATIVE_EXACT_AGE_RE = re.compile(
    r"(?:열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)"
    r"(?:한|하나|두|둘|세|셋|네|넷|다섯|여섯|일곱|여덟|아홉)?"
)
_SINO_EXACT_AGE_RE = re.compile(
    r"(?:[일이삼사오육칠팔구]?십[일이삼사오육칠팔구]?|"
    r"[일이삼사오육칠팔구])\s*년"
)
_ARABIC_EXACT_AGE_RE = re.compile(
    r"(?<!\d)(?:[0-9]|[1-9][0-9]|1[0-4][0-9])"
    r"(?:\s*(?:살|세))?(?!\d)"
)
_FAMILY_DETAIL_RE = re.compile(
    r"(?:초|중|고)\s*[1-6](?:학년)?|"
    r"(?:첫째|둘째|셋째|넷째|막내)|"
    r"(?:아이|자녀|아들|딸)\s*(?:둘|셋|넷|\d+)"
)
_COMMUTE_ROUTE_RE = re.compile(
    r"(?:\d+\s*호선|\d+\s*번(?:\s*버스)?|"
    r"[가-힣A-Za-z0-9]+역(?:\s*\d+번\s*출구)?)"
)

_DEFAULT_DICTIONARY: RegionDictionary | None = None


def _dictionary() -> RegionDictionary:
    global _DEFAULT_DICTIONARY
    if _DEFAULT_DICTIONARY is None:
        _DEFAULT_DICTIONARY = RegionDictionary()
    return _DEFAULT_DICTIONARY


def _age_resolution(text: str) -> tuple[int, str]:
    if _AGE_GENERATION_RE.search(text):
        return 1, "age_band"
    if (
        _NATIVE_EXACT_AGE_RE.search(text)
        or _SINO_EXACT_AGE_RE.search(text)
        or _ARABIC_EXACT_AGE_RE.search(text)
    ):
        return 3, "age_exact"
    return 1, "age_band"


def _admin_condition(
    text: str,
    dictionary: RegionDictionary,
) -> tuple[int, str, str] | None:
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
    resolution, code = min(resolved, key=lambda item: (item[0], item[1]))
    return resolution, "administrative_area", code


def _facility_code(text: str) -> str | None:
    hit = station_lookup(text)
    if hit is None:
        for alias in station_aliases():
            if alias in text:
                hit = station_lookup(alias)
                if hit is not None:
                    break
    if hit is None or hit.ambiguous or hit.emd is None:
        return None
    return hit.emd


def _resolved_fields(
    span: Mapping[str, Any],
    dictionary: RegionDictionary,
) -> tuple[int, str, str | None, str | None] | None:
    span_type = str(span["type"])
    text = str(span["text"]).strip()
    level = str(span["level"])

    if span_type == "LOC_ADMIN":
        result = _admin_condition(text, dictionary)
        if result is None:
            return None
        resolution, kind, code = result
        return resolution, kind, None, code
    if span_type == "LOC_FACILITY":
        code = _facility_code(text)
        if code is None:
            return None
        return 4, "facility", None, code
    if span_type == "AGE":
        resolution, kind = _age_resolution(text)
        return resolution, kind, text, None
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
        resolution = 2 if _COMMUTE_ROUTE_RE.search(text) else 1
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
        if span_type == "SEX" and any(term in text for term in SPOUSE_TERMS):
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
