"""c1_span 스키마 및 상수 정의.

docs/contracts/span.schema.json (v1.0) 및 docs/contracts/label-schema.md 준수.
- 문자 offset 기준 (0-based, [start, end) 반열림, NFC 정규화)
- 10개 정본 유형 (AGE, SEX, LOC_ADMIN, LOC_FACILITY, REL_HOME, REL_WORK, JOB, FAM, COMMUTE, INCOME)
- 3개 등급 (explicit, implicit, inferential)
- 3개 주체 귀속 (self, other, unknown)
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION: str = "1.0"

# label-schema.md §3-2: 정본 10종
ALLOWED_TYPES: Tuple[str, ...] = (
    "AGE",
    "SEX",
    "LOC_ADMIN",
    "LOC_FACILITY",
    "REL_HOME",
    "REL_WORK",
    "JOB",
    "FAM",
    "COMMUTE",
    "INCOME",
)

# label-schema.md §4-1: 3등급
ALLOWED_LEVELS: Tuple[str, ...] = (
    "explicit",
    "implicit",
    "inferential",
)

# label-schema.md §4-2: 귀속 3종
ALLOWED_SUBJECTS: Tuple[str, ...] = (
    "self",
    "other",
    "unknown",
)

# span.schema.json: text_id 정규식
TEXT_ID_PATTERN: str = r"^(title|body|profile_bio|photo_caption:\d+)$"
_TEXT_ID_RE = re.compile(TEXT_ID_PATTERN)


def normalize_nfc(text: str) -> str:
    """NFC 정규화 적용 (span.schema.json 제약 1)."""
    return unicodedata.normalize("NFC", text)


def format_span_id(post_id: str, index: int, text_id: str = "body") -> str:
    """label-schema.md §8-1 / span.schema.json:
    <post_id>_s<2자리>. 프로필은 <persona_id>_bio_s<2자리>.
    """
    if text_id == "profile_bio":
        return f"{post_id}_bio_s{index:02d}"
    return f"{post_id}_s{index:02d}"


def create_span_record(
    span_id: str,
    text_id: str,
    start: int,
    end: int,
    text: str,
    type_: str,
    level: str = "inferential",
    subject: str = "self",
    score: Optional[float] = None,
) -> Dict[str, Any]:
    """span.schema.json의 단일 스팬 객체 생성."""
    if not _TEXT_ID_RE.match(text_id):
        raise ValueError(f"유효하지 않은 text_id: {text_id} (패턴: {TEXT_ID_PATTERN})")

    if type_ not in ALLOWED_TYPES:
        raise ValueError(f"허용되지 않은 스팬 유형: {type_}. 허용값: {ALLOWED_TYPES}")

    if level not in ALLOWED_LEVELS:
        raise ValueError(f"허용되지 않은 레벨: {level}. 허용값: {ALLOWED_LEVELS}")

    if subject not in ALLOWED_SUBJECTS:
        raise ValueError(f"허용되지 않은 주체: {subject}. 허용값: {ALLOWED_SUBJECTS}")

    if start < 0 or end <= start:
        raise ValueError(f"유효하지 않은 offset: start={start}, end={end} (0 <= start < end 필요)")

    record: Dict[str, Any] = {
        "span_id": span_id,
        "text_id": text_id,
        "start": start,
        "end": end,
        "text": text,
        "type": type_,
        "level": level,
        "subject": subject,
    }
    if score is not None:
        record["score"] = round(float(score), 4)

    return record


def format_output(
    post_id: str,
    model_version: str,
    spans: List[Dict[str, Any]],
    flags: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """span.schema.json 최상위 출력 객체 구성."""
    output: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "model_version": model_version,
        "post_id": post_id,
        "spans": spans,
    }
    if flags is not None:
        output["flags"] = flags
    return output


def text_id_sort_key(text_id: str) -> Tuple[int, int]:
    """label-schema.md §5-3 확정 텍스트 채널 정렬 키.

    순서: title → body → photo_caption:0 → … → photo_caption:N → profile_bio
    색인은 숫자로 정렬 (photo_caption:10 은 photo_caption:2 보다 뒤).
    """
    if text_id == "title":
        return (0, 0)
    if text_id == "body":
        return (1, 0)
    if text_id.startswith("photo_caption:"):
        parts = text_id.split(":", 1)
        try:
            return (2, int(parts[1]))
        except ValueError:
            return (2, 999999)
    if text_id == "profile_bio":
        return (3, 0)
    return (99, 0)


def span_sort_key(span: Dict[str, Any]) -> Tuple[Tuple[int, int], int, int]:
    """label-schema.md §8-1: 텍스트 정렬 순서 → start 오름차순."""
    tid = span.get("text_id", "body")
    s = span.get("start", 0)
    e = span.get("end", 0)
    return (text_id_sort_key(tid), s, e)


def sort_spans(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """스팬 목록을 계약 규격(텍스트 채널 순서 → start 오름차순)으로 정렬합니다."""
    return sorted(spans, key=span_sort_key)


def validate_span_output(
    output: Dict[str, Any],
    texts: Optional[Dict[str, str]] = None,
) -> List[str]:
    """span.schema.json 및 시맨틱 제약 검증 (0 <= start < end, 같은 text_id 겹침 금지, 텍스트 일치).

    오류가 없으면 빈 리스트 []를 반환합니다.
    """
    errors: List[str] = []

    # 1. 최상위 필수 키
    for k in ("schema_version", "model_version", "post_id", "spans"):
        if k not in output:
            errors.append(f"필수 최상위 필드 누락: {k}")

    if output.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 불일치: 기대값 '{SCHEMA_VERSION}', 실제값 '{output.get('schema_version')}'")

    spans = output.get("spans", [])
    if not isinstance(spans, list):
        errors.append(f"spans 필드는 list여야 합니다 (현재: {type(spans)})")
        return errors

    # 2. 개별 스팬 검증 및 겹침 검사
    spans_by_channel: Dict[str, List[Dict[str, Any]]] = {}

    for idx, sp in enumerate(spans):
        # 필수 필드
        for req in ("span_id", "text_id", "start", "end", "text", "type", "level", "subject"):
            if req not in sp:
                errors.append(f"spans[{idx}] 필수 필드 누락: {req}")

        tid = sp.get("text_id", "")
        if not _TEXT_ID_RE.match(tid):
            errors.append(f"spans[{idx}] 유효하지 않은 text_id: '{tid}'")

        st, ed = sp.get("start", -1), sp.get("end", -1)
        if st < 0 or ed <= st:
            errors.append(f"spans[{idx}] 잘못된 offset: start={st}, end={ed} (0 <= start < end 필요)")

        typ = sp.get("type", "")
        if typ not in ALLOWED_TYPES:
            errors.append(f"spans[{idx}] 허용되지 않은 type: '{typ}'")

        lvl = sp.get("level", "")
        if lvl not in ALLOWED_LEVELS:
            errors.append(f"spans[{idx}] 허용되지 않은 level: '{lvl}'")

        subj = sp.get("subject", "")
        if subj not in ALLOWED_SUBJECTS:
            errors.append(f"spans[{idx}] 허용되지 않은 subject: '{subj}'")

        # 텍스트 일치 검사 (texts 제공 시)
        if texts and tid in texts:
            channel_text = texts[tid]
            expected_text = channel_text[st:ed]
            actual_text = sp.get("text", "")
            if expected_text != actual_text:
                errors.append(
                    f"spans[{idx}] 텍스트 불일치 (text_id='{tid}'): "
                    f"기대값 '{expected_text}', 실제값 '{actual_text}'"
                )

        spans_by_channel.setdefault(tid, []).append(sp)

    # 3. 같은 text_id 안에서 겹침 금지 검사
    for tid, ch_spans in spans_by_channel.items():
        sorted_ch = sorted(ch_spans, key=lambda x: (x.get("start", 0), x.get("end", 0)))
        for i in range(len(sorted_ch) - 1):
            cur, nxt = sorted_ch[i], sorted_ch[i + 1]
            if nxt.get("start", 0) < cur.get("end", 0):
                errors.append(
                    f"같은 text_id('{tid}') 내 스팬 겹침 발견: "
                    f"[{cur.get('start')}, {cur.get('end')}) '{cur.get('text')}' vs "
                    f"[{nxt.get('start')}, {nxt.get('end')}) '{nxt.get('text')}'"
                )

    return errors
