"""직접 식별 정보 탐지 — 계정 링크 · 이메일 · 전화 · @아이디 (합성 문장만).

실행:
    python -m pytest src/kopl/c4_stage2/test_links.py -v
"""

import pytest

from kopl.c4_stage2.links import find_direct_identifiers, find_in_text


def _kinds(text):
    return [(f["kind"], f["value"]) for f in find_in_text(text)]


@pytest.mark.parametrize("text,expected", [
    ("지난 글은 https://blog.naver.com/abc_123/223456789012 에 있어요", [("account_url", "https://blog.naver.com/abc_123/223456789012")]),
    ("관련 글(blog.naver.com/abc_123)도 보세요.", [("account_url", "blog.naver.com/abc_123")]),
    ("인스타 www.instagram.com/my.daily_log 놀러 오세요!", [("account_url", "www.instagram.com/my.daily_log")]),
    ("https://abc-diary.tistory.com/42 참고", [("account_url", "https://abc-diary.tistory.com/42")]),
    ("유튜브 https://youtube.com/@cookinglog 구독", [("account_url", "https://youtube.com/@cookinglog")]),
    ("오픈채팅 https://open.kakao.com/o/sAbCdEf 로 문의", [("account_url", "https://open.kakao.com/o/sAbCdEf")]),
    ("https://naver.me/xYz123 링크", [("account_url", "https://naver.me/xYz123")]),
])
def test_account_urls(text, expected):
    assert _kinds(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("레시피는 https://www.example.com/recipe/12 참고했어요.", [("url", "https://www.example.com/recipe/12")]),
    ("인스타 해시태그 https://www.instagram.com/explore/tags/cafe 구경", [("url", "https://www.instagram.com/explore/tags/cafe")]),
    ("유튜브 https://youtu.be/dQw4w9WgXcQ 영상", [("url", "https://youtu.be/dQw4w9WgXcQ")]),  # 영상 하나 — 계정은 아니다
])
def test_other_urls_are_lower_kind(text, expected):
    assert _kinds(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("문의는 my.name+blog@gmail.com 으로", [("email", "my.name+blog@gmail.com")]),
    ("연락처 010-1234-5678 남겨요", [("phone", "010-1234-5678")]),
    ("번호는 01012345678 이에요", [("phone", "01012345678")]),
    ("인스타 @daily_log.kr 팔로우", [("handle", "@daily_log.kr")]),
])
def test_email_phone_handle(text, expected):
    assert _kinds(text) == expected


@pytest.mark.parametrize("text", [
    "오늘 3.5km 걸었다. 점수는 4.5점.",
    "가격은 12,000원이고 1588-1234 로 예약했다",        # 대표번호는 개인 식별이 약하다
    "회의는 @ 3시에 시작",                               # 띄운 @ 는 아이디가 아니다
    "출근 18일차 · 26.09.03",
    "파일명은 report.final.docx 였다",                   # 점 들어간 단어 — 스킴·플랫폼이 없으면 주소로 안 본다
    "블로그 이웃 신청 환영해요",
    "2024년 010호실",
    "주문번호 A01012345678B 확인",                       # 영숫자 식별자 안의 숫자
    "2024 10 08 에 갔다",
])
def test_no_false_positives(text):
    assert find_in_text(text) == []


@pytest.mark.parametrize("text,expected", [
    ("주소blog.naver.com/abc_123 참고", [("account_url", "blog.naver.com/abc_123")]),
    ("메일은 abc@example.com으로 주세요", [("email", "abc@example.com")]),
    ("이메일abc@example.com", [("email", "abc@example.com")]),
    ("인스타@daily_log 팔로우", [("handle", "@daily_log")]),
    ("제 계정은 @daily_log입니다", [("handle", "@daily_log")]),
    ("https://m.blog.naver.com/abc_123에서 봤어요", [("account_url", "https://m.blog.naver.com/abc_123")]),
])
def test_hangul_boundaries(text, expected):
    """한글이 바로 붙어도 잡고, 한글을 끌어들이지 않는다 (Codex 10/8)"""
    assert _kinds(text) == expected


@pytest.mark.parametrize("text", ["010 - 1234 - 5678", "010)1234-5678", "+82 10-1234-5678", "+821012345678", "010.1234.5678",
                                  "+82 (10) 1234-5678", "+82 (0)10 1234 5678", "(010) 1234-5678"])
def test_phone_variants(text):
    assert [k for k, _ in _kinds(text)] == ["phone"]


@pytest.mark.parametrize("url", ["https://www.instagram.com/accounts/login/", "https://github.com/topics/python",
                                 "https://x.com/home", "https://www.facebook.com/help/123"])
def test_platform_system_pages_are_plain_links(url):
    assert _kinds(f"{url} 참고") == [("url", url)]


def test_plain_link_is_not_strong():
    assert [f["strong"] for f in find_in_text("레시피 https://www.example.com/recipe 와 blog.naver.com/abc")] == [False, True]


def test_email_is_not_also_a_handle_and_trailing_punct_is_cut():
    assert _kinds("메일(abc@naver.com).") == [("email", "abc@naver.com")]
    assert _kinds("링크: https://blog.naver.com/abc.") == [("account_url", "https://blog.naver.com/abc")]


def test_offsets_are_codepoints_and_channels_are_kept():
    title = "😀 제목"
    body = "이모지 뒤 😀 blog.naver.com/abc 와 010-1111-2222"
    out = find_direct_identifiers({"title": title, "body": body, "photo_caption:0": None})
    assert [(f["text_id"], f["kind"]) for f in out] == [("body", "account_url"), ("body", "phone")]
    for f in out:
        assert body[f["start"]:f["end"]] == f["value"]
