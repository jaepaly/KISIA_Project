"""c1_span 골격 및 계약 무결성 자체 검증 스크립트.

실행:
    python -m kopl.c1_span.test_span
"""

import json
from pathlib import Path
from kopl.c1_span import (
    MockSpanDetector,
    predict,
    sort_spans,
    span_sort_key,
    text_id_sort_key,
    validate_span_output,
)


def test_sort_order() -> None:
    """label-schema.md §5-3 및 §8-1 정렬 순서 검증."""
    channels = [
        "profile_bio",
        "photo_caption:10",
        "photo_caption:2",
        "body",
        "title",
        "photo_caption:0",
    ]
    sorted_channels = sorted(channels, key=text_id_sort_key)
    expected = [
        "title",
        "body",
        "photo_caption:0",
        "photo_caption:2",
        "photo_caption:10",
        "profile_bio",
    ]
    assert sorted_channels == expected, f"채널 정렬 실패: {sorted_channels} != {expected}"
    print("[PASS] 1. text_id 정렬 순서 (photo_caption:10 이 :2 보다 뒤) 검증 통과")


def test_mock_detect_and_schema() -> None:
    """단일 텍스트 탐지 및 계약 스키마 검증."""
    text = "집 근처라 자주 가는 신갈저수지 조황입니다. 마흔여덟 되니 힘드네요."
    res = predict(text, post_id="test_post_01")

    # 1. 자체 시맨틱 검증
    errors = validate_span_output(res, texts={"body": text})
    assert not errors, f"단일 텍스트 검증 오류: {errors}"
    assert "dialect_hits" in res.get("flags", {}), "flags에 dialect_hits가 누락되었습니다"

    # 2. JSON Schema 검증 (파일 존재 시)
    schema_path = Path("docs/contracts/span.schema.json")
    if schema_path.exists():
        try:
            from jsonschema import Draft202012Validator
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)
            schema_errors = list(validator.iter_errors(res))
            assert not schema_errors, f"span.schema.json 계약 검증 실패: {schema_errors}"
            print("[PASS] 2. 단일 텍스트 탐지 docs/contracts/span.schema.json 통과")
        except ImportError:
            print("[WARN] jsonschema 미설치로 JSON Schema 파일 직접 검증은 건너뜀")
    else:
        print("[WARN] docs/contracts/span.schema.json 경로를 찾을 수 없음")


def test_multi_channel_post() -> None:
    """글 단위 다중 채널(title, body, photo_captions) 탐지 및 span_id 일괄 부여 검증.

    profile_bio는 글 단위 레코드에서 제외되어야 합니다 (규칙 10).
    """
    mock = MockSpanDetector()
    post = {
        "post_id": "P_20260827_01",
        "title": "동탄 사는 이야기",
        "body": "판교 회사 앞 카페에서 커피 한잔.",
        "photo_captions": [
            "첫째가 좋아하는 호수공원",
            "집 앞 풍경",
        ],
    }

    res = mock.detect_post(post)

    # 스키마 및 무결성 검증 (규칙 10 포함)
    errors = validate_span_output(res, is_post=True)
    assert not errors, f"다중 채널 검증 오류: {errors}"

    spans = res["spans"]
    assert len(spans) >= 3, f"스팬 검출 수 부족: {len(spans)}"

    # 글 단위 스팬에 profile_bio가 없어야 함 (규칙 10)
    assert not any(sp["text_id"] == "profile_bio" for sp in spans), "글 레코드에 profile_bio가 포함되어선 안 됨"

    # 정렬 및 span_id 검증 (<post_id>_s<2자리>)
    for idx, sp in enumerate(spans, start=1):
        expected_id = f"P_20260827_01_s{idx:02d}"
        assert sp["span_id"] == expected_id, f"span_id 불일치: {sp['span_id']} != {expected_id}"

    # 채널 순서 검증 (title -> body -> photo_caption:0 -> photo_caption:1)
    channel_orders = [text_id_sort_key(sp["text_id"]) for sp in spans]
    assert channel_orders == sorted(channel_orders), "채널 정렬 순서 불일치"

    print("[PASS] 3. 글 단위 다중 채널(title/body/photo_caption) 통합 탐지 및 규칙 10 검증 통과")


def test_profile_bio_separation() -> None:
    """사용자 프로필(profile_bio) 단독 탐지 및 span_id (<persona_id>_bio_sNN) 검증."""
    from kopl.c1_span import predict_profile

    persona_id = "D05"
    bio_text = "성수동 거주하는 30대 카페 매니저입니다."
    res = predict_profile(persona_id, bio_text)

    # 사용자 레코드로서 스키마 검증
    errors = validate_span_output(res, is_post=False)
    assert not errors, f"프로필 검증 오류: {errors}"

    spans = res["spans"]
    assert len(spans) >= 1, "프로필 스팬 검출 실패"

    # span_id 형식 검증: 글 ID(b03 등)가 없이 <persona_id>_bio_s<2자리> 여야 함!
    for idx, sp in enumerate(spans, start=1):
        expected_id = f"D05_bio_s{idx:02d}"
        assert sp["span_id"] == expected_id, f"span_id 형식 오류: {sp['span_id']} != {expected_id}"
        assert sp["text_id"] == "profile_bio"

    # 만약 글 레코드 검증기(is_post=True)로 돌리면 규칙 10으로 차단되는지 확인
    block_errors = validate_span_output(res, is_post=True)
    assert any("규칙10" in err for err in block_errors), "글 검증기에서 profile_bio가 차단되지 않음"

    print("[PASS] 4. 프로필(profile_bio) 사용자 단위 독립 탐지 및 <persona_id>_bio_sNN 검증 통과")


if __name__ == "__main__":
    print("=== kopl.c1_span 골격 및 계약 검증 시작 ===")
    test_sort_order()
    test_mock_detect_and_schema()
    test_multi_channel_post()
    test_profile_bio_separation()
    print("=== [성공] c1_span 골격의 모든 검증을 완벽히 통과했습니다! ===")
