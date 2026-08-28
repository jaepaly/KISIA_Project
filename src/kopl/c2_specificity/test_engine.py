"""C2 지역 단일 조건 프로토타입 자체 검증.

실행:
    python -m kopl.c2_specificity.test_engine
"""

from kopl.c2_specificity import classify_k, specificity


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


if __name__ == "__main__":
    test_unique_name()
    print("[PASS] 고유 지명 총인구 조회")

    test_ambiguous_name()
    print("[PASS] 동명이 지명 후보 반환")

    test_unknown_name()
    print("[PASS] 없는 지명 UNKNOWN 처리")

    test_k_boundaries()
    print("[PASS] k_level 경계값")