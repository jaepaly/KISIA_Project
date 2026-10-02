"""저장된 v1 test 예측에 W7 명시 규칙을 결합해 전·후를 별도로 채점한다.

모델 추론과 학습을 다시 실행하지 않는다. 원본 predictions.jsonl·split·골드는
수정하지 않으며 새 결과는 runs/ 하위의 새로운 디렉터리에만 저장한다.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import evaluate_test
from prepare_bio import DataError
from rules import ExplicitRules, TRAIN_AMBIGUOUS_TERMS, merge_with_model


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / 'experiments/exp06-finetune/runs'
EXPECTED_TEST_SHA256 = '9662a167f530f47318da2bd37a8401988ee74555393d6cd377fa84dfe8a886ad'
PROFILES = {
    'v1': {
        'saved_test_dir': RUNS / 'test_v1_lr5e-5_t07',
        'output_dir': RUNS / 'w7_v1_plus_rules',
        'bio_data': Path('experiments/exp06-finetune/runs/bio/train.jsonl'),
        'model_version': 'v1_lr5e-5/checkpoint-epoch-10',
        'overall_counts': (111, 286, 247),
    },
    'w7_teacher': {
        'saved_test_dir': RUNS / 'w7_test_teacher_1e-5',
        'output_dir': RUNS / 'w7_test_teacher_1e-5_plus_rules',
        'bio_data': Path('experiments/exp06-finetune/runs/bio_w7_teacher/train.jsonl'),
        'model_version': 'w7_teacher_lr1e-5_diagnostic/checkpoint-epoch-10',
        'overall_counts': (211, 318, 147),
    },
}


def check_baseline(baseline, profile):
    """저장 예측이 선택한 모델과 원래 공식 채점 결과에 대응하는지 확인한다."""
    if baseline['model_version'] != profile['model_version'] or baseline['min_span_score'] != 0.7:
        raise DataError('저장 예측의 체크포인트 또는 임계값이 선택한 평가 설정과 다릅니다.')
    original = baseline['metrics']['overall']
    if (original['tp'], original['fp'], original['fn']) != profile['overall_counts']:
        raise DataError('저장 예측의 기존 공식 test 점수가 기대값과 다릅니다.')


def score_augmented(posts, gold, prediction_rows, detector):
    """골드는 채점에만 사용하고 규칙·병합 함수에는 원문과 예측만 전달한다."""
    if set(prediction_rows) != set(posts):
        raise DataError('저장 예측 ID와 공식 test ID가 다릅니다.')
    combined = {}
    source_stats: Counter[str] = Counter()
    for pid in sorted(posts):
        texts = posts[pid]['texts']
        combined[pid], stats = merge_with_model(pid, texts,
                                                 prediction_rows[pid]['candidates'], detector)
        source_stats.update(stats)
    scored = evaluate_test.score_subset(posts, gold, combined)
    by_kind = {kind: evaluate_test.score_subset(
                   [pid for pid, row in posts.items() if row['kind'] == kind], gold, combined)
               for kind in sorted({row['kind'] for row in posts.values()})}
    return {'metrics': scored, 'by_kind': by_kind,
            'fp_breakdown': evaluate_test.fp_breakdown(scored, by_kind),
            'source_stats': dict(source_stats)}


def headline(metrics, by_kind):
    explicit = metrics['by_level']['explicit']
    overall = metrics['overall']
    return {
        'explicit_tp': explicit['tp'], 'explicit_fn': explicit['fn'],
        'explicit_recall': explicit['recall'], 'explicit_proxy_f1': explicit['proxy_f1'],
        'overall_tp': overall['tp'], 'overall_fp': overall['fp'], 'overall_fn': overall['fn'],
        'overall_precision': overall['precision'], 'overall_f1': overall['f1'],
        'noise_fp': by_kind['noise']['overall']['fp'],
        'by_type_tp_fp': {kind: {'tp': counts['tp'], 'fp': counts['fp']}
                          for kind, counts in metrics['by_type'].items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, default='v1')
    parser.add_argument('--saved-test-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    profile = PROFILES[args.profile]
    args.saved_test_dir = args.saved_test_dir or profile['saved_test_dir']
    args.output_dir = args.output_dir or profile['output_dir']
    if Path.cwd().resolve() != ROOT:
        parser.error('입력 지문 비교를 위해 저장소 루트에서 실행하세요.')
    if not args.output_dir.resolve().is_relative_to(RUNS.resolve()) or args.output_dir.exists():
        parser.error('기존 결과를 덮어쓰지 않도록 새로운 runs/ 하위 출력 디렉터리를 지정하세요.')

    posts, gold, audit = evaluate_test.prepare(Path('data/corpus/v0'), profile['bio_data'])
    test_sha = audit['input_sha256'][str(Path('data/corpus/v0/splits/test.jsonl'))]
    if test_sha != EXPECTED_TEST_SHA256 or len(posts) != 239:
        raise DataError('확정된 239편 test와 지문이 다릅니다. split을 변경하지 마세요.')
    # 원본만 재채점해 지문·오프셋·기존 전체 TP/FP/FN의 동일성을 확인한다.
    # 규칙 결합 결과에는 rescore_saved()를 적용하지 않는다.
    baseline = evaluate_test.rescore_saved(args.saved_test_dir, posts, gold, audit)
    check_baseline(baseline, profile)

    prediction_rows = evaluate_test.index_posts(
        evaluate_test.records(args.saved_test_dir / 'predictions.jsonl'))
    augmented = score_augmented(posts, gold, prediction_rows, ExplicitRules())
    before = headline(baseline['metrics'], baseline['by_kind'])
    after = headline(augmented['metrics'], augmented['by_kind'])
    report = {
        'profile': args.profile,
        'measured_at_utc': datetime.now(timezone.utc).isoformat(),
        'data_version': baseline['data_version'],
        'checkpoint': baseline['checkpoint'],
        'checkpoint_sha256': baseline['checkpoint_sha256'],
        'min_span_score': baseline['min_span_score'],
        'test_posts': len(posts), 'test_sha256': test_sha,
        'model_inference_repeated': False,
        'test_informed_design': True,
        'limitation': ('AGE·LOC_ADMIN 보강 유형은 test 오류 분석 #283을 보고 선정했다. '
                       '정규식·제외 표현은 train 331편만 보고 확정했으며 이 test 평가는 규칙 확정 후 1회다.'),
        'rule_policy': {
            'types': ['AGE', 'LOC_ADMIN'],
            'excluded_ambiguous_terms_from_train': sorted(TRAIN_AMBIGUOUS_TERMS),
            'merge': 'train.resolve_overlapping_spans; longest first, no source priority',
            'rule_score': 'not assigned; no calibrated confidence',
            'source_logging': 'source_stats only; no new contract span fields',
        },
        'before': {'headline': before, 'metrics': baseline['metrics'],
                   'by_kind': baseline['by_kind'], 'fp_breakdown': baseline['fp_breakdown']},
        'after': {'headline': after, **augmented},
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    target = args.output_dir / 'metrics.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'before': before, 'after': after,
                      'source_stats': augmented['source_stats']}, ensure_ascii=False, indent=2))
    print(f'Saved: {target}')


if __name__ == '__main__':
    main()
