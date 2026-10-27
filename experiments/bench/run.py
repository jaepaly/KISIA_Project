"""1단 벤치마크 — 기존 평가·추가 탐지율·CPU 지연을 metrics.json 하나로 모은다.

기본은 train 검증용이다. test는 --final-test-confirm으로만 열 수 있다.
모델 재학습·임계값 탐색·평가 결과 덮어쓰기는 하지 않는다.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import warnings

ROOT = Path(__file__).resolve().parents[2]
EXP06 = ROOT / 'experiments/exp06-finetune'
for path in (ROOT / 'src', EXP06, ROOT / 'apps/analyzer/engines', Path(__file__).resolve().parent):
    sys.path.insert(0, str(path))

import evaluate_test as evaluation
import measure_additional_rate as additional
import measure_cpu_latency as latency
from prepare_bio import DataError, validate_channel
from kopl.c1_span import infer, rules
from kopl.c1_span.attributes import resolve
import train
import c1_uncertainty as uncertainty
import c1_post_attr as post_attr

TEST_SHA256 = latency.TEST_SHA256
LEVELS = evaluation.LEVELS
# 가중치 밖에서 예측을 바꾸는 파일(토크나이저·라벨 매핑)도 지문에 넣는다.
CHECKPOINT_FILES = {'config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json',
                    'vocab.txt', 'sentencepiece.bpe.model', 'trainer_state.json'}


def test_ids(corpus):
    """ID만 읽으며 train 검증에서는 test 본문·blind를 열지 않는다."""
    data = json.loads((corpus / 'splits/test_post_ids.json').read_text(encoding='utf-8-sig'))
    ids = data.get('post_ids')
    if (not isinstance(ids, list) or len(ids) != 255 or any(not isinstance(p, str) for p in ids)
            or len(set(ids)) != len(ids)):
        raise DataError('공식 test ID 목록은 중복 없는 255개여야 합니다.')
    return set(ids)


def checkpoint_data_sha256(checkpoint_dir):
    """train.py가 trainer_state.json eval.run_config에 남긴 학습 BIO 지문. 없으면 None."""
    path = checkpoint_dir / 'trainer_state.json'
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding='utf-8'))
    return ((state.get('eval') or {}).get('run_config') or {}).get('data_sha256')


def training_provenance(args):
    """누수 검사할 --bio-data가 체크포인트가 실제 학습한 BIO인지 대조한다(train smoke에서도 미리 확인)."""
    trained = checkpoint_data_sha256(args.checkpoint_dir)
    checked = train.file_sha256(args.bio_data) if args.bio_data.exists() else None
    if trained is not None and trained != checked:
        raise DataError('--bio-data가 체크포인트 학습 데이터와 다릅니다(run_config.data_sha256 불일치).')
    return {'checkpoint': trained, 'checked_bio': checked, 'verified': trained is not None}


def load_dataset(args):
    provenance = training_provenance(args)
    if args.split == 'test':
        if not args.final_test_confirm or args.limit is not None:
            raise DataError('test는 --final-test-confirm이 필요하며 --limit은 사용할 수 없습니다.')
        path = args.corpus_dir / 'splits/test.jsonl'
        if train.file_sha256(path) != TEST_SHA256:
            raise DataError('고정 test.jsonl 지문이 다릅니다.')
        expected_ids = test_ids(args.corpus_dir)
        actual_ids = set(evaluation.index_posts(evaluation.records(path)))
        if actual_ids != expected_ids:
            raise DataError('test.jsonl과 고정 test ID 목록이 다릅니다.')
        posts, gold, audit = evaluation.prepare(args.corpus_dir, args.bio_data)
        if len(posts) != 239:
            raise DataError('IAA 제외 후 공식 평가 글 수는 239여야 합니다.')
        audit['training_data_sha256'] = provenance
        # 지문이 없는 체크포인트(v1)는 한계 문장을 남긴다.
        if provenance['verified']:
            audit['limitations'] = [x for x in audit['limitations'] if not x.startswith('Current BIO checked')]
        return posts, gold, audit
    forbidden = test_ids(args.corpus_dir)
    train_path = args.corpus_dir / 'splits/train.jsonl'
    training = evaluation.index_posts(evaluation.records(train_path))
    if set(training) & forbidden:
        raise DataError('train/test 글 ID가 겹칩니다.')
    gold, files = {}, [train_path, args.corpus_dir / 'splits/test_post_ids.json']
    for path in sorted((args.corpus_dir / 'gold').glob('*_spans.jsonl')):
        files.append(path)
        for row in evaluation.records(path):
            pid = row.get('post_id')
            if pid not in training or row.get('reviewed') is not True:
                continue
            if pid in gold:
                raise DataError(f'검수 골드 중복: {pid}')
            gold[pid] = row
    ids = sorted(gold)[:args.limit or 20]
    if len(ids) < 2:
        raise DataError('train 검증에는 검수 골드가 있는 글 2편 이상이 필요합니다.')
    posts = {pid: training[pid] for pid in ids}
    gold = {pid: gold[pid] for pid in ids}
    return posts, gold, {'scope': 'train reviewed subset; not independent performance evaluation',
                         'test_body_opened': False, 'evaluated_posts': len(ids),
                         'post_ids': ids, 'selection_policy': 'sorted reviewed train post_id; first N for smoke',
                         'training_data_sha256': provenance,
                         'input_sha256': {str(p): train.file_sha256(p) for p in files}}


def validate_gold(posts, gold):
    """미검수·다른 원문·등급 누락·중복을 빈 정답으로 받아들이지 않는다."""
    if set(posts) != set(gold):
        raise DataError('골드 글 목록이 다릅니다.')
    seen = set()
    for pid, row in gold.items():
        texts = infer.input_channels({'post_id': pid, 'texts': posts[pid]['texts']})[2]
        if row.get('reviewed') is not True or row.get('texts') != texts:
            raise DataError(f'검수 골드/원문 불일치: {pid}')
        grouped = defaultdict(list)
        for span in row['spans']:
            if span.get('level') not in LEVELS or span.get('subject') not in ('self', 'other', 'unknown'):
                raise DataError(f'골드 속성 누락: {pid}')
            if span['span_id'] in seen:
                raise DataError('골드 span_id 중복')
            seen.add(span['span_id'])
            grouped[span['text_id']].append(span)
        if set(grouped) - set(texts):
            raise DataError('골드의 알 수 없는 채널')
        for tid, text in texts.items():
            validate_channel(source=pid, text_id=tid, text=text, spans=grouped[tid])


def score_predictions(posts, gold, predictions):
    """proxy와 경계·유형·판정 등급 모두 일치해야 맞는 지표를 분리한다."""
    if set(predictions) != set(posts):
        raise DataError('예측 글 누락·추가: 탐지 없음도 빈 배열로 기록해야 합니다.')
    for pid, spans in predictions.items():
        raw = {'record_type': 'post', 'post_id': pid, 'texts': gold[pid]['texts'],
               'candidates': spans, 'model_version': 'benchmark-validation'}
        # 계약·문자 위치·중복·겹침도 기존 계약 출력 검증기로 검사한다.
        infer.format_contract(raw, lambda texts, s: {k: s[k] for k in ('level', 'subject')})
    partial = evaluation.score_subset(posts, gold, predictions)
    by_kind = {kind: evaluation.score_subset(
        [pid for pid, row in posts.items() if row.get('kind', 'unspecified') == kind], gold, predictions)
        for kind in sorted({row.get('kind', 'unspecified') for row in posts.values()})}
    for item in partial['by_level'].values():
        item['precision_shared'] = partial['overall']['precision']
    truth, guessed = {}, {}
    for pid in posts:
        for tid in gold[pid]['texts']:
            truth[(pid, tid)] = {(s['start'], s['end'], s['type'] + '/' + s['level'])
                                for s in gold[pid]['spans'] if s['text_id'] == tid}
            guessed[(pid, tid)] = {(s['start'], s['end'], s['type'] + '/' + s['level'])
                                  for s in predictions[pid] if s['text_id'] == tid}
    def resolved_scores(scorer):
        result = {'overall': scorer(truth, guessed)['overall'], 'by_level': {}}
        for level in LEVELS:
            filtered = [{key: {s for s in spans if s[2].endswith('/' + level)}
                         for key, spans in mapping.items()} for mapping in (truth, guessed)]
            support = sum(len(x) for x in filtered[0].values())
            count = sum(len(x) for x in filtered[1].values())
            item = scorer(*filtered)['overall']
            if not support:
                item = {**item, 'recall': None, 'f1': None}
            result['by_level'][level] = {**item, 'gold_spans': support, 'predicted_spans': count}
        return result
    exact_proxy = {}
    for level in LEVELS:
        actual = {(pid, s['text_id'], s['start'], s['end'], s['type'])
                  for pid, row in gold.items() for s in row['spans'] if s['level'] == level}
        predicted = {(pid, s['text_id'], s['start'], s['end'], s['type'])
                     for pid, spans in predictions.items() for s in spans}
        tp, fn = len(actual & predicted), len(actual - predicted)
        recall = tp / len(actual) if actual else None
        precision = partial['exact']['overall']['precision']
        f1 = (2 * precision * recall / (precision + recall) if precision and recall else 0.0) if actual else None
        exact_proxy[level] = {'tp': tp, 'fn': fn, 'gold_spans': len(actual), 'recall': recall,
                              'precision_shared': precision, 'proxy_f1': f1}
    implicit = partial['by_level']['implicit']['proxy_f1']
    classified = resolved_scores(train.score_span_sets)
    # 신뢰구간 · 오탐 원인은 11/2 보고 항목(PM 결정 10/25). 글별 합이 위 점수와 다르면 중단한다.
    uncertainty_result = uncertainty.bootstrap(posts, gold, predictions, partial, classified)
    causes = uncertainty.fp_causes(posts, gold, predictions)
    if causes['total'] != partial['overall']['fp']:
        raise DataError('오탐 원인 합이 전체 FP 와 다릅니다.')
    return {
        'boundary_type': {'partial': partial, 'exact': partial['exact']},
        'by_kind': by_kind, 'fp_breakdown': {**evaluation.fp_breakdown(partial, by_kind), 'by_cause': causes},
        'bootstrap_ci': uncertainty_result,
        # 서비스 단위 보조 지표 — 판정 값 아님 · 정의는 11/2 전에 고정(DEC-016)
        'post_attribute': post_attr.score(gold, predictions),
        'proxy': {'partial_by_level': partial['by_level'], 'exact_by_level': exact_proxy,
                  'policy': partial['level_policy']},
        'resolved_level': {'partial': classified, 'exact': resolved_scores(evaluation.exact_span_sets),
                           'policy': 'type AND resolve-predicted level equal; greedy 1:1 IoU >= 0.5. '
                                     'End-to-end span+level F1, not standalone level accuracy; subject not a match condition.'},
        'implicit_iaa': {**partial['implicit_iaa_comparison'],
                         'proxy_percent': implicit / .444 * 100 if implicit is not None else None,
                         'resolved_level_percent': classified['by_level']['implicit']['f1'] / .444 * 100
                         if classified['by_level']['implicit']['f1'] is not None else None,
                         'policy': 'IAA v2 rounded 44.4%; different samples/definitions, reference ratio only'},
    }


class DetectCall:
    """#301 measure_one이 같은 detect 인터페이스로 앱 경로도 잴 수 있게 한다."""
    def __init__(self, call):
        self.call = call

    def detect(self, post):
        return self.call(post)


def measure_latency(posts, model_call, app_call, samples=20, warmup=5, repeats=50):
    selected = latency.select_length_spaced(posts, min(samples, len(posts)))
    result = {}
    for name, call in [('model_only', model_call), ('app_full', app_call)]:
        rows = []
        for post in selected:
            times = latency.measure_one(DetectCall(call), post, warmup, repeats)
            rows.append({'post_id': post['post_id'], 'characters': latency.post_length(post),
                         'median_ms': statistics.median(times), 'p95_ms': latency.nearest_rank(times),
                         'times_ms': times})
        medians = [r['median_ms'] for r in rows]
        result[name] = {'posts': rows, 'distribution_ms': {
            'median': statistics.median(medians), 'p95_nearest_rank': latency.nearest_rank(medians),
            'max': max(medians), 'under_300_posts': sum(x < 300 for x in medians)}}
    return {**result, 'sample_policy': 'same #301 length-spaced midpoint algorithm, same posts for both paths',
            'warmup_per_post': warmup, 'repeats_per_post': repeats, 'posts_per_call': 1,
            'scope': 'model_only: #301 detect incl contract validation (legacy attributes); '
                     'app_full: model+optional rules+resolve+contract validation; model loading excluded'}


def source_fingerprint(path):
    try:
        commit = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--', str(path)],
                                         cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {'sha256': train.file_sha256(path), 'commit': commit}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--split', choices=('train', 'test'), default='train')
    parser.add_argument('--final-test-confirm', action='store_true', help='11/2 최종 측정 때만 사용')
    parser.add_argument('--limit', type=int, help='train 검증 글 수, 기본 20; test에서는 금지')
    parser.add_argument('--corpus-dir', type=Path, default=ROOT / 'data/corpus/v0')
    parser.add_argument('--bio-data', type=Path, default=EXP06 / 'runs/bio_variant_base_20261008/train.jsonl')
    parser.add_argument('--rules', choices=('on', 'off'), default='on')
    parser.add_argument('--threshold', type=float, default=.7)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--latency-samples', type=int, default=20)
    parser.add_argument('--warmup', type=int, default=5)
    parser.add_argument('--repeats', type=int, default=50)
    parser.add_argument('--skip-baselines', action='store_true', help='개발 검증용; 미측정으로 표시')
    parser.add_argument('--skip-latency', action='store_true', help='개발 검증용; 미측정으로 표시')
    args = parser.parse_args(argv)
    if args.split == 'test' and (not args.final_test_confirm or args.limit is not None
                                 or args.skip_baselines or args.skip_latency):
        parser.error('최종 test는 확인 옵션이 필요하며 limit/skip 옵션은 금지합니다.')
    if (not 0 <= args.threshold <= 1 or args.threads < 1 or args.warmup < 0 or args.repeats < 1
            or args.latency_samples < 2 or args.limit is not None and args.limit < 2):
        parser.error('임계값·스레드·반복·표본 수가 유효하지 않습니다.')
    if args.split == 'test' and (args.latency_samples != 20 or args.warmup != 5 or args.repeats != 50):
        parser.error('최종 지연은 #301과 같은 20편·워밍업 5회·반복 50회로 측정합니다.')
    resolved = args.output_dir.resolve()
    if args.output_dir.exists() or not resolved.is_relative_to(ROOT / 'experiments') or 'runs' not in resolved.parts:
        parser.error('기존 결과를 덮어쓰지 않습니다. experiments 아래 새 runs/ 경로를 지정하세요.')
    return args


def main(argv=None):
    args = parse_args(argv)
    posts, gold, audit = load_dataset(args)
    validate_gold(posts, gold)
    # skip은 미측정으로 기록. 기본 경로에서는 도구가 빠져도 폴백하지 않는다.
    baseline_result = None
    if not args.skip_baselines:
        baseline_result = additional.run_baselines(posts)
    import torch
    import transformers
    torch.set_num_threads(args.threads)
    os.environ['C1_RULES'] = '1' if args.rules == 'on' else '0'
    import c1_rules
    if c1_rules.enabled() != (args.rules == 'on'):
        raise DataError('프로세스에 이미 로드된 앱 규칙 설정이 CLI와 다릅니다. 새 프로세스로 실행하세요.')
    started = time.perf_counter()
    detector = infer.SpanDetector(args.checkpoint_dir, device='cpu', min_span_score=args.threshold)
    loading = time.perf_counter() - started
    app_call = lambda post: c1_rules.detect(detector, post, resolve)
    # label·kind·골드 메타는 detector에 넘기지 않는다.
    records = {pid: {'post_id': pid, 'texts': row['texts']} for pid, row in posts.items()}
    predictions = {pid: app_call(row)['spans'] for pid, row in records.items()}
    scores = score_predictions(posts, gold, predictions)
    extra = {'status': 'not_measured', 'reason': '--skip-baselines; development only'}
    if baseline_result is not None:
        tools, meta = baseline_result
        extra = {'status': 'measured', **additional.score_additional_rate(
            gold, predictions, tools, scores['boundary_type']['partial']['overall']['tp']), 'baseline': meta}
    timing = {'status': 'not_measured', 'reason': '--skip-latency; development only'}
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='level=implicit.*', category=RuntimeWarning)
        if not args.skip_latency:
            timing = {'status': 'measured', **measure_latency(records, detector.detect, app_call,
                     args.latency_samples, args.warmup, args.repeats)}
    report = {'schema_version': 'bench-c1-1.0', 'measured_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'official_test' if args.split == 'test' else 'development_smoke_not_final',
              'data_version': 'corpus-v0 p2.3; gold hashes identify current level convention',
              'checkpoint': str(args.checkpoint_dir), 'model_version': detector.version,
              'checkpoint_sha256': {p.name: train.file_sha256(p) for p in sorted(args.checkpoint_dir.glob('*'))
                                    if p.is_file() and (p.suffix == '.safetensors' or p.name in CHECKPOINT_FILES)},
              'rules_enabled': args.rules == 'on', 'threshold': args.threshold,
              'device': 'cpu', 'threads': torch.get_num_threads(), 'cpu_name': platform.processor(),
              'python': platform.python_version(), 'torch': torch.__version__, 'transformers': transformers.__version__,
              'window_batch_size': detector.batch_size, 'max_length': detector.max_length,
              'stride': detector.stride, 'model_loading_seconds_excluded': loading,
              'checkpoint_training': json.loads((args.checkpoint_dir / 'trainer_state.json').read_text(encoding='utf-8'))
              .get('eval', {}).get('run_config') if (args.checkpoint_dir / 'trainer_state.json').exists() else None,
              'source': {str(p.relative_to(ROOT)): source_fingerprint(p) for p in
                         [Path(__file__).resolve(), ROOT / 'src/kopl/c1_span/infer.py',
                          ROOT / 'src/kopl/c1_span/rules.py', ROOT / 'src/kopl/c1_span/bio.py',
                          ROOT / 'src/kopl/c1_span/attributes.py', ROOT / 'apps/analyzer/engines/c1_rules.py',
                          EXP06 / 'evaluate_test.py', EXP06 / 'measure_additional_rate.py',
                          EXP06 / 'measure_cpu_latency.py', EXP06 / 'train.py']},
              'audit': audit, 'c1': scores, 'additional_detection': extra, 'cpu_latency': timing,
              'extensions': {}, 'extension_policy': 'D adds stage2/risk/actions here; no placeholder scores'}
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / 'predictions.jsonl').write_text(''.join(json.dumps(
        {'post_id': pid, 'candidates': spans}, ensure_ascii=False) + '\n' for pid, spans in predictions.items()), encoding='utf-8')
    target = args.output_dir / 'metrics.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'scope': report['scope'], 'overall': scores['boundary_type']['partial']['overall'],
                      'additional_detection': extra['status'], 'cpu_latency': timing['status']}, ensure_ascii=False, indent=2))
    print(f'Saved: {target}')


if __name__ == '__main__':
    main()
