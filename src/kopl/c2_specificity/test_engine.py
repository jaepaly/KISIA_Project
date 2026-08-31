"""C2 지역 단일 조건 프로토타입 자체 검증.

실행:
    python -m kopl.c2_specificity.test_engine
"""

from kopl.c2_specificity import classify_k, resolve, specificity


def test_unique_name() -> None:
    result = specificity("성수1가제1동")

    assert result == {
        "k": 14748,
        "k_level": "ACCEPTABLE",
    }


def test_ambiguous_name() -> None:
    result = specificity("중앙동")

    assert result["k"] is None
    assert result["k_level"] == "UNKNOWN"
    assert result["ambiguous"] is True
    assert len(result["candidates"]) > 1


def test_unknown_name() -> None:
    result = specificity("존재하지않는동")

    assert result == {
        "k": None,
        "k_level": "UNKNOWN",
    }


def test_k_boundaries() -> None:
    assert classify_k(None) == "UNKNOWN"
    assert classify_k(1) == "VERY_HIGH"
    assert classify_k(2) == "VERY_HIGH"
    assert classify_k(3) == "HIGH"
    assert classify_k(4.9) == "HIGH"
    assert classify_k(5) == "ACCEPTABLE"


def test_legal_dong_canonical_and_deprecated_path() -> None:
    expected = [
        "5211171100",
        "5211171200",
        "5211171300",
        "5211171400",
        "5211173000",
    ]

    # 현재 정본 시도명과 과거 시도명 모두 같은 행정동 후보로 연결한다.
    assert resolve(
        "전북특별자치도 전주시 완산구 효자동"
    ) == expected
    assert resolve(
        "전라북도 전주시 완산구 효자동"
    ) == expected


def test_context_segment_matching() -> None:
    # '남구'가 '강남구'의 부분문자열이라는 이유로 일치하면 안 된다.
    assert resolve(
        "신사동",
        context="남구",
    ) == []

    # 본문 전체 경로와 별도 context가 충돌하면 한쪽을 임의로 고르지 않는다.
    assert resolve(
        "서울특별시 강남구 신사동",
        context="관악구",
    ) == []


if __name__ == "__main__":
    test_unique_name()
    print("[PASS] 고유 지명 총인구 조회")

    test_ambiguous_name()
    print("[PASS] 동명이 지명 후보 반환")

    test_unknown_name()
    print("[PASS] 없는 지명 UNKNOWN 처리")

    test_k_boundaries()
    print("[PASS] k_level 경계값")

    test_legal_dong_canonical_and_deprecated_path()
    print("[PASS] 정본·과거 효자동 법정동 후보 조회")

    test_context_segment_matching()
    print("[PASS] 상위 경로 세그먼트 비교·맥락 충돌 차단")