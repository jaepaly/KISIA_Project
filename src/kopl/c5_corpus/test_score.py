"""문장 분리기 검증 — 종결어미 뒤 자모, 그리고 기존 동작 회귀.

실행:
    python -m kopl.c5_corpus.test_score
"""

import json
from pathlib import Path

from kopl.c5_corpus.score import carded_metrics, compare_declared, post_metrics


def sents(body: str) -> int:
    return post_metrics(body)["문장수"]


def test_jamo_is_boundary() -> None:
    """음절에 붙은 자모 이모티콘은 문장 끝이다."""
    assert sents("혼자 살짝 신났음ㅠ 출구까지 잘 오길래 두드렸음ㅠ") == 2
    assert sents("동전을 또 넣었어요ㅠ 이번에는 배를 꽉 잡았거든요.") == 2
    assert sents("빙글 돌더니 제자리로 착 내려감ㅠ\n약 올리는 솜씨만 좋았다네요.") == 2
    # 종결어미 목록에 없는 명사형 종결도 자모가 있으면 끊긴다
    assert sents("앞치마 냄새 밴 채로 버스 탐ㅋㅋ 뉴타운 쪽에서 내렸다.") == 2


def test_jamo_at_body_end() -> None:
    """자모로 본문이 끝나도 마지막 문장이 잘린다."""
    assert sents("한 번만 더 하면 될 것 같았음. 결국 또 놓침ㅠ") == 2
    assert sents("진짜 딱 코앞이었음ㅋㅋ") == 1


def test_ellipsis_unchanged() -> None:
    """말줄임표는 문장 경계가 아니다 — 기존 동작 회귀."""
    assert sents("커피를 샀는데... 오늘따라 줄이 길었다.") == 1
    assert sents("나갔다... 커피 샀다...") == 2


def test_ending_and_period_unchanged() -> None:
    """홑마침표·종결어미 분리는 그대로다 — 기존 동작 회귀."""
    assert sents("아침에 나갔다. 저녁에 들어왔다.") == 2
    assert sents("비가 왔어요 우산을 안 챙겼네요") == 2


def test_noun_ending_without_jamo_unchanged() -> None:
    """자모가 없으면 종결어미 목록대로다 — 「지금」 「사람」 이 끊기면 안 된다."""
    assert sents("지금 사람 처럼 보였다.") == 1
    assert sents("가방을 들고 나감 그리고 버스를 탔다") == 1


def test_jamo_count_not_affected() -> None:
    """문장 분리에서 자모를 삼켜도 자모이모티콘 집계는 본문 기준이라 그대로다."""
    m = post_metrics("혼자 살짝 신났음ㅠ 결국 또 놓침ㅠ")
    assert m["자모이모티콘"] == 2
    assert m["문장수"] == 2



def test_card_axes_loaded_as_package() -> None:
    """`python -m kopl.c5_corpus.score --cards` 에서 카드 근거가 조용히 빠지지 않는다.

    예전에는 `from validate import` 가 패키지 실행에서 실패하고 예외를 삼켜 carded=None 이 됐다
    → 「카드 근거 없음」 표시가 전부 사라졌다 (W9 Codex 검토)."""
    root = Path(__file__).resolve().parents[3]
    pj = json.loads((root / "data/corpus/v0/personas/A01.json").read_text(encoding="utf-8-sig"))
    carded = carded_metrics(pj, root / "data/realism/cards")
    assert "문장길이_평균" in carded          # A01 의 카드 S14 에 문장 길이 근거가 있다
    out = compare_declared({"문장길이_평균": 23.0, "이모지": 1.0}, {"문장길이_평균": 25, "이모지": 0}, carded)
    assert any("이모지" in l and "카드 근거 없음" in l for l in out)
    assert not any("문장길이_평균" in l and "카드 근거 없음" in l for l in out)

if __name__ == "__main__":
    test_jamo_is_boundary()
    print("[PASS] 음절에 붙은 자모 → 문장 경계")

    test_jamo_at_body_end()
    print("[PASS] 자모로 본문이 끝날 때")

    test_ellipsis_unchanged()
    print("[PASS] 말줄임표는 경계가 아니다 (회귀)")

    test_ending_and_period_unchanged()
    print("[PASS] 홑마침표·종결어미 분리 (회귀)")

    test_noun_ending_without_jamo_unchanged()
    print("[PASS] 자모 없는 ㅁ받침은 안 끊는다")

    test_jamo_count_not_affected()
    print("[PASS] 자모이모티콘 집계 불변")

    test_card_axes_loaded_as_package()
    print("[PASS] 카드 근거 축 — 패키지 실행에서도 읽힌다")
