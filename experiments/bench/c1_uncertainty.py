"""1단 점수의 불확실성과 오탐 원인 — 부트스트랩 신뢰구간 · 부분 일치 FP 분해.

run.py score_predictions 가 부른다. 점수를 새로 정의하지 않는다 — 기존 채점기(train.score_span_sets ·
evaluate_test.level_breakdown)를 글 단위로 다시 돌려 더한 값이 전체 점수와 같은지 먼저 대조한다.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import random
import re

import evaluate_test as evaluation
from prepare_bio import DataError
import train

LEVELS = evaluation.LEVELS
# 측정 전에 고정한다(PM 결정 10/25). 바꾸면 신뢰구간이 달라지므로 11/2 에는 이 값 그대로.
RESAMPLES = 2000
SEED = 20261102
FP_CAUSES = ('boundary_low_iou', 'duplicate_of_matched', 'type_confusion', 'unannotated_repeat', 'no_overlap')


def _channel_sets(pid, gold, predictions, *, with_level):
    truth, guessed = {}, {}
    for tid in gold[pid]['texts']:
        label = (lambda s: s['type'] + '/' + s['level']) if with_level else (lambda s: s['type'])
        truth[(pid, tid)] = {(s['start'], s['end'], label(s)) for s in gold[pid]['spans'] if s['text_id'] == tid}
        guessed[(pid, tid)] = {(s['start'], s['end'], label(s)) for s in predictions[pid] if s['text_id'] == tid}
    return truth, guessed


def post_counts(pid, gold, predictions):
    """글 하나의 TP·FP·FN. 매칭이 채널 안에서만 일어나므로 글끼리 더하면 전체와 같다."""
    truth, guessed = _channel_sets(pid, gold, predictions, with_level=False)
    overall = train.score_span_sets(truth, guessed)['overall']
    levels = {(pid, tid): {(s['start'], s['end'], s['type']): s['level']
                           for s in gold[pid]['spans'] if s['text_id'] == tid} for tid in gold[pid]['texts']}
    by_level = evaluation.level_breakdown(truth, guessed, levels, overall)['by_level']
    truth_l, guessed_l = _channel_sets(pid, gold, predictions, with_level=True)
    resolved = train.score_span_sets(truth_l, guessed_l)['overall']
    explicit_only = [{k: {s for s in v if s[2].endswith('/explicit')} for k, v in m.items()}
                     for m in (truth_l, guessed_l)]
    resolved_explicit = train.score_span_sets(*explicit_only)['overall']
    return {'tp': overall['tp'], 'fp': overall['fp'], 'fn': overall['fn'],
            'explicit_tp': by_level['explicit']['tp'], 'explicit_fn': by_level['explicit']['fn'],
            'resolved_tp': resolved['tp'], 'resolved_fp': resolved['fp'], 'resolved_fn': resolved['fn'],
            'resolved_explicit_tp': resolved_explicit['tp'], 'resolved_explicit_fp': resolved_explicit['fp'],
            'resolved_explicit_fn': resolved_explicit['fn']}


def _f1(p, r):
    return 2 * p * r / (p + r) if p + r else 0.0


def headline(c):
    """신뢰구간을 낼 지표. 정의는 run.py 의 proxy · resolved_level 과 같다."""
    def ratio(a, b):
        return a / b if b else 0.0
    precision = ratio(c['tp'], c['tp'] + c['fp'])
    recall = ratio(c['tp'], c['tp'] + c['fn'])
    explicit_recall = ratio(c['explicit_tp'], c['explicit_tp'] + c['explicit_fn'])
    r_p = ratio(c['resolved_explicit_tp'], c['resolved_explicit_tp'] + c['resolved_explicit_fp'])
    r_r = ratio(c['resolved_explicit_tp'], c['resolved_explicit_tp'] + c['resolved_explicit_fn'])
    rr_p = ratio(c['resolved_tp'], c['resolved_tp'] + c['resolved_fp'])
    rr_r = ratio(c['resolved_tp'], c['resolved_tp'] + c['resolved_fn'])
    return {'explicit_proxy_f1': _f1(precision, explicit_recall) if precision and explicit_recall else 0.0,
            'explicit_recall': explicit_recall, 'precision': precision, 'recall': recall,
            'f1': _f1(precision, recall), 'resolved_explicit_f1': _f1(r_p, r_r),
            'resolved_f1': _f1(rr_p, rr_r)}


def _total(rows):
    out = Counter()
    for row in rows:
        out.update(row)
    return out


def _percentile(sorted_values, q):
    """선형 보간 백분위수(numpy 기본과 같은 방식)."""
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def bootstrap(posts, gold, predictions, partial, resolved, *, resamples=RESAMPLES, seed=SEED):
    """글 단위 복원추출 백분위 95% 신뢰구간. 점추정은 전체 표본 값 그대로다."""
    ids = sorted(posts)
    rows = [post_counts(pid, gold, predictions) for pid in ids]
    total = _total(rows)
    # 글별 합이 공식 채점과 다르면 신뢰구간이 다른 지표를 재는 것이 된다.
    expected = {'tp': partial['overall']['tp'], 'fp': partial['overall']['fp'], 'fn': partial['overall']['fn'],
                'explicit_tp': partial['by_level']['explicit']['tp'],
                'explicit_fn': partial['by_level']['explicit']['fn'],
                'resolved_tp': resolved['overall']['tp'], 'resolved_fp': resolved['overall']['fp'],
                'resolved_fn': resolved['overall']['fn'],
                'resolved_explicit_tp': resolved['by_level']['explicit']['tp'],
                'resolved_explicit_fp': resolved['by_level']['explicit']['fp'],
                'resolved_explicit_fn': resolved['by_level']['explicit']['fn']}
    if any(total[k] != v for k, v in expected.items()):
        raise DataError('글 단위 합이 공식 채점과 다릅니다 — 신뢰구간을 내지 않습니다.')
    point = headline(total)
    rng = random.Random(seed)
    draws = defaultdict(list)
    for _ in range(resamples):
        sample = _total(rng.choices(rows, k=len(rows)))
        for key, value in headline(sample).items():
            draws[key].append(value)
    metrics = {}
    for key, value in point.items():
        values = sorted(draws[key])
        metrics[key] = {'point': value, 'ci95_low': _percentile(values, .025),
                        'ci95_high': _percentile(values, .975)}
    return {'metrics': metrics, 'unit': 'post', 'posts': len(ids), 'resamples': resamples, 'seed': seed,
            'method': 'percentile bootstrap, posts resampled with replacement; point = full-sample value',
            'limitations': ['Posts by the same persona are not independent; persona-level resampling would '
                            'give wider intervals. Read as sampling noise of this test set, not of new users.',
                            'Gold convention uncertainty (annotator disagreement) is not included.']}


def _norm(text):
    return re.sub(r'\s+', '', text)


def fp_causes(posts, gold, predictions):
    """부분 일치에서 짝을 못 찾은 예측(FP)을 기계적으로 다섯 갈래로 나눈다. 합 = 전체 FP.

    boundary_low_iou      같은 유형 골드와 겹치지만 IoU < 0.5
    duplicate_of_matched  같은 유형 골드와 IoU ≥ 0.5 인데 그 골드를 다른 예측이 먼저 가져감
    type_confusion        다른 유형 골드와만 겹침 (골드 유형 → 예측 유형 짝으로 센다)
    unannotated_repeat    겹치는 골드는 없지만 같은 글에 같은 유형 · 같은 글자의 골드가 있음
                          (골드가 반복 언급을 한 번만 칠한 경우가 많다)
    no_overlap            나머지 — 골드와 아무 관련이 없는 예측
    「골드 관례 차이인가 · 모델 잘못인가」는 사람 판단이라 여기서 가르지 않는다.
    """
    causes = Counter()
    by_type = defaultdict(Counter)
    confusion = Counter()
    for pid in sorted(posts):
        same_text = defaultdict(set)
        for s in gold[pid]['spans']:
            same_text[s['type']].add(_norm(s['text']))
        for tid, text in gold[pid]['texts'].items():
            actual = sorted((s['start'], s['end'], s['type']) for s in gold[pid]['spans'] if s['text_id'] == tid)
            guessed = sorted({(s['start'], s['end'], s['type']) for s in predictions[pid] if s['text_id'] == tid})
            # train.score_span_sets 와 같은 탐욕 매칭(동점 처리 포함)으로 짝 없는 예측을 고른다.
            candidates = sorted(((train.span_iou(g, p), i, j) for i, g in enumerate(actual)
                                 for j, p in enumerate(guessed)
                                 if g[2] == p[2] and train.span_iou(g, p) >= .5), reverse=True)
            used_gold, used_pred = set(), set()
            for _, i, j in candidates:
                if i not in used_gold and j not in used_pred:
                    used_gold.add(i)
                    used_pred.add(j)
            for j, (start, end, kind) in enumerate(guessed):
                if j in used_pred:
                    continue
                overlap = [g for g in actual if g[0] < end and start < g[1]]
                same = [g for g in overlap if g[2] == kind]
                if same:
                    cause = ('duplicate_of_matched' if any(train.span_iou(g, (start, end, kind)) >= .5 for g in same)
                             else 'boundary_low_iou')
                elif overlap:
                    cause = 'type_confusion'
                    confusion[f'{overlap[0][2]}->{kind}'] += 1
                elif _norm(text[start:end]) in same_text[kind]:
                    cause = 'unannotated_repeat'
                else:
                    cause = 'no_overlap'
                causes[cause] += 1
                by_type[kind][cause] += 1
    return {'total': sum(causes.values()), 'by_cause': {c: causes[c] for c in FP_CAUSES},
            'by_type': {k: {c: v[c] for c in FP_CAUSES if v[c]} for k, v in sorted(by_type.items())},
            'type_confusion_pairs': dict(confusion.most_common()),
            'policy': 'mechanical split of unmatched partial-match predictions; '
                      'whether a cause is a gold convention difference or a model error is a human judgment'}
