"""직접 식별 정보 — 계정 링크 · 이메일 · 전화번호 · @아이디.

준식별자(나이·지역·직업)와 달리 **하나만으로 글쓴이 계정이나 연락처에 바로 닿는다.** k(같은 조건의 사람 수)로
잴 대상이 아니라 「보이면 지운다」가 답이라, 스팬 계약(label-schema 10유형) 밖에서 따로 찾는다.

계기: 내부 시험(10/8)에서 외부 LLM 검토자는 본문에 남은 블로그 글 주소를 「가장 강한 식별 요소」로 꼽았는데,
우리 도구는 유형이 없어 아예 보지 못했고 위험도가 낮아 「추가 조치 불필요」로 안내했다.

    from kopl.c4_stage2.links import find_direct_identifiers
    find_direct_identifiers({"title": "...", "body": "...", "photo_caption:0": "..."})
    → [{"text_id", "start", "end", "kind", "label", "value"}, ...]   # 오프셋은 파이썬 문자(코드포인트) 단위

kind — ``account_url`` 개인 계정 · 글로 이어지는 주소 / ``url`` 그 밖의 주소 / ``email`` / ``phone`` / ``handle`` @아이디
``strong`` — url 만 False. 일반 참고 링크는 계정에 닿지 않으므로 「먼저 지울 것」이 아니라 확인 권고로 낮춰 보여 준다
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# 주소 — 스킴이 있거나 www. 로 시작하거나, 아는 플랫폼 도메인이 그대로 나온 것만. 「a.b」 같은 아무 점 단어는 잡지 않는다
_PLATFORM_HOSTS = (
    r"(?:m\.)?blog\.naver\.com|naver\.me|(?:m\.)?cafe\.naver\.com|(?:www\.)?instagram\.com|instagr\.am"
    r"|(?:www\.)?(?:twitter|x)\.com|(?:www\.|m\.)?facebook\.com|fb\.me|(?:www\.|m\.)?youtube\.com|youtu\.be"
    r"|(?:www\.)?tiktok\.com|brunch\.co\.kr|velog\.io|(?:www\.)?github\.com|(?:www\.)?threads\.(?:net|com)"
    r"|open\.kakao\.com|pf\.kakao\.com|story\.kakao\.com|[a-z0-9-]+\.tistory\.com|(?:www\.)?linkedin\.com"
)
# 경계는 영숫자(ASCII)로만 본다 — 파이썬 \w 는 한글도 포함해 「주소blog.naver.com/…」 「abc@x.com으로」를 놓친다 (Codex 10/8)
_URL = re.compile(
    r"(?<![A-Za-z0-9@./])(?:(?:https?://|www\.)[^\s<>\"'()\[\]{}가-힣]+|(?:" + _PLATFORM_HOSTS + r")/[^\s<>\"'()\[\]{}가-힣]*)",
    re.IGNORECASE)
# 계정·글로 이어지는 주소 — 플랫폼 뒤에 아이디(또는 @아이디) 경로가 있거나, 서브도메인 자체가 아이디(티스토리)
_ACCOUNT = re.compile(
    r"^(?:https?://)?(?:"
    r"(?:m\.)?blog\.naver\.com/[\w.-]+|naver\.me/\w+|(?:m\.)?cafe\.naver\.com/[\w.-]+"
    r"|(?:www\.)?instagram\.com/(?!p/|explore/|reel/)[\w.]+|instagr\.am/[\w.]+"
    r"|(?:www\.)?(?:twitter|x)\.com/(?!search|hashtag|i/)\w+|(?:www\.|m\.)?facebook\.com/(?!groups/|events/)[\w.]+|fb\.me/\w+"
    r"|(?:www\.|m\.)?youtube\.com/(?:@[\w.-]+|channel/|c/|user/)|(?:www\.)?tiktok\.com/@[\w.]+"
    r"|brunch\.co\.kr/@[\w.-]+|velog\.io/@[\w.-]+|(?:www\.)?github\.com/[\w-]+|(?:www\.)?threads\.(?:net|com)/@[\w.]+"
    r"|open\.kakao\.com/|pf\.kakao\.com/|story\.kakao\.com/[\w.-]+|(?:www\.)?linkedin\.com/in/"
    r"|(?!www\.)[a-z0-9-]+\.tistory\.com)",
    re.IGNORECASE)
_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![A-Za-z0-9-])")
# 휴대전화 — 010-1234-5678 · 010 1234 5678 · 01012345678. 유선·대표번호(1588 등)는 개인 식별이 약해 넣지 않는다
# 「010 - 1234 - 5678」 「010)1234-5678」 「+82 10-1234-5678」도 (Codex 10/8)
# 영숫자 식별자 안(「주문번호 A01012345678B」)은 아니다 · 「+82 (10) …」 「+82 (0)10 …」도 (Codex 10/8 2차)
_PHONE = re.compile(r"(?<![A-Za-z0-9+])(?:\+82[-.\s]*(?:\(0\)\s*)?\(?0?1[016789]\)?|01[016789])"
                    r"\s*[-.)]?\s*\d{3,4}\s*[-.]?\s*\d{4}(?![A-Za-z0-9])")
# @아이디 — 영문으로 시작하는 3자 이상. 앞이 글자·숫자면(이메일 · 「1@2」) 아니다. 「@ 3시」처럼 띄우면 아니다
_HANDLE = re.compile(r"(?<![A-Za-z0-9_@.])@([A-Za-z][A-Za-z0-9._]{2,29})(?![A-Za-z0-9_@])")
_TRAILING = ".,!?…·)]}>\"'"
# 플랫폼의 시스템 페이지 — 첫 경로가 이것이면 계정이 아니다 (「instagram.com/accounts/login」 「github.com/topics/python」 · Codex 10/8 2차)
_RESERVED_PATHS = {
    "accounts", "account", "login", "logout", "signup", "join", "explore", "about", "topics", "features", "settings",
    "search", "hashtag", "help", "privacy", "policies", "legal", "terms", "marketplace", "home", "share", "watch",
    "results", "p", "reel", "reels", "tags", "groups", "events", "i", "intent", "notifications", "messages", "direct",
    "orgs", "organizations", "trending", "collections", "sponsors", "pricing", "enterprise", "stories", "tv",
}

_LABEL = {
    "account_url": "계정·글로 바로 이어지는 주소",
    "url": "링크",
    "email": "이메일 주소",
    "phone": "휴대전화 번호",
    "handle": "SNS 아이디",
}


def _strip_trailing(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1] in _TRAILING:
        end -= 1
    return end


def _is_account(url: str) -> bool:
    if not _ACCOUNT.match(url):
        return False
    rest = re.sub(r"^(?:https?://)?[^/]+", "", url)  # 호스트 뒤 경로
    first = rest.lstrip("/").split("/", 1)[0].split("?", 1)[0].lower()
    return first not in _RESERVED_PATHS


def find_in_text(text: str) -> list[dict[str, Any]]:
    """한 채널의 직접 식별 정보. 겹치면 먼저 찾은 것(주소 > 이메일 > 전화 > 아이디)을 남긴다."""
    found: list[dict[str, Any]] = []
    taken: list[tuple[int, int]] = []

    def add(start: int, end: int, kind: str) -> None:
        if end <= start or any(start < e and s < end for s, e in taken):
            return
        taken.append((start, end))
        found.append({"start": start, "end": end, "kind": kind, "label": _LABEL[kind], "value": text[start:end],
                      "strong": kind != "url"})

    for m in _URL.finditer(text):
        end = _strip_trailing(text, m.start(), m.end())
        value = text[m.start():end]
        add(m.start(), end, "account_url" if _is_account(value) else "url")
    for m in _EMAIL.finditer(text):
        add(m.start(), m.end(), "email")
    for m in _PHONE.finditer(text):
        add(m.start(), m.end(), "phone")
    for m in _HANDLE.finditer(text):
        add(m.start(), m.end(), "handle")
    return sorted(found, key=lambda f: f["start"])


def find_direct_identifiers(texts: Mapping[str, str | None]) -> list[dict[str, Any]]:
    """채널별 원문({text_id: 글}) → 직접 식별 정보 목록. text_id 를 붙여 돌려준다."""
    out: list[dict[str, Any]] = []
    for text_id, text in texts.items():
        if not text:
            continue
        out.extend({"text_id": text_id, **f} for f in find_in_text(text))
    return out
