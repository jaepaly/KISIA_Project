"""B·C·D 완성 후 여기로 교체한다. 부분 교체 가능 — 아직 안 온 함수는
mock에서 그대로 가져와 쓴다 (docs/roles/howto/e-integration.md §3).
"""

from __future__ import annotations

from .mock import contribution, specificity, stage2  # noqa: F401 — 아직 안 온 것은 목을 그대로 쓴다


def detect_spans(post: dict) -> dict:
    raise NotImplementedError(
        "c1 실제 모델 미연결 — kopl.c1_span 붙으면 여기서 predict() 호출로 교체")
