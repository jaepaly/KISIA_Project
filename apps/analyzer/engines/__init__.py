"""엔진 스위치. 환경변수 하나로 목/실제를 바꾼다 (docs/roles/howto/e-integration.md §3)."""

from __future__ import annotations

import os
from pathlib import PurePath


def checkpoint_label(path) -> str:
    """체크포인트 폴더 → 「상위폴더/폴더」 두 단계만 (예 ``kisia-ckpt/v2``). PC 절대경로는 응답에 싣지 않는다 (#348 과 같은 이유)."""
    return "/".join(PurePath(path).parts[-2:])


if os.getenv("ENGINE_MODE", "mock") == "real":
    from .real import c1_checkpoint, conditions, contribution, detect_spans, per_post_k, specificity, stage2
else:
    from .mock import c1_checkpoint, conditions, contribution, detect_spans, per_post_k, specificity, stage2

__all__ = ["c1_checkpoint", "checkpoint_label", "detect_spans", "conditions", "specificity", "contribution", "per_post_k", "stage2"]
