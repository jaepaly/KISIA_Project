"""B·C·D 완성 후 여기로 교체한다. 부분 교체 가능 — 아직 안 온 함수는
mock에서 그대로 가져와 쓴다 (docs/roles/howto/e-integration.md §3).

c1(스팬 탐지)만 실제 모델이다 — B 의 v1 체크포인트를 experiments/exp06-finetune/infer.py
의 SpanDetector 로 부른다. 가이드 예시(kopl.c1_span.predict)와 다르게 가는 이유:
  - local_files_only=True — 체크포인트를 허브에서 받으러 나가지 않는다 (외부 요청 0건)
  - 체크포인트가 없으면 에러 — kopl 쪽은 조용히 목 결과로 폴백해 진짜와 구분이 안 된다
  - 임계값 0.7 · 긴 글 창 나눔 — W7 성능 수치(#276)를 잰 경로와 같다

체크포인트는 gitignore 경로에 둔다 (#266). 다른 곳에 뒀으면 C1_CHECKPOINT_DIR 로 지정.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .mock import stage2  # noqa: F401 — 아직 안 온 것은 목을 그대로 쓴다
from .c23 import conditions, contribution, per_post_k, specificity  # noqa: F401 — C2·C3 실제 (k 엔진 · LOO)
from . import c1_rules as _c1_rules

_ROOT = Path(__file__).resolve().parents[3]
_EXP06 = _ROOT / "experiments" / "exp06-finetune"
_DEFAULT_CHECKPOINT = _EXP06 / "runs" / "v1_lr5e-5" / "checkpoint-epoch-10"
_MIN_SPAN_SCORE = 0.7  # v1 운용 임계값 (#266 B 코멘트)

# infer.py 는 같은 폴더의 train·prepare_bio 와 kopl.c1_span.schema 를 import 한다
for _path in (_EXP06, _ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import infer  # noqa: E402

from kopl.c1_span.attributes import resolve as resolve_attributes  # noqa: E402


def _attributes(texts: dict, candidate: dict) -> dict:
    """level·subject 판정 — 규칙 판정기 (kopl.c1_span.attributes · exp16).

    모델은 level·subject 를 예측하지 않는다. 임시값(implicit/self)을 쓰면 타인 단서(「친구가 [화정에서]」)도
    본인 것으로 k 를 좁히고, 「본인 명시 단서」를 다루는 추천·바꿔 쓰기가 한 번도 돌지 않는다.
    """
    return resolve_attributes(texts, candidate)


def _load_detector() -> "infer.SpanDetector":
    checkpoint = Path(os.getenv("C1_CHECKPOINT_DIR", _DEFAULT_CHECKPOINT))
    if not (checkpoint / "config.json").is_file():
        raise RuntimeError(
            f"c1 체크포인트가 없다: {checkpoint}\n"
            "B 에게 받은 파일(config.json · model.safetensors · tokenizer*.json)을 이 폴더에 두거나 "
            "C1_CHECKPOINT_DIR 로 위치를 지정한다 (#266). 목 엔진으로 돌리려면 ENGINE_MODE=mock.")
    detector = infer.SpanDetector(checkpoint, device="cpu", min_span_score=_MIN_SPAN_SCORE)
    return detector


# 서버가 켜질 때 한 번만 로드한다 (글마다 로드하면 1편에 수십 초)
_DETECTOR = _load_detector()


def detect_spans(post: dict) -> dict:
    """B(c1) 자리. span.schema.json 준수 — infer.format_contract 가 스키마 검사까지 한다."""
    record = {key: post[key] for key in ("post_id", "title", "body", "photo_captions")
              if post.get(key) is not None}
    return _c1_rules.detect(_DETECTOR, record, _attributes)  # C1_RULES=1 이면 명시 규칙 병합 (기본 꺼짐)
