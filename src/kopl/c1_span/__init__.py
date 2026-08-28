"""c1_span: 1단 준식별자 스팬 탐지 패키지.

docs/contracts/span.schema.json 계약 및 docs/roles/howto/e-integration.md 준수.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .detector import SpanDetector, decode
from .mock import MockSpanDetector, predict_mock, predict_profile_mock
from .schema import (
    ALLOWED_LEVELS,
    ALLOWED_RECORD_TYPES,
    ALLOWED_SUBJECTS,
    ALLOWED_TYPES,
    SCHEMA_VERSION,
    TEXT_ID_PATTERN,
    create_span_record,
    format_output,
    format_span_id,
    normalize_nfc,
    sort_spans,
    span_sort_key,
    text_id_sort_key,
    validate_span_output,
)

__all__ = [
    "SCHEMA_VERSION",
    "ALLOWED_RECORD_TYPES",
    "ALLOWED_TYPES",
    "ALLOWED_LEVELS",
    "ALLOWED_SUBJECTS",
    "TEXT_ID_PATTERN",
    "SpanDetector",
    "MockSpanDetector",
    "decode",
    "predict",
    "predict_post",
    "predict_profile",
    "predict_mock",
    "predict_profile_mock",
    "create_span_record",
    "format_span_id",
    "format_output",
    "normalize_nfc",
    "text_id_sort_key",
    "span_sort_key",
    "sort_spans",
    "validate_span_output",
]

_GLOBAL_DETECTOR: Optional[SpanDetector] = None


def get_detector() -> Optional[SpanDetector]:
    """C1_MODEL_PATH 환경변수가 설정되어 있으면 SpanDetector 싱글톤을 로드합니다."""
    global _GLOBAL_DETECTOR
    if _GLOBAL_DETECTOR is None:
        model_path = os.getenv("C1_MODEL_PATH")
        if model_path and os.path.exists(model_path):
            _GLOBAL_DETECTOR = SpanDetector(model_dir=model_path)
    return _GLOBAL_DETECTOR


def predict(
    target: Any,
    post_id: Optional[str] = None,
    text_id: str = "body",
) -> Dict[str, Any]:
    """준식별자 스팬 탐지 통합 호출 함수.

    docs/roles/howto/e-integration.md §3 연동 규격:
    `from kopl.c1_span import predict as _c1`

    - 단일 텍스트 문자열: `predict("내용...", post_id="p1")`
    - 다중 채널 글 객체: `predict({"post_id": "p1", "body": "...", "title": "..."})`
    가중치 모델이 없거나 로드되지 않은 상태에서는 MockSpanDetector를 안전하게 폴백으로 사용합니다.
    """
    detector = get_detector()
    if detector is not None:
        if isinstance(target, dict):
            return detector.detect_post(target)
        return detector.detect(str(target), post_id=post_id, text_id=text_id)

    # 가중치가 준비되기 전(M1~M2 초기)에는 계약 규격의 목 결과를 반환
    return predict_mock(target, post_id=post_id, text_id=text_id)


def predict_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """다중 채널 글 객체 탐지 편의 함수."""
    return predict(post)


def predict_profile(persona_id: str, bio: str) -> Dict[str, Any]:
    """사용자 프로필 소개란(profile_bio) 단독 탐지 함수.

    스팬 식별자는 <persona_id>_bio_s<2자리> 로 부여되며, 글 단위 레코드와 철저히 분리됩니다 (label-schema §8-1, 규칙 10).
    """
    detector = get_detector()
    if detector is not None:
        return detector.detect_profile(persona_id, bio)
    return predict_profile_mock(persona_id, bio)
