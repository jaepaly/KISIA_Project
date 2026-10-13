"""1단 BIO 추론의 순수 함수 — 라벨 목록 · 채널 순서 · 토큰 라벨 → 스팬 · 겹침 해소 · 점수 거르기.

``experiments/exp06-finetune`` 의 ``prepare_bio.py`` · ``train.py`` 에서 옮겼다(README W9 D 9번 · 동작 그대로).
학습 코드(``train.py`` · ``prepare_bio.py``)는 여기서 다시 가져다 쓴다 — 추론과 학습이 같은 함수를 쓰게.
torch · transformers 를 쓰지 않는다.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence


class SpanDecodeError(RuntimeError):
    """학습을 시작하기 전에 고쳐야 하는 입력·환경 오류. (``train.TrainError`` 와 같은 클래스)"""


TYPES = [
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
]
LABELS = ["O"] + [f"{prefix}-{span_type}" for span_type in TYPES for prefix in ("B", "I")]


def channel_sort_key(text_id: str) -> tuple[int, int | str]:
    if text_id == "title":
        return (0, 0)
    if text_id == "body":
        return (1, 0)
    if text_id.startswith("photo_caption:"):
        suffix = text_id.split(":", 1)[1]
        if suffix.isdigit():
            return (2, int(suffix))
        return (2, suffix)
    if text_id == "profile_bio":
        return (3, 0)
    return (4, text_id)


def decode_token_spans(
    offsets: Sequence[Sequence[int]], label_ids: Sequence[int], id2label: dict[int, str]
) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    current: list[Any] | None = None
    for (raw_start, raw_end), label_id in zip(offsets, label_ids):
        start, end = int(raw_start), int(raw_end)
        if start == end or int(label_id) == -100:
            continue
        tag = id2label[int(label_id)]
        if tag == "O":
            if current is not None:
                spans.append((current[0], current[1], current[2]))
                current = None
            continue
        prefix, span_type = tag.split("-", 1)
        if prefix == "B" or current is None or current[2] != span_type:
            if current is not None:
                spans.append((current[0], current[1], current[2]))
            current = [start, end, span_type]
        else:
            current[1] = end
    if current is not None:
        spans.append((current[0], current[1], current[2]))
    return spans


def span_iou(left: tuple[int, int, str], right: tuple[int, int, str]) -> float:
    intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return intersection / union if union else 0.0


def resolve_overlapping_spans(
    spans: Iterable[tuple[int, int, str]],
) -> set[tuple[int, int, str]]:
    """한 텍스트 채널 안에서 긴 스팬부터 창 간 충돌을 해소한다.

    동일한 스팬은 중복 제거하고, 유형이 달라도 한 글자 이상 겹치면 충돌로 본다.
    인접한 스팬은 분리한다. 창에서 예측하지 않은 경계를 만들지 않도록 스팬을
    합치거나 늘리지 않는다. 동률이면 start, end, type 순서로 정해 골드와
    무관하게 결정적으로 선택한다(계약 §6).
    """
    accepted: list[tuple[int, int, str]] = []
    for span in sorted(set(spans), key=lambda s: (-(s[1] - s[0]), s[0], s[1], s[2])):
        if span[0] < 0 or span[1] <= span[0]:
            raise SpanDecodeError(f"Invalid predicted span: {span}")
        if not any(span[0] < other[1] and other[0] < span[1] for other in accepted):
            accepted.append(span)
    return set(accepted)


def mean_span_score(values: Sequence[float]) -> float:
    if not values:
        raise SpanDecodeError("Predicted span has no token confidence scores.")
    return sum(values) / len(values)


def filter_span_predictions(pred_by_text: dict, span_scores: dict, min_span_score: float) -> dict:
    """겹침을 먼저 해소한 뒤 점수로 거른다. 골드 라벨은 선택에 영향을 주지 않는다.

    점수는 창별 예측 토큰 확률의 평균을 동일 스팬을 예측한 창 사이에서 다시
    평균한 값이며, 보정된 정확도가 아니다. 가장 긴 스팬이 임계값을 통과하지
    못해도 더 짧은 스팬을 다시 살리지 않는다.
    """
    if not 0 <= min_span_score <= 1:
        raise SpanDecodeError("--min-span-score must be between 0 and 1.")
    merged = {key: resolve_overlapping_spans(spans) for key, spans in pred_by_text.items()}
    if min_span_score == 0:
        return merged
    return {key: {span for span in spans
                  if mean_span_score(span_scores.get((key, span), [])) >= min_span_score}
            for key, spans in merged.items()}
