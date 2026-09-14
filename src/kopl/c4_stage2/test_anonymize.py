"""c4_stage2 가명화·복원 라운드트립 검증.

실행:
    python -m kopl.c4_stage2.test_anonymize
    python -m pytest src/kopl/c4_stage2/test_anonymize.py -v
"""

from kopl.c4_stage2 import anonymize, restore


def test_roundtrip_basic() -> None:
    """시설 + 숫자 나이 — 가명 토큰 삽입 후 완전 복원."""
    #      0123456789...
    text = "판교 사는 48세 직장인이고 신갈저수지 자주 갑니다"
    facility_start = text.index("신갈저수지")
    spans = [
        {"start": 6, "end": 9, "text": "48세", "type": "AGE"},
        {
            "start": facility_start,
            "end": facility_start + 5,
            "text": "신갈저수지",
            "type": "LOC_FACILITY",
        },
    ]
    anon, key = anonymize(text, spans)
    assert "[40대]" in anon, f"연령대 토큰 누락: {anon!r}"
    assert "[시설1]" in anon, f"시설 토큰 누락: {anon!r}"
    assert "48세" not in anon and "신갈저수지" not in anon, f"원문 잔존: {anon!r}"
    assert restore(anon, key) == text, f"복원 실패: {restore(anon, key)!r}"
    print("[PASS] 1. 기본 라운드트립(시설+숫자나이) 통과")


def test_same_decade_no_collision() -> None:
    """같은 연령대 서로 다른 나이 — README 예시 버전이 깨지는 지점."""
    text = "형은 48세, 나는 42세"
    spans = [
        {"start": 3, "end": 6, "text": "48세", "type": "AGE"},
        {"start": 11, "end": 14, "text": "42세", "type": "AGE"},
    ]
    anon, key = anonymize(text, spans)
    # 두 나이가 같은 [40대]로 뭉개지지 않고 유일 토큰으로 분리돼야 한다
    assert len(key) == 2, f"토큰이 유일하지 않음: {key}"
    assert restore(anon, key) == text, f"복원 실패: {restore(anon, key)!r}"
    print("[PASS] 2. 같은 연령대 충돌 없이 라운드트립 통과")


def test_korean_age_fallback() -> None:
    """한글 나이('마흔여덟') — 연령대 환산 실패해도 라운드트립 보장."""
    text = "마흔여덟 되니 무릎이 아픕니다"
    spans = [{"start": 0, "end": 4, "text": "마흔여덟", "type": "AGE"}]
    anon, key = anonymize(text, spans)
    assert "마흔여덟" not in anon, f"원문 잔존: {anon!r}"
    assert restore(anon, key) == text, f"복원 실패: {restore(anon, key)!r}"
    print("[PASS] 3. 한글 나이 폴백 라운드트립 통과")


def test_multi_same_type() -> None:
    """같은 유형 여러 스팬 — 인덱스로 구분."""
    text = "신갈저수지 옆 기흥호수 조황"
    spans = [
        {"start": 0, "end": 5, "text": "신갈저수지", "type": "LOC_FACILITY"},
        {"start": 8, "end": 12, "text": "기흥호수", "type": "LOC_FACILITY"},
    ]
    anon, key = anonymize(text, spans)
    assert "[시설1]" in anon and "[시설2]" in anon, f"시설 인덱스 누락: {anon!r}"
    assert restore(anon, key) == text, f"복원 실패: {restore(anon, key)!r}"
    print("[PASS] 4. 같은 유형 다중 스팬 라운드트립 통과")


def test_all_canonical_types() -> None:
    """정본 10종 각각 한 스팬 — 유형명 계약 준수 + 라운드트립."""
    parts = {
        "AGE": "30대",
        "SEX": "남자",
        "LOC_ADMIN": "성수동",
        "LOC_FACILITY": "한강공원",
        "REL_HOME": "집 근처",
        "REL_WORK": "회사 앞",
        "JOB": "바리스타",
        "FAM": "여동생",
        "COMMUTE": "판교로 출근",
        "INCOME": "월 이백",
    }
    text = " ".join(parts.values())
    spans = []
    cursor = 0
    for typ, frag in parts.items():
        start = text.index(frag, cursor)
        spans.append({"start": start, "end": start + len(frag), "text": frag, "type": typ})
        cursor = start + len(frag)
    anon, key = anonymize(text, spans)
    assert len(key) == 10, f"토큰 수 불일치: {len(key)}"
    assert restore(anon, key) == text, f"복원 실패: {restore(anon, key)!r}"
    print("[PASS] 5. 정본 10종 라운드트립 통과")


def test_empty_and_identical() -> None:
    """스팬 없음 → 원문 그대로. 동일 원문 반복 → 라운드트립 유지."""
    assert anonymize("스팬 없는 잡담 글", []) == ("스팬 없는 잡담 글", {})

    text = "신갈저수지 갔다가 또 신갈저수지"
    s2 = text.index("신갈저수지", 1)
    spans = [
        {"start": 0, "end": 5, "text": "신갈저수지", "type": "LOC_FACILITY"},
        {"start": s2, "end": s2 + 5, "text": "신갈저수지", "type": "LOC_FACILITY"},
    ]
    anon, key = anonymize(text, spans)
    assert restore(anon, key) == text, f"복원 실패: {restore(anon, key)!r}"
    print("[PASS] 6. 빈 스팬·동일 원문 반복 라운드트립 통과")


if __name__ == "__main__":
    print("=== kopl.c4_stage2 가명화·복원 검증 시작 ===")
    test_roundtrip_basic()
    test_same_decade_no_collision()
    test_korean_age_fallback()
    test_multi_same_type()
    test_all_canonical_types()
    test_empty_and_identical()
    print("=== [성공] c4_stage2 라운드트립 전 항목 통과 ===")
