"""엔진 스위치. 환경변수 하나로 목/실제를 바꾼다 (docs/roles/howto/e-integration.md §3)."""

from __future__ import annotations

import os

if os.getenv("ENGINE_MODE", "mock") == "real":
    from .real import contribution, detect_spans, specificity, stage2
else:
    from .mock import contribution, detect_spans, specificity, stage2

__all__ = ["detect_spans", "specificity", "contribution", "stage2"]
