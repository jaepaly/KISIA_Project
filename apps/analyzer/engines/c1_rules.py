"""1단 명시 규칙 병합 — **기본 켬** (``C1_RULES=0`` 이면 끔).

B 의 exp06 ``rules.ExplicitRules`` (한글 수사·숫자 나이 · 행정구역 이름·약칭)를 모델 후보와 같은 정책
(``merge_with_model`` — 최장 우선 · 겹침 없음)으로 합친다. models/registry.md 「v1+명시 규칙」 구성이다
(test 239편 명시 재현율 0.1339 → 0.3750 · partial F1 0.2940 → 0.3424).

운용 구성은 **기준선 v2 = 교사 라벨 재학습 + 이 규칙**으로 확정했다 (#310 · DEC-011 · 10/8). exp17b · exp17c 점수는
규칙을 켠 채로 쟀으므로 앱도 기본으로 켠다 — 끄면 그 점수와 다른 구성이 된다. 모델 단독과 비교할 때만 ``C1_RULES=0``.
"""
from __future__ import annotations

import os
import threading

_ENABLED = os.getenv("C1_RULES", "1") != "0"
_RULES = None
_LOCK = threading.Lock()


def enabled() -> bool:
    return _ENABLED


def _rules():
    global _RULES
    with _LOCK:
        if _RULES is None:
            import rules  # experiments/exp06-finetune (real.py 가 sys.path 에 넣는다)

            _RULES = rules.ExplicitRules()
    return _RULES


def detect(detector, record: dict, resolver) -> dict:
    """``detector.detect`` 와 같은 결과 형식. 규칙이 꺼져 있으면 그대로 위임한다."""
    if not _ENABLED:
        return detector.detect(record, resolver=resolver)
    import infer
    import rules

    raw = detector.predict_raw(record)
    if raw.get("record_type") != "post":
        return infer.format_contract(raw, resolver)
    merged, _stats = rules.merge_with_model(raw["post_id"], raw["texts"], raw["candidates"], _rules())
    raw = {**raw, "candidates": merged, "model_version": f"{raw['model_version']}+rules"}
    return infer.format_contract(raw, resolver)
