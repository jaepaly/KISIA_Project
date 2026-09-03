"""행정구역 이름으로 특정성 k를 조회하는 프로토타입."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any
from .dicts import PopulationTable, load_population, pop_lookup

DEFAULT_REGIONS_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "dict"
    / "admin"
    / "regions.json"
)

DEFAULT_LEGAL_ADMIN_MAP_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "dict"
    / "admin"
    / "legal_admin_map.json"
)

# 과거 전체 경로를 현재 KIKmix 법정동 경로로 연결한다.
_RENAMED_QUERY_PATHS: dict[str, str] = {
    "전라북도 전주시 완산구 효자동":
        "전북특별자치도 전주시 완산구 효자동",
    "인천광역시 서구 청라동":
        "인천광역시 서해구 청라동",
}

# 최근 행정구역 개편 전 전체 경로를 현재 행정코드로 연결한다.
_RENAMED_PATH_CODES: dict[str, list[str]] = {
    "인천광역시 중구 신포동": [
        "2812551000",
    ],
}


def classify_k(k: int | float | None) -> str:
    """계약의 경계값에 따라 k 등급을 반환한다."""
    if k is None:
        return "UNKNOWN"
    if k <= 2:
        return "VERY_HIGH"
    if k < 5:
        return "HIGH"
    return "ACCEPTABLE"

def age_to_band(age: int) -> str:
    """만 나이를 주민등록 인구통계의 5세 연령구간으로 변환한다."""
    if isinstance(age, bool) or not isinstance(age, int):
        raise TypeError("age는 정수여야 합니다.")

    if age < 0:
        raise ValueError("age는 0 이상이어야 합니다.")

    if age >= 100:
        return "100+"

    start = (age // 5) * 5
    return f"{start}-{start + 4}"

def _normalize_name(value: str) -> str:
    """지명 비교용으로 제·점·공백 표기 차이를 정규화한다."""
    normalized = unicodedata.normalize("NFC", value).strip()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace(".", "")
    normalized = re.sub(r"제(?=\d)", "", normalized)
    return normalized


def _context_tokens(value: str | None) -> list[str]:
    """상위 경로 문자열을 공백 단위 행정구역명으로 나눈다."""
    if not value:
        return []

    return [
        _normalize_name(token)
        for token in value.split()
        if token.strip()
    ]


class RegionDictionary:
    """regions.json을 한 번 읽고 지명 조회에 재사용한다."""

    def __init__(
        self,
        path: str | Path = DEFAULT_REGIONS_PATH,
        legal_admin_path: str | Path | None = DEFAULT_LEGAL_ADMIN_MAP_PATH,
    ) -> None:
        self.path = Path(path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.regions: dict[str, dict[str, Any]] = payload["regions"]
        self.name_index: dict[str, list[str]] = payload["name_index"]

        self.legal_admin_mappings: dict[str, dict[str, Any]] = {}
        self.legal_name_index: dict[str, list[str]] = {}
        self.admin_group_index: dict[str, list[str]] = {}

        if legal_admin_path is not None:
            self.legal_admin_path = Path(legal_admin_path)
            legal_payload = json.loads(
                self.legal_admin_path.read_text(encoding="utf-8")
            )

            if legal_payload["dict_version"] != payload["dict_version"]:
                raise ValueError(
                    "regions.json과 legal_admin_map.json의 "
                    "dict_version이 다릅니다."
                )

            self.legal_admin_mappings = legal_payload["mappings"]

            for full_name in self.legal_admin_mappings:
                final_name = full_name.rsplit(" ", 1)[-1]
                key = _normalize_name(final_name)
                self.legal_name_index.setdefault(key, []).append(full_name)

        # 이름·별칭을 같은 표기로 정규화한 검색 인덱스다.

        # 이름·별칭을 같은 표기로 정규화한 검색 인덱스다.
        self.normalized_index: dict[str, list[str]] = {}

        for code, region in self.regions.items():
            names = {
                str(region.get("name", "")),
                *[str(alias) for alias in region.get("aliases", [])],
            }

            for name in names:
                if not name:
                    continue

                key = _normalize_name(name)
                bucket = self.normalized_index.setdefault(key, [])

                if code not in bucket:
                    bucket.append(code)
                group_match = re.fullmatch(r"(.+?)\d+동", key)

                if group_match is not None:
                    group_key = f"{group_match.group(1)}동"
                    group_bucket = self.admin_group_index.setdefault(
                        group_key,
                        [],
                    )

                    if code not in group_bucket:
                        group_bucket.append(code)

    def _resolve_legal(
        self,
        text: str,
        context: str | None = None,
    ) -> tuple[list[str], list[str]]:
        """KIKmix에서 행정동 코드와 일치한 법정동 경로를 반환한다."""
        raw_text = unicodedata.normalize("NFC", text).strip()
        lookup_text = _RENAMED_QUERY_PATHS.get(raw_text, raw_text)
        parts = lookup_text.split()

        if len(parts) > 1:
            target = parts[-1]
            implicit_context = " ".join(parts[:-1])
        else:
            target = lookup_text
            implicit_context = None

        key = _normalize_name(target)
        tokens = [
            *_context_tokens(implicit_context),
            *_context_tokens(context),
        ]
        tokens = list(dict.fromkeys(tokens))

        matched_paths: list[str] = []

        for full_name in self.legal_name_index.get(key, []):
            full_name_tokens = set(_context_tokens(full_name))

            if not tokens or all(
                token in full_name_tokens for token in tokens
            ):
                matched_paths.append(full_name)

        candidates: set[str] = set()

        for full_name in matched_paths:
            mapping = self.legal_admin_mappings[full_name]

            for code in mapping["admin_codes"]:
                code = str(code)

                if code in self.regions:
                    candidates.add(code)

        return sorted(candidates), sorted(matched_paths)
    def resolve(
        self,
        text: str,
        context: str | None = None,
    ) -> list[str]:
        """지명과 상위 경로를 이용해 가능한 행정코드 목록을 반환한다.

        후보가 없거나 상위 경로와 맞지 않으면 빈 목록을 반환한다.
        전국에서 이름이 같더라도 임의로 한 곳을 고르지 않는다.
        """
        raw_text = unicodedata.normalize("NFC", text).strip()
        lookup_text = _RENAMED_QUERY_PATHS.get(raw_text, raw_text)

        legal_candidates, matched_legal_paths = self._resolve_legal(
            lookup_text,
            context=context,
        )

        if matched_legal_paths:
            return legal_candidates

        # 실제 폐지된 전체 경로는 현재 행정코드에 연결한다.
        renamed = _RENAMED_PATH_CODES.get(raw_text)

        if renamed is not None:
            return [
                code
                for code in renamed
                if code in self.regions
            ]

        # text 자체가 전체 경로라면 마지막 토큰은 지명,
        # 앞부분은 본문에서 얻은 상위 경로로 사용한다.
        parts = lookup_text.split()

        if len(parts) > 1:
            target = parts[-1]
            implicit_context = " ".join(parts[:-1])
        else:
            target = raw_text
            implicit_context = None

        key = _normalize_name(target)
        candidates = list(self.normalized_index.get(key, []))

        if not candidates:
            candidates = list(self.admin_group_index.get(key, []))

        if not candidates:
            return []

        tokens = [
            *_context_tokens(implicit_context),
            *_context_tokens(context),
        ]
        tokens = list(dict.fromkeys(tokens))

        if not tokens:
            return candidates

        filtered: list[str] = []

        for code in candidates:
            region = self.regions[code]
            full_name_tokens = set(
                _context_tokens(str(region.get("full_name", "")))
            )

            if all(token in full_name_tokens for token in tokens):
                filtered.append(code)

        return filtered

    def specificity(self, name: str) -> dict[str, Any]:
        """행정구역 이름 하나의 총인구와 k 등급을 반환한다."""
        legal_candidates, matched_legal_paths = self._resolve_legal(name)

        # 한 법정동이 여러 행정동에 걸치면 전체 집합과
        # 가장 작은 후보 집단을 모두 보고한다.
        if len(matched_legal_paths) == 1 and len(legal_candidates) > 1:
            populations = [
                int(self.regions[code]["population"])
                for code in legal_candidates
            ]
            k_union = max(1, sum(populations))
            k_min = max(1, min(populations))

            return {
                "k": k_min,
                "k_level": classify_k(k_min),
                "ambiguous": True,
                "codes": legal_candidates,
                "k_union": k_union,
                "k_min": k_min,
                "basis": "legal_dong_expansion",
            }

        # 같은 법정동명이 전국 여러 경로에 있으면 임의 선택하지 않는다.
        if len(matched_legal_paths) > 1:
            return {
                "k": None,
                "k_level": "UNKNOWN",
                "ambiguous": True,
                "candidates": legal_candidates,
            }

        candidates = self.resolve(name)

        if not candidates:
            return {
                "k": None,
                "k_level": "UNKNOWN",
            }

        if len(candidates) > 1:
            return {
                "k": None,
                "k_level": "UNKNOWN",
                "ambiguous": True,
                "candidates": candidates,
            }

        region = self.regions[candidates[0]]
        population = int(region["population"])
        k = max(1, population)

        return {
            "k": k,
            "k_level": classify_k(k),
        }

_DEFAULT_DICTIONARY: RegionDictionary | None = None


def _get_default_dictionary() -> RegionDictionary:
    global _DEFAULT_DICTIONARY

    if _DEFAULT_DICTIONARY is None:
        _DEFAULT_DICTIONARY = RegionDictionary()

    return _DEFAULT_DICTIONARY


def resolve(
    text: str,
    context: str | None = None,
) -> list[str]:
    """기본 행정구역 사전으로 지명 후보 코드를 조회한다."""
    return _get_default_dictionary().resolve(text, context=context)


def specificity(name: str) -> dict[str, Any]:
    """기본 행정구역 사전으로 지명의 특정성을 조회한다."""
    return _get_default_dictionary().specificity(name)

_DEFAULT_POPULATION: PopulationTable | None = None


def _get_default_population() -> PopulationTable:
    """기본 인구 교차표를 최초 한 번만 읽어 재사용한다."""
    global _DEFAULT_POPULATION

    if _DEFAULT_POPULATION is None:
        _DEFAULT_POPULATION = load_population()

    return _DEFAULT_POPULATION


def specificity_l1(
    location: str,
    age: int,
    sex: str,
    context: str | None = None,
) -> dict[str, Any]:
    """지역·연령·성별 교차표에서 L1 특정성 k를 계산한다."""
    normalized_sex = sex.strip().upper()

    if normalized_sex not in {"M", "F"}:
        raise ValueError("sex는 'M' 또는 'F'여야 합니다.")

    age_band = age_to_band(age)
    dictionary = _get_default_dictionary()
    legal_candidates, matched_legal_paths = dictionary._resolve_legal(
        location,
        context=context,
    )

    # 하나의 법정동이 여러 행정동에 걸치는 경우에는
    # 행정동별 교차인구를 모두 보존하고 최소값으로 위험을 판정한다.
    if len(matched_legal_paths) == 1 and len(legal_candidates) > 1:
        population_by_code: dict[str, int] = {}

        for code in legal_candidates:
            population = pop_lookup(
                _get_default_population(),
                geo_code=code,
                sex=normalized_sex,
                age_bands=[age_band],
            )

            if population is None:
                return {
                    "k": None,
                    "k_level": "UNKNOWN",
                    "age_band": age_band,
                    "sex": normalized_sex,
                    "codes": legal_candidates,
                    "basis": "legal_dong_expansion",
                }

            population_by_code[code] = population

        population_union = sum(population_by_code.values())
        population_min = min(population_by_code.values())
        k_union = max(1, population_union)
        k_min = max(1, population_min)

        return {
            "k": k_min,
            "k_level": classify_k(k_min),
            "age_band": age_band,
            "sex": normalized_sex,
            "ambiguous": True,
            "codes": legal_candidates,
            "k_union": k_union,
            "k_min": k_min,
            "populations": population_by_code,
            "floor_applied": population_min < 1,
            "basis": "legal_dong_expansion",
            "steps": [
                {
                    "axis": "location+age+sex",
                    "condition": (
                        f"{location}({','.join(legal_candidates)}) / "
                        f"{age_band} / {normalized_sex}"
                    ),
                    "n_after": population_min,
                    "method": "legal_dong_expansion_min",
                }
            ],
        }

    # 같은 법정동명이 여러 지역에 있으면 임의로 하나를 고르지 않는다.
    if len(matched_legal_paths) > 1:
        return {
            "k": None,
            "k_level": "UNKNOWN",
            "age_band": age_band,
            "sex": normalized_sex,
            "ambiguous": True,
            "candidates": legal_candidates,
        }

    candidates = dictionary.resolve(location, context=context)

    if not candidates:
        return {
            "k": None,
            "k_level": "UNKNOWN",
            "age_band": age_band,
            "sex": normalized_sex,
        }

    if len(candidates) > 1:
        return {
            "k": None,
            "k_level": "UNKNOWN",
            "age_band": age_band,
            "sex": normalized_sex,
            "ambiguous": True,
            "candidates": candidates,
        }


    if len(candidates) > 1:
        return {
            "k": None,
            "k_level": "UNKNOWN",
            "age_band": age_band,
            "sex": normalized_sex,
            "ambiguous": True,
            "candidates": candidates,
        }
    geo_code = candidates[0]
    population = pop_lookup(
        _get_default_population(),
        geo_code=geo_code,
        sex=normalized_sex,
        age_bands=[age_band],
    )

    if population is None:
        return {
            "k": None,
            "k_level": "UNKNOWN",
            "geo_code": geo_code,
            "age_band": age_band,
            "sex": normalized_sex,
        }

    floor_applied = population < 1
    k = max(1, population)

    return {
        "k": k,
        "k_level": classify_k(k),
        "geo_code": geo_code,
        "age_band": age_band,
        "sex": normalized_sex,
        "population": population,
        "floor_applied": floor_applied,
        "steps": [
            {
                "axis": "location+age+sex",
                "condition": (
                    f"{location}({geo_code}) / "
                    f"{age_band} / {normalized_sex}"
                ),
                "n_after": population,
                "method": "crosstab_lookup",
            }
        ],
    }