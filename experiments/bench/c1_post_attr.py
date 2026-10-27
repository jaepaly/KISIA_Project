"""1단 보조 지표 — 글×속성 단위 F1 (서비스 관점 · 판정 값 아님).

run.py score_predictions 가 부른다. 판정 값은 그대로 명시 proxy 다(README 「명시 F1 — 11/2 에 무엇을 판정
값으로 적나」 · DEC-016). 이 값은 「위험도 · 사람 수 계산이 실제로 쓰는 단위에서 단서를 찾았나」를 보는 보조다.

정의 (11/2 측정 전에 고정 · DEC-016):
- 단위: (글, 속성). 속성은 서비스 판정과 같은 매핑 ``kopl.c4_stage2.rules.TYPE_TO_ATTR`` 로 정한다
- 맞음(TP): 그 글에서 같은 속성의 정답 스팬과 예측 스팬이 **같은 채널에서 한 글자 이상 겹친다**
- 놓침(FN): 정답에는 그 속성이 있는데 겹치는 예측이 없다
- 헛잡음(FP): 예측에는 그 속성이 있는데 겹치는 정답이 없다 — 정답에 속성이 있어도 다른 곳을 짚었으면 FN · FP 둘 다
- 등급 · subject 는 보지 않는다(주 지표 partial 과 같다). 반복 언급 · 경계 차이는 한 단위로 접힌다
"""
from __future__ import annotations

from collections import Counter

from kopl.c4_stage2.rules import ATTRS, TYPE_TO_ATTR

POLICY = ('unit (post, attribute) via c4_stage2.rules.TYPE_TO_ATTR; TP if a gold and a predicted span of that '
          'attribute overlap by >= 1 character in the same channel; level and subject ignored. '
          'Auxiliary service-unit view registered before 11/2 (DEC-016); not the judgement value.')


def _by_attr(spans):
    out = {}
    for s in spans:
        out.setdefault(TYPE_TO_ATTR[s['type']], []).append((s['text_id'], s['start'], s['end']))
    return out


def _overlaps(a, b):
    return any(x[0] == y[0] and x[1] < y[2] and y[1] < x[2] for x in a for y in b)


def _prf(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {'tp': tp, 'fp': fp, 'fn': fn, 'precision': precision, 'recall': recall, 'f1': f1}


def score(gold, predictions):
    """gold: {post_id: {'spans': [...]}} · predictions: {post_id: [span]} → 전체 · 속성별 P/R/F1."""
    counts = {attr: Counter() for attr in ATTRS}
    for pid, row in gold.items():
        truth, guessed = _by_attr(row['spans']), _by_attr(predictions[pid])
        for attr in truth.keys() | guessed.keys():
            hit = attr in truth and attr in guessed and _overlaps(truth[attr], guessed[attr])
            if hit:
                counts[attr]['tp'] += 1
                continue
            if attr in truth:
                counts[attr]['fn'] += 1
            if attr in guessed:
                counts[attr]['fp'] += 1
    total = sum(counts.values(), Counter())
    return {'overall': _prf(total['tp'], total['fp'], total['fn']),
            'by_attribute': {attr: _prf(c['tp'], c['fp'], c['fn']) for attr, c in counts.items()},
            'policy': POLICY}
