"""주민등록 인구 교차표 로더와 조회 함수."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TypeAlias


DEFAULT_POPULATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "dict"
    / "admin"
    / "population.csv"
)

PopulationTable: TypeAlias = dict[str, dict[str, dict[str, int]]]


def load_population(
    path: str | Path = DEFAULT_POPULATION_PATH,
) -> PopulationTable:
    """인구 CSV를 ``geo_code → sex → age_band → population``으로 읽는다."""
    population: PopulationTable = {}

    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            geo_code = row["geo_code"]
            sex = row["sex"]
            age_band = row["age_band"]
            count = int(row["population"])

            population.setdefault(geo_code, {}).setdefault(sex, {})[
                age_band
            ] = count

    return population


def pop_lookup(
    population: PopulationTable,
    *,
    geo_code: str,
    sex: str | None = None,
    age_bands: list[str] | None = None,
    default: int | None = None,
) -> int | None:
    """지역·성별·연령구간 조건에 해당하는 인구를 합산한다.

    조회 조건이나 데이터가 없으면 인구 0명으로 오인하지 않고
    ``default``를 반환한다. 실제 통계값이 0명인 경우에는 0을 반환한다.
    """
    by_sex = population.get(geo_code)
    if by_sex is None:
        return default

    if sex is None:
        selected_sexes = list(by_sex)
    elif sex in by_sex:
        selected_sexes = [sex]
    else:
        return default

    total = 0

    for selected_sex in selected_sexes:
        bands = by_sex[selected_sex]

        if age_bands is None:
            selected_bands = list(bands)
        else:
            if any(age_band not in bands for age_band in age_bands):
                return default
            selected_bands = age_bands

        total += sum(bands[age_band] for age_band in selected_bands)

    return total