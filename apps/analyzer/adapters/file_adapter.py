"""수동 업로드 경로 — M4 외적 타당성 검증에서 실블로거 글을 여기로 받는다.

⚠️ 업로드된 내용은 메모리에서만 다루고 디스크에 쓰지 않는다. 분석이 끝나면
버린다 (§6 데이터 원칙 — 분석 후 즉시 파기).

입력 상한 (A4) — 점검 시간은 글자 수에 거의 비례한다(서버 약 1.45ms/자). 상한이 없으면 1MB 파일 하나가
서버를 몇 분 붙잡는다. 시연 데이터에 넉넉히 맞췄다 (Veilo 계정 최대 30편 · 가장 긴 계정 E15 약 97,000자 ·
글 하나 최대 3,754자 · 캡션 글당 최대 2개 · 26자 — 10/14 data/interim/sns.db 실측).
글쓰기 화면은 「내 계정 글 + 쓰는 글」을 한 번에 보내므로 가장 긴 계정에 초안이 붙어도 들어가야 한다.
"""

from __future__ import annotations

import json
import re
import uuid

MAX_POSTS = 200            # 글 수 (.txt 는 줄 수)
MAX_TOTAL_CHARS = 150_000  # 제목 · 본문 · 캡션 합 — E15(약 97,000자) + 초안의 1.5배 남짓 · 서버에서 약 3~4분
MAX_BODY_CHARS = 20_000    # 글 하나 본문
MAX_TITLE_CHARS = 300
MAX_CAPTIONS = 10          # 글 하나의 사진 캡션 수
MAX_CAPTION_CHARS = 1_000
MAX_ID_CHARS = 100         # post_id
MAX_META_CHARS = 200       # 위치 태그 · 닉네임 · 작성 날짜 · 시각
_USER_REF = re.compile(r"u_[0-9a-f]{8,64}")


class UploadError(ValueError):
    """화면에 그대로 보이는 고정 문구 + 상태 코드 (400 형식 오류 · 413 너무 큼)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _opt_str(v, limit: int, what: str) -> None:
    if v is None:
        return
    if not isinstance(v, str):
        raise UploadError(f"{what} 은(는) 문자열이어야 합니다")
    if len(v) > limit:
        raise UploadError(f"{what} 이(가) 너무 깁니다 ({limit:,}자 이하)", 413)


def _caption(ph):
    return ph.get("caption") if isinstance(ph, dict) else ph


def validate_posts(posts) -> int:
    """export 형식 posts 를 검사하고 글자 수 합을 돌려준다. 어긋나면 UploadError (500 대신 4xx)."""
    if not isinstance(posts, list):
        raise UploadError("posts 는 글 목록(배열)이어야 합니다")
    if len(posts) > MAX_POSTS:
        raise UploadError(f"글이 너무 많습니다 ({MAX_POSTS}편 이하)", 413)
    total = 0
    for p in posts:
        if not isinstance(p, dict):
            raise UploadError("posts 의 각 글은 객체여야 합니다")
        pid = p.get("post_id")
        if not isinstance(pid, str) or not pid:
            raise UploadError("모든 글에 post_id(문자열)가 있어야 합니다")
        if len(pid) > MAX_ID_CHARS:
            raise UploadError(f"post_id 가 너무 깁니다 ({MAX_ID_CHARS}자 이하)")
        _opt_str(p.get("title"), MAX_TITLE_CHARS, "제목")
        _opt_str(p.get("body"), MAX_BODY_CHARS, "본문")
        _opt_str(p.get("post_date"), MAX_META_CHARS, "post_date")
        photos = p.get("photos")
        if photos is not None:
            if not isinstance(photos, list):
                raise UploadError("photos 는 배열이어야 합니다")
            if len(photos) > MAX_CAPTIONS:
                raise UploadError(f"사진 캡션이 너무 많습니다 (글 하나에 {MAX_CAPTIONS}개 이하)", 413)
            for ph in photos:
                if not isinstance(ph, (dict, str)):
                    raise UploadError("photos 의 각 항목은 {\"caption\": 문자열} 이어야 합니다")
                _opt_str(_caption(ph), MAX_CAPTION_CHARS, "사진 캡션")
        meta = p.get("activity_meta")
        if meta is not None:
            if not isinstance(meta, dict):
                raise UploadError("activity_meta 는 객체여야 합니다")
            for key in ("geo_tag", "nickname", "post_time"):
                _opt_str(meta.get(key), MAX_META_CHARS, key)
        total += len(p.get("title") or "") + len(p.get("body") or "")
        total += sum(len(_caption(ph) or "") for ph in photos or [])
        if total > MAX_TOTAL_CHARS:
            raise UploadError(f"글이 너무 깁니다 (모두 합쳐 {MAX_TOTAL_CHARS:,}자 이하)", 413)
    return total


def load_from_bytes(content: bytes, filename: str) -> dict:
    """.txt(줄마다 글 한 편) 또는 .json(export 형식과 동일) 둘 다 받는다."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UploadError("UTF-8 텍스트 파일만 받습니다") from exc

    if filename.lower().endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise UploadError("JSON 형식이 올바르지 않습니다") from exc
        if not isinstance(data, dict) or "posts" not in data:
            raise UploadError("json 업로드는 export 형식(posts 배열)이어야 한다")
        validate_posts(data["posts"])
        ref = data.get("user_ref")
        if ref is None:
            data["user_ref"] = "u_" + uuid.uuid4().hex[:12]
        elif not isinstance(ref, str) or not _USER_REF.fullmatch(ref):
            raise UploadError("user_ref 형식이 올바르지 않습니다 (u_ + 16진수)")
        return data

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    user_ref = "u_" + uuid.uuid4().hex[:12]  # 계약 형식 (^u_[0-9a-f]{8,}$) — 「u_upload00」은 16진수가 아니라 LOO 가 거부한다
    export = {
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
    validate_posts(export["posts"])
    return export
