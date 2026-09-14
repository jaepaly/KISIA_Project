"""c4_stage2 가명화·복원 라운드트립 검증.

실행:
    python -m kopl.c4_stage2.test_anonymize
    python -m pytest src/kopl/c4_stage2/test_anonymize.py -v
"""

import pytest

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


def test_token_literal_in_original() -> None:
    """원문에 가명 토큰과 같은 리터럴이 있어도 그것은 건드리지 않는다 (Codex P1-1)."""
    text = "[시설1] 서울역 다녀옴"
    start = text.index("서울역")
    spans = [{"start": start, "end": start + 3, "text": "서울역", "type": "LOC_FACILITY"}]
    anon, key = anonymize(text, spans)
    assert restore(anon, key) == text, f"복원 실패: {restore(anon, key)!r}"
    # 미리 있던 '[시설1]' 리터럴은 스팬이 아니므로 복원 키에 없어야 한다
    assert "[시설1]" not in key, f"원문 리터럴이 키에 섞임: {key}"
    print("[PASS] 7. 원문 내 토큰 리터럴 충돌 회피 통과")


def test_original_text_is_tokenlike() -> None:
    """스팬 원문 자체가 토큰처럼 생겨도 연쇄 재치환 없이 복원 (Codex P1-2)."""
    text = "서울역 [시설2]"
    spans = [
        {"start": 0, "end": 3, "text": "서울역", "type": "LOC_FACILITY"},
        {"start": 4, "end": 9, "text": "[시설2]", "type": "LOC_FACILITY"},
    ]
    anon, key = anonymize(text, spans)
    assert restore(anon, key) == text, f"복원 실패: {restore(anon, key)!r}"
    print("[PASS] 8. 토큰형 원문 연쇄 재치환 방지 통과")


def test_age_triple_same_decade() -> None:
    """같은 연령대 세 나이 — while 분리 루프를 실제로 태운다."""
    text = "48세 42세 45세"
    spans = [
        {"start": 0, "end": 3, "text": "48세", "type": "AGE"},
        {"start": 4, "end": 7, "text": "42세", "type": "AGE"},
        {"start": 8, "end": 11, "text": "45세", "type": "AGE"},
    ]
    anon, key = anonymize(text, spans)
    assert len(key) == 3, f"토큰이 유일하지 않음: {key}"
    assert restore(anon, key) == text, f"복원 실패: {restore(anon, key)!r}"
    print("[PASS] 9. 같은 연령대 3개 분리 라운드트립 통과")


def test_unknown_type_no_collision() -> None:
    """미등록 유형 여럿이 폴백 라벨을 공유해도 토큰은 유일해야 한다 (Codex P2-4)."""
    text = "가 나"
    spans = [
        {"start": 0, "end": 1, "text": "가", "type": "FOO"},
        {"start": 2, "end": 3, "text": "나", "type": "BAR"},
    ]
    anon, key = anonymize(text, spans)
    assert len(key) == 2, f"폴백 토큰 충돌: {key}"
    assert restore(anon, key) == text, f"복원 실패: {restore(anon, key)!r}"
    print("[PASS] 10. 미등록 유형 폴백 토큰 유일성 통과")


def test_age_huge_digits_fallback() -> None:
    """비정상적으로 긴 숫자열 AGE — 크래시 없이 폴백 토큰으로 라운드트립 (Codex 재검토 P2)."""
    text = "0" * 4400 + "48세"
    spans = [{"start": 0, "end": len(text), "text": text, "type": "AGE"}]
    anon, key = anonymize(text, spans)
    assert restore(anon, key) == text, "긴 숫자열 AGE 복원 실패"
    print("[PASS] 12. 긴 숫자열 AGE 폴백 통과")


def test_overlap_rejected() -> None:
    """겹치는 스팬은 조용히 절단하지 말고 거부한다 (label-schema §6, Codex P2-3)."""
    text = "서울역 광장"
    spans = [
        {"start": 0, "end": 3, "text": "서울역", "type": "LOC_FACILITY"},
        {"start": 2, "end": 6, "text": "역 광장", "type": "LOC_ADMIN"},
    ]
    with pytest.raises(ValueError, match="겹치는 스팬"):
        anonymize(text, spans)
    print("[PASS] 11. 겹침 스팬 거부 통과")


if __name__ == "__main__":
    print("=== kopl.c4_stage2 가명화·복원 검증 시작 ===")
    test_roundtrip_basic()
    test_same_decade_no_collision()
    test_korean_age_fallback()
    test_multi_same_type()
    test_all_canonical_types()
    test_empty_and_identical()
    test_token_literal_in_original()
    test_original_text_is_tokenlike()
    test_age_triple_same_decade()
    test_unknown_type_no_collision()
    test_age_huge_digits_fallback()
    test_overlap_rejected()
    print("=== [성공] c4_stage2 라운드트립 전 항목 통과 ===")
