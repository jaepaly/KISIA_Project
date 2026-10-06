"""수동 업로드 경로 — M4 외적 타당성 검증에서 실블로거 글을 여기로 받는다.

⚠️ 업로드된 내용은 메모리에서만 다루고 디스크에 쓰지 않는다. 분석이 끝나면
버린다 (§6 데이터 원칙 — 분석 후 즉시 파기).
"""

from __future__ import annotations

import json
import uuid


def load_from_bytes(content: bytes, filename: str) -> dict:
    """.txt(줄마다 글 한 편) 또는 .json(export 형식과 동일) 둘 다 받는다."""
    text = content.decode("utf-8")

    if filename.lower().endswith(".json"):
        data = json.loads(text)
        if "posts" not in data:
            raise ValueError("json 업로드는 export 형식(posts 배열)이어야 한다")
        return data

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    user_ref = "u_" + uuid.uuid4().hex[:12]  # 계약 형식 (^u_[0-9a-f]{8,}$) — 「u_upload00」은 16진수가 아니라 LOO 가 거부한다
    return {
        "schema_version": "1.0",
        "user_ref": user_ref,
        "nickname": None,
        "profile_bio": None,
        "posts": [{
            "post_id": f"upload_{i:03d}",
            "user_ref": user_ref,
            "title": None,
            "body": line,
            "photos": [],
            "activity_meta": {"nickname": None, "geo_tag": None, "post_time": None},
        } for i, line in enumerate(lines)],
    }
