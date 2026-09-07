"""C2 지역·연령·성별 L1 특정성 교차조회 검증.

실행:
    python -m kopl.c2_specificity.test_l1
"""

from kopl.c2_specificity import age_to_band, specificity_l1


LEGAL_BASIS = {
    "method": "legal_dong_expansion",
    "source": "행정안전부 주민등록 인구통계",
    "as_of": "2026-07",
}


def test_age_to_band() -> None:
    assert age_to_band(0) == "0-4"
    assert age_to_band(4) == "0-4"
    assert age_to_band(5) == "5-9"
    assert age_to_band(22) == "20-24"
    assert age_to_band(38) == "35-39"
    assert age_to_band(74) == "70-74"
    assert age_to_band(99) == "95-99"
    assert age_to_band(100) == "100+"
    assert age_to_band(105) == "100+"


def test_d06_boundary() -> None:
    result = specificity_l1(
        "경상남도 의령군 궁류면",
        age=38,
        sex="F",
    )

    assert result["geo_code"] == "4872041500"
    assert result["age_band"] == "35-39"
    assert result["population"] == 5
    assert result["k"] == 5
    assert result["k_level"] == "ACCEPTABLE"
    assert result["floor_applied"] is False


def test_d07_population() -> None:
    result = specificity_l1(
        "인천광역시 미추홀구 주안3동",
        age=74,
        sex="M",
    )

    assert result["geo_code"] == "2817764000"
    assert result["age_band"] == "70-74"
    assert result["k"] == 339
    assert result["k_level"] == "ACCEPTABLE"


def test_d08_population() -> None:
    result = specificity_l1(
        "경기도 광주시 경안동",
        age=22,
        sex="F",
    )

    assert result["geo_code"] == "4161051000"
    assert result["age_band"] == "20-24"
    assert result["k"] == 679
    assert result["k_level"] == "ACCEPTABLE"

def test_legal_dong_expansion() -> None:
    result = specificity_l1(
        "전북특별자치도 전주시 완산구 효자동",
        age=31,
        sex="F",
    )

    assert result["codes"] == [
        "5211171100",
        "5211171200",
        "5211171300",
        "5211171400",
        "5211173000",
    ]
    assert result["age_band"] == "30-34"
    assert result["populations"] == {
        "5211171100": 365,
        "5211171200": 234,
        "5211171300": 396,
        "5211171400": 1163,
        "5211173000": 1666,
    }
    assert result["k_union"] == 3824
    assert result["k_min"] == 234
    assert result["k"] == 234
    assert result["k_level"] == "ACCEPTABLE"
    assert "ambiguous" not in result
    assert result["resolution"] == "legal_expansion"
    assert result["basis"] == LEGAL_BASIS

def test_unknown_location() -> None:
    result = specificity_l1(
        "존재하지않는동",
        age=30,
        sex="F",
    )

    assert result["k"] is None
    assert result["k_level"] == "UNKNOWN"


def test_ambiguous_location() -> None:
    result = specificity_l1(
        "중앙동",
        age=30,
        sex="M",
    )

    assert result["k"] is None
    assert result["k_level"] == "UNKNOWN"
    assert result["ambiguous"] is True
    assert len(result["candidates"]) > 1


def test_invalid_input() -> None:
    try:
        age_to_band(-1)
    except ValueError:
        pass
    else:
        raise AssertionError("음수 나이는 ValueError여야 합니다.")

    try:
        specificity_l1("궁류면", age=38, sex="X")
    except ValueError:
        pass
    else:
        raise AssertionError("잘못된 성별은 ValueError여야 합니다.")


if __name__ == "__main__":
    test_age_to_band()
    print("[PASS] 만 나이 → 5세 연령구간 변환")

    test_d06_boundary()
    print("[PASS] D06 궁류면 38F → k=5")

    test_d07_population()
    print("[PASS] D07 주안3동 74M → k=339")

    test_d08_population()
    print("[PASS] D08 경안동 22F → k=679")

    test_legal_dong_expansion()
    print("[PASS] 법정동 1:N L1 k_union·k_min 계산")

    test_unknown_location()
    print("[PASS] 없는 지명 UNKNOWN 처리")

    test_ambiguous_location()
    print("[PASS] 동명이 지명 임의 선택 차단")

    test_invalid_input()
    print("[PASS] 잘못된 나이·성별 입력 차단")
