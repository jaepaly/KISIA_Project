"""행정구역 이름으로 특정성 k를 조회하는 프로토타입."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any


DEFAULT_REGIONS_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "dict"
    / "admin"
    / "regions.json"
)

# 법정동 이름 하나가 여러 행정동으로 연결되는 임시 대응이다.
# 전체 대응표는 KIKmix 기반 후속 작업에서 데이터 파일로 분리한다.
_HYOJA_ADMIN_CODES = [
    "5211171100",
    "5211171200",
    "5211171300",
    "5211171400",
    "5211173000",
]

_LEGAL_DONG_PATH_CODES: dict[str, list[str]] = {
    "전북특별자치도 전주시 완산구 효자동": _HYOJA_ADMIN_CODES,
    "전라북도 전주시 완산구 효자동": _HYOJA_ADMIN_CODES,
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

    def __init__(self, path: str | Path = DEFAULT_REGIONS_PATH) -> None:
        self.path = Path(path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.regions: dict[str, dict[str, Any]] = payload["regions"]
        self.name_index: dict[str, list[str]] = payload["name_index"]

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

        # 정본 경로와 과거 표기를 모두 법정동→행정동 후보로 연결한다.
        legal_dong = _LEGAL_DONG_PATH_CODES.get(raw_text)
        if legal_dong is not None:
            return [
                code
                for code in legal_dong
                if code in self.regions
            ]

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
        parts = raw_text.split()

        if len(parts) > 1:
            target = parts[-1]
            implicit_context = " ".join(parts[:-1])
        else:
            target = raw_text
            implicit_context = None

        key = _normalize_name(target)
        candidates = list(self.normalized_index.get(key, []))

        if not candidates:
            return []

        # 본문 경로와 별도 context를 모두 적용한다.
        # 둘이 충돌하면 양쪽 조건을 만족하는 후보가 없어 []가 된다.
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

            # 전체 문자열 포함 여부가 아니라 행정구역 세그먼트끼리 비교한다.
            # 따라서 '남구'가 '강남구'에 포함됐다는 이유로 일치하지 않는다.
            full_name_tokens = set(
                _context_tokens(str(region.get("full_name", "")))
            )

            if all(token in full_name_tokens for token in tokens):
                filtered.append(code)

        # 맥락이 있는데 일치 후보가 없으면 전국의 다른 동을 반환하지 않는다.
        return filtered

    def specificity(self, name: str) -> dict[str, Any]:
        """행정구역 이름 하나의 총인구와 k 등급을 반환한다."""
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

        # 계약은 k >= 1을 요구한다.
        # 주민등록 인구가 0명인 지역에는 하한 1을 적용한다.
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