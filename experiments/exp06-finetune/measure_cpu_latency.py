"""공식 test 글 여러 편의 1단 CPU 지연을 재현 가능하게 측정한다.

글 길이순으로 고르게 표본을 고르고, 각 글에서 워밍업을 버린 뒤
`SpanDetector.detect()` 전체 시간을 잰다. 골드 라벨은 추론에 전달하지 않는다.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import platform
import statistics
import time
import warnings

import evaluate_test
import infer
import train


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / 'experiments/exp06-finetune/runs'
TEST_SHA256 = '9662a167f530f47318da2bd37a8401988ee74555393d6cd377fa84dfe8a886ad'


def post_length(post: dict) -> int:
    """추론에 실제로 들어가는 NFC 텍스트 채널의 총 문자 수."""
    return sum(len(text) for text in infer.input_channels(post)[2].values())


def select_length_spaced(posts: dict, count: int) -> list[dict]:
    """길이순 목록의 동일 폭 구간 중앙에서 글 하나씩 뽑는다."""
    if count < 2 or count > len(posts):
        raise ValueError('표본 수는 2 이상이며 평가 글 수 이하여야 합니다.')
    ordered = sorted(posts.values(), key=lambda post: (post_length(post), post['post_id']))
    indices = [round((len(ordered) - 1) * (index + 0.5) / count)
               for index in range(count)]
    if len(set(indices)) != count:
        raise ValueError('길이별 표본의 글 ID가 중복됩니다.')
    return [ordered[index] for index in indices]


def nearest_rank(values: list[float], quantile: float = 0.95) -> float:
    """정렬 후 올림 순위를 사용하는 p95 등 분위수."""
    if not values or not 0 < quantile <= 1:
        raise ValueError('분위수 계산에 유효한 값이 필요합니다.')
    return sorted(values)[math.ceil(quantile * len(values)) - 1]


def measure_one(detector, post: dict, warmup: int, repeats: int,
                clock=time.perf_counter) -> list[float]:
    """글 하나의 워밍업을 버리고 detect 호출의 경과 시간을 ms로 기록한다."""
    for _ in range(warmup):
        detector.detect(post)
    times = []
    for _ in range(repeats):
        start = clock()
        detector.detect(post)
        times.append((clock() - start) * 1000)
    return times


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, default=RUNS / 'w8_cpu_latency_v1')
    parser.add_argument('--corpus-dir', type=Path, default=ROOT / 'data/corpus/v0')
    parser.add_argument('--bio-data', type=Path, default=train.DEFAULT_DATA)
    parser.add_argument('--samples', type=int, default=20)
    parser.add_argument('--warmup', type=int, default=5)
    parser.add_argument('--repeats', type=int, default=50)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--min-span-score', type=float, default=0.7)
    parser.add_argument('--cpu-name', default=platform.processor())
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error(f'기존 결과를 덮어쓰지 않습니다: {args.output_dir}')
    if args.warmup < 0 or args.repeats < 1 or args.threads < 1:
        parser.error('warmup은 0 이상, repeats와 threads는 1 이상이어야 합니다.')
    if not 0 <= args.min_span_score <= 1:
        parser.error('min-span-score는 0~1이어야 합니다.')

    import torch
    torch.set_num_threads(args.threads)
    posts, _, audit = evaluate_test.prepare(args.corpus_dir, args.bio_data)
    test_path = args.corpus_dir / 'splits/test.jsonl'
    test_sha256 = train.file_sha256(test_path)
    if test_sha256 != TEST_SHA256 or len(posts) != 239:
        raise ValueError('고정된 공식 test 239편/입력 지문이 달라 측정을 중단합니다.')
    sample = select_length_spaced(posts, args.samples)

    warnings.filterwarnings('ignore', message='level=implicit.*', category=RuntimeWarning)
    started = time.perf_counter()
    detector = infer.SpanDetector(args.checkpoint_dir, device='cpu',
                                  min_span_score=args.min_span_score)
    loading_seconds = time.perf_counter() - started
    rows = []
    for number, post in enumerate(sample, 1):
        times = measure_one(detector, post, args.warmup, args.repeats)
        row = {'post_id': post['post_id'], 'characters': post_length(post),
               'median_ms': statistics.median(times),
               'p95_nearest_rank_ms': nearest_rank(times), 'times_ms': times}
        rows.append(row)
        print(f'{number}/{len(sample)} {row["post_id"]} '
              f'{row["characters"]} chars median={row["median_ms"]:.2f}ms', flush=True)

    medians = [row['median_ms'] for row in rows]
    report = {
        'measured_at_utc': datetime.now(timezone.utc).isoformat(),
        'data_version': 'corpus-v0 p2.3',
        'test_sha256': test_sha256,
        'checkpoint': str(args.checkpoint_dir),
        'model_version': detector.version,
        'model_sha256': train.file_sha256(args.checkpoint_dir / 'model.safetensors'),
        'official_test_posts': audit['official_test_posts'],
        'excluded_legacy_iaa_ids': audit['excluded_legacy_iaa_ids'],
        'eligible_test_posts': len(posts),
        'sample_policy': 'length-ranked equal-width bins; midpoint post from each bin',
        'sample_posts': len(rows),
        'device': 'cpu', 'cpu_name': args.cpu_name,
        'torch_version': torch.__version__, 'threads': torch.get_num_threads(),
        'posts_per_call': 1, 'window_batch_size': detector.batch_size,
        'min_span_score': args.min_span_score,
        'warmup_per_post': args.warmup, 'repeats_per_post': args.repeats,
        'model_loading_seconds_excluded': loading_seconds,
        'scope': 'tokenization+model+postprocessing+contract_validation; '
                 'excludes model loading and level/subject classifier',
        'post_median_distribution_ms': {
            'median': statistics.median(medians),
            'p95_nearest_rank': nearest_rank(medians),
            'max': max(medians),
        },
        'posts': rows,
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    target = args.output_dir / 'metrics.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('RESULT ' + json.dumps(report['post_median_distribution_ms']))
    print(f'Saved: {target}')


if __name__ == '__main__':
    main()
