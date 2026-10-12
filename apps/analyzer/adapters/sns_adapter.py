"""가상 SNS 서비스의 내보내기 API를 계약 형식으로 가져온다.

⚠️ 경계 — 이 파일은 HTTP 요청만 한다. 저장소나 내부 모듈을 직접 import하지
않는다 (scripts/check_boundary.sh 가 검사한다).
"""

from __future__ import annotations

import requests

DEFAULT_BASE = "http://localhost:3000"


def load(user_ref: str, base: str = DEFAULT_BASE, session_id: str | None = None) -> dict:
    # 가상 SNS 는 방문자별 사본을 쓴다 — 브라우저가 보낸 세션 ID 를 넘겨야 그 사람이 본 글을 읽는다
    headers = {"X-Veilo-Session": session_id} if session_id else {}
    r = requests.get(f"{base}/api/export/{user_ref}", timeout=5, headers=headers)
    r.raise_for_status()
    return r.json()


# 두 번째 창구 — 계정 찾기 (sns-minimal-spec §6). 화면이 Veilo 를 직접 부르지 않고 여기를 거친다
AUTHOR_FIELDS = ("user_ref", "nickname", "n_posts")


def search_authors(q: str, base: str = DEFAULT_BASE, session_id: str | None = None) -> list[dict]:
    headers = {"X-Veilo-Session": session_id} if session_id else {}
    r = requests.get(f"{base}/api/authors", params={"q": q}, timeout=5, headers=headers)
    r.raise_for_status()
    # 계약 밖 필드가 와도 화면까지 흘리지 않는다
    return [{k: a.get(k) for k in AUTHOR_FIELDS} for a in r.json()]
