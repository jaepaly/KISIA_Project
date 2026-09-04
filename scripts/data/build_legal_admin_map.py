#!/usr/bin/env python3
"""Build a legal-dong to administrative-dong mapping from KIKmix."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DEFAULT_REGIONS_PATH = Path("data/dict/admin/regions.json")
DEFAULT_OUTPUT_PATH = Path("data/dict/admin/legal_admin_map.json")

# KIKmix.20260701 고정폭 바이트 위치
ADMIN_CODE = slice(0, 10)
SIDO_NAME = slice(11, 41)
SIGUNGU_NAME = slice(42, 72)
ADMIN_NAME = slice(73, 103)
LEGAL_CODE = slice(104, 114)
LEGAL_NAME = slice(115, 145)
CREATED_DATE = slice(146, 154)
DELETED_DATE = slice(155, 163)


def decode_field(line: bytes, field: slice) -> str:
    """CP949 고정폭 필드 하나를 문자열로 읽는다."""
    return line[field].decode("cp949").strip()


def load_regions(path: Path) -> tuple[str, dict[str, dict[str, object]]]:
    """행정구역 사전의 버전과 지역 레코드를 읽는다."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["dict_version"], payload["regions"]


def build_mapping(
    source: Path,
    regions: dict[str, dict[str, object]],
) -> tuple[dict[str, dict[str, object]], int]:
    """KIKmix 원본에서 현재 유효한 법정동→행정동 대응을 만든다."""
    lines = source.read_bytes().splitlines()

    if not lines:
        raise ValueError("KIKmix 원본이 비어 있습니다.")

    mappings: dict[str, tuple[str, set[str]]] = {}
    active_rows = 0
    missing_admin_codes: set[str] = set()

    for line_number, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue

        if len(line) < 163:
            raise ValueError(
                f"{line_number}행 길이가 너무 짧습니다: {len(line)}바이트"
            )

        admin_code = decode_field(line, ADMIN_CODE)
        sido = decode_field(line, SIDO_NAME)
        sigungu = decode_field(line, SIGUNGU_NAME)
        admin_name = decode_field(line, ADMIN_NAME)
        legal_code = decode_field(line, LEGAL_CODE)
        legal_name = decode_field(line, LEGAL_NAME)
        created_date = decode_field(line, CREATED_DATE)
        deleted_date = decode_field(line, DELETED_DATE)

        if deleted_date:
            continue

        if not legal_name:
            continue

        region = regions.get(admin_code)

        if region is None:
            missing_admin_codes.add(admin_code)
            continue

        # 시도·시군구 행은 제외하고 행정 읍면동만 사용한다.
        if region.get("level") != "emd":
            continue

        if not admin_name:
            raise ValueError(
                f"{line_number}행에 행정 읍면동명이 없습니다: {admin_code}"
            )

        # 법정리는 같은 시군구 안에서 이름이 중복될 수 있으므로
        # 상위 읍·면 이름을 경로에 포함한다.
        # 법정동은 여러 행정동으로 갈릴 수 있어 admin_name을 붙이지 않는다.
        path_parts = [sido, sigungu]

        if legal_name.endswith("리") and admin_name.endswith(("읍", "면")):
            path_parts.append(admin_name)

        path_parts.append(legal_name)
        full_legal_name = " ".join(
            part for part in path_parts if part
        )

        previous = mappings.get(full_legal_name)

        if previous is None:
            mappings[full_legal_name] = (legal_code, {admin_code})
        else:
            previous_legal_code, admin_codes = previous

            if previous_legal_code != legal_code:
                raise ValueError(
                    f"같은 법정동 경로에 코드가 둘입니다: "
                    f"{full_legal_name} "
                    f"{previous_legal_code} != {legal_code}"
                )

            admin_codes.add(admin_code)

        active_rows += 1

        if not created_date:
            raise ValueError(
                f"{line_number}행에 생성일자가 없습니다: {full_legal_name}"
            )

    if missing_admin_codes:
        sample = ", ".join(sorted(missing_admin_codes)[:10])
        raise ValueError(
            "regions.json에 없는 행정동 코드가 있습니다: "
            f"{len(missing_admin_codes)}개 ({sample})"
        )

        # 효자동1가·효자동2가처럼 숫자+가로 구분된 법정동은
    # 사용자가 흔히 쓰는 효자동 형태의 파생 경로로도 묶는다.
    derived_aliases: dict[str, tuple[set[str], set[str]]] = {}

    for full_name, (legal_code, admin_codes) in mappings.items():
        prefix, _, final_name = full_name.rpartition(" ")
        match = re.fullmatch(r"(.+동)\d+가", final_name)

        if match is None:
            continue

        alias = f"{prefix} {match.group(1)}"
        legal_codes, alias_admin_codes = derived_aliases.setdefault(
            alias,
            (set(), set()),
        )
        legal_codes.add(legal_code)
        alias_admin_codes.update(admin_codes)

    output: dict[str, dict[str, object]] = {
        full_name: {
            "legal_codes": [legal_code],
            "admin_codes": sorted(admin_codes),
            "basis": "exact",
        }
        for full_name, (legal_code, admin_codes) in mappings.items()
    }

    for alias, (legal_codes, admin_codes) in derived_aliases.items():
        # 실제 법정동 경로가 이미 있으면 파생 별칭으로 덮어쓰지 않는다.
        if alias in output:
            continue

        output[alias] = {
            "legal_codes": sorted(legal_codes),
            "admin_codes": sorted(admin_codes),
            "basis": "derived_shorthand",
        }

    return dict(sorted(output.items())), active_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="행정안전부 KIKmix.20260701 원본",
    )
    parser.add_argument(
        "--regions",
        type=Path,
        default=DEFAULT_REGIONS_PATH,
        help="행정구역 사전 regions.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="생성할 법정동→행정동 대응표",
    )
    args = parser.parse_args()

    dict_version, regions = load_regions(args.regions)
    mappings, active_rows = build_mapping(args.source, regions)

    one_to_many = sum(
        len(record["admin_codes"]) > 1
        for record in mappings.values()
    )

    payload = {
        "schema_version": "1.0",
        "dict_version": dict_version,
        "source": "행정안전부 KIKmix.20260701",
        "source_as_of": "2026-07-01",
        "source_url": "https://www.code.go.kr/",
        "mappings": mappings,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"OK 활성 대응 행: {active_rows:,}개")
    print(f"OK 법정동 경로: {len(mappings):,}개")
    print(f"OK 1:N 법정동: {one_to_many:,}개")
    print(f"OK 출력: {args.output}")


if __name__ == "__main__":
    main()
