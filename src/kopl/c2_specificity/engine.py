"""행정동 이름으로 총인구(k)를 조회하는 최소 프로토타입.

이번 단계는 지역 단일 조건만 처리한다. 연령·성별 조건 결합과 완전한
specificity.schema.json 출력은 다음 단계에서 추가한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_REGIONS_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "dict"
    / "admin"
    / "regions.json"
)


def classify_k(k: int | float | None) -> str:
    """계약의 경계값에 따라 k 등급을 반환한다."""
    if k is None:
        return "UNKNOWN"
    if k <= 2:
        return "VERY_HIGH"
    if k < 5:
        return "HIGH"
    return "ACCEPTABLE"


class RegionDictionary:
    """regions.json을 한 번 읽고 지명 조회에 재사용한다."""

    def __init__(self, path: str | Path = DEFAULT_REGIONS_PATH) -> None:
        self.path = Path(path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.regions: dict[str, dict[str, Any]] = payload["regions"]
        self.name_index: dict[str, list[str]] = payload["name_index"]

    def specificity(self, name: str) -> dict[str, Any]:
        """행정구역 이름 하나의 총인구와 k 등급을 반환한다.

        동명이 지명은 임의로 하나를 고르지 않고 UNKNOWN과 후보 코드를
        반환한다. 존재하지 않는 이름도 UNKNOWN으로 처리한다.
        """
        normalized = name.strip()
        candidates = self.name_index.get(normalized, [])

        if not candidates:
            return {"k": None, "k_level": "UNKNOWN"}

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


def specificity(name: str) -> dict[str, Any]:
    """기본 행정구역 사전으로 지명을 조회하는 편의 함수."""
    global _DEFAULT_DICTIONARY

    if _DEFAULT_DICTIONARY is None:
        _DEFAULT_DICTIONARY = RegionDictionary()

    return _DEFAULT_DICTIONARY.specificity(name)