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
