"""엔진 스위치. 환경변수 하나로 목/실제를 바꾼다 (docs/roles/howto/e-integration.md §3)."""

from __future__ import annotations

import os

if os.getenv("ENGINE_MODE", "mock") == "real":
    from .real import conditions, contribution, detect_spans, per_post_k, specificity, stage2
else:
    from .mock import conditions, contribution, detect_spans, per_post_k, specificity, stage2

__all__ = ["detect_spans", "conditions", "specificity", "contribution", "per_post_k", "stage2"]
