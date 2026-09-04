#!/usr/bin/env python3
"""Build the 2026-07 administrative-region and population dictionaries.

The source CSVs are downloaded from the Ministry of the Interior and Safety
resident-registration population statistics site. They are CP949-encoded.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path


AGE_BANDS = [
    "0-4", "5-9", "10-14", "15-19", "20-24", "25-29", "30-34",
    "35-39", "40-44", "45-49", "50-54", "55-59", "60-64",
    "65-69", "70-74", "75-79", "80-84", "85-89", "90-94",
    "95-99", "100+",
]
SOURCE_AGE_BANDS = [band.replace("-", "~") + "세" for band in AGE_BANDS[:-1]] + ["100세 이상"]
REGION_RE = re.compile(r"^(.*?)\s*\((\d{10})\)\s*$")


def integer(value: str) -> int:
    return int(value.replace(",", "").strip() or "0")


def parse_region(value: str) -> tuple[str, str]:
    match = REGION_RE.match(value)
    if not match:
        raise ValueError(f"행정구역 형식을 해석할 수 없습니다: {value!r}")
    return " ".join(match.group(1).split()), match.group(2)


def level_of(code: str) -> str:
    if code.endswith("00000000"):
        return "sido"
    if code.endswith("00000"):
        return "sigungu"
    return "emd"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="cp949", newline="") as source:
        return list(csv.DictReader(source))


def build_regions(total_rows: list[dict[str, str]], output: Path) -> dict[str, int]:
    regions: dict[str, dict[str, object]] = {}
    name_index: dict[str, list[str]] = defaultdict(list)
    current_sido: tuple[str, str] | None = None
    current_sigungu: tuple[str, str] | None = None
    official_population: dict[str, int] = {}

    for row in total_rows:
        full_name, code = parse_region(row["행정구역"])
        level = level_of(code)
        name = full_name.split()[-1]
        population = integer(row["2026년07월_총인구수"])

        if level == "sido":
            current_sido = (code, name)
            current_sigungu = None
            parent = None
        elif level == "sigungu":
            if current_sido is None:
                raise ValueError(f"시도 상위 항목이 없습니다: {full_name}")
            parent = current_sido[0]
            current_sigungu = (code, name)
        else:
            if current_sido is None or current_sigungu is None:
                raise ValueError(f"시도·시군구 상위 항목이 없습니다: {full_name}")
            parent = current_sigungu[0]

        regions[code] = {
            "code": code,
            "name": name,
            "full_name": full_name,
            "level": level,
            "parent": parent,
            "sido": current_sido[1] if current_sido else None,
            "sigungu": current_sigungu[1] if current_sigungu else None,
            "population": population,
            "aliases": [name],
        }
        name_index[name].append(code)
        official_population[code] = population

    payload = {
        "schema_version": "1.0",
        "dict_version": "geo-2026-07",
        "source": "행정안전부 주민등록 인구통계 2026-07",
        "source_as_of": "2026-07",
        "regions": regions,
        "name_index": dict(sorted(name_index.items())),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return official_population


def build_population(
    age_rows: list[dict[str, str]], official_population: dict[str, int], output: Path
) -> tuple[int, int, list[str]]:
    keys: set[tuple[str, str, str]] = set()
    output_total = 0
    emd_count = 0
    age_codes: set[str] = set()

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target, lineterminator="\n")
        writer.writerow(["geo_code", "age_band", "sex", "population"])

        for row in age_rows:
            full_name, code = parse_region(row["행정구역"])
            if level_of(code) != "emd":
                continue
            emd_count += 1
            age_codes.add(code)
            row_total = 0
            sex_totals = {"남": 0, "여": 0}

            for age_band, source_band in zip(AGE_BANDS, SOURCE_AGE_BANDS, strict=True):
                for source_sex, sex in (("남", "M"), ("여", "F")):
                    population = integer(row[f"2026년07월_{source_sex}_{source_band}"])
                    key = (code, age_band, sex)
                    if key in keys:
                        raise ValueError(f"중복 조회 키: {key}")
                    keys.add(key)
                    writer.writerow([code, age_band, sex, population])
                    row_total += population
                    sex_totals[source_sex] += population
                    output_total += population

            declared_total = integer(row["2026년07월_계_총인구수"])
            if row_total != declared_total:
                raise ValueError(f"연령·성별 합계 불일치: {full_name} {row_total} != {declared_total}")
            for source_sex in ("남", "여"):
                declared_sex_total = integer(row[f"2026년07월_{source_sex}_총인구수"])
                if sex_totals[source_sex] != declared_sex_total:
                    raise ValueError(
                        f"{source_sex} 연령 합계 불일치: {full_name} "
                        f"{sex_totals[source_sex]} != {declared_sex_total}"
                    )
            if code in official_population and row_total != official_population[code]:
                raise ValueError(
                    f"두 원본 간 총인구 불일치: {full_name} {row_total} != {official_population[code]}"
                )

    expected_rows = emd_count * len(AGE_BANDS) * 2
    if len(keys) != expected_rows:
        raise ValueError(f"행 수 불일치: {len(keys)} != {expected_rows}")

    missing = sorted(
        code for code in official_population
        if level_of(code) == "emd" and code not in age_codes
    )
    nonzero_missing = [code for code in missing if official_population[code] != 0]
    if nonzero_missing:
        raise ValueError(f"연령별 원본에 없는 비영(非零) 읍면동: {nonzero_missing}")
    return emd_count, output_total, missing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--age", type=Path, required=True, help="202607 연령별인구현황 CSV")
    parser.add_argument("--total", type=Path, required=True, help="202607 주민등록인구및세대현황 CSV")
    parser.add_argument("--output-dir", type=Path, default=Path("data/dict/admin"))
    args = parser.parse_args()

    age_rows = read_rows(args.age)
    total_rows = read_rows(args.total)
    official = build_regions(total_rows, args.output_dir / "regions.json")
    emd_count, population, missing = build_population(
        age_rows, official, args.output_dir / "population.csv"
    )

    nationwide = sum(value for code, value in official.items() if level_of(code) == "sido")
    if population != nationwide:
        raise ValueError(f"전국 총인구 불일치: {population} != {nationwide}")

    print(f"OK regions.json: {len(official):,}개 행정구역")
    print(f"OK population.csv: {emd_count:,}개 읍면동 × 21개 연령구간 × 2개 성별")
    print(f"OK 전국 총인구: {population:,}명")
    if missing:
        print(f"INFO 연령별 원본에 없는 0명 읍면동 {len(missing)}개: {', '.join(missing)}")


if __name__ == "__main__":
    main()
