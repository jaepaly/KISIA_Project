"""공식 test에서 기존 도구 3종의 미탐 중 koelectra-v1이 회수한 비율을 잰다.

exp01의 설계 단서 결과를 재사용하지 않고 동일한 test 글·채널에 세 도구를
다시 적용한다. 기존 도구에는 type 불문 IoU 0.5 매칭을 허용하고, v1에는
공식 partial 채점과 동일한 type 일치·1:1 매칭을 적용한다.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import sys

import evaluate_test
from prepare_bio import DataError
import train


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / 'experiments/exp01-baseline'


def model_matched_gold(gold: dict, predictions: dict) -> set[str]:
    """기존 partial 채점기의 정렬·탐욕 1:1 규칙으로 맞힌 span_id를 구한다."""
    matched = set()
    for pid, record in gold.items():
        for tid in record['texts']:
            actual = sorted({(s['start'], s['end'], s['type']) for s in record['spans']
                             if s['text_id'] == tid})
            predicted = sorted({(s['start'], s['end'], s['type']) for s in predictions[pid]
                                if s['text_id'] == tid})
            ids = {(s['start'], s['end'], s['type']): s['span_id'] for s in record['spans']
                   if s['text_id'] == tid}
            candidates = sorted(
                ((train.span_iou(g, p), i, j)
                 for i, g in enumerate(actual) for j, p in enumerate(predicted)
                 if g[2] == p[2] and train.span_iou(g, p) >= 0.5), reverse=True)
            used_gold, used_pred = set(), set()
            for _, i, j in candidates:
                if i not in used_gold and j not in used_pred:
                    used_gold.add(i)
                    used_pred.add(j)
                    matched.add(ids[actual[i]])
    return matched


def baseline_missed_gold(gold: dict, tool_predictions: dict) -> set[str]:
    """exp01 원칙: 세 도구 중 하나라도 type 불문 IoU 0.5면 탐지로 본다."""
    missed = set()
    for pid, record in gold.items():
        for span in record['spans']:
            gold_interval = (span['start'], span['end'], span['type'])
            guesses = tool_predictions.get((pid, span['text_id']), [])
            if not any(train.span_iou(gold_interval, (p['start'], p['end'], p['type'])) >= 0.5
                       for p in guesses):
                missed.add(span['span_id'])
    return missed


def run_baselines(posts: dict) -> tuple[dict, dict]:
    """같은 원문에 exp01 탐지 함수 세 가지를 적용한다. 조용한 폴백은 금지한다."""
    sys.path.insert(0, str(BASELINE))
    import run_regex
    import run_presidio
    import run_koreanpii

    if not run_presidio.HAS_PRESIDIO or run_koreanpii._NLP is None:
        raise DataError('Presidio와 spaCy ko_core_news_sm 둘 다 필요합니다. 폴백 결과로 채점하지 않습니다.')
    analyzer = run_presidio.build_analyzer()
    if analyzer is None:
        raise DataError('한국어 Presidio Analyzer를 생성하지 못했습니다.')
    if set(analyzer.supported_languages) != {'ko'}:
        raise DataError('Presidio 초기화가 대체 엔진으로 폴백했습니다. 확정 한국어 엔진만 사용합니다.')
    predicted = {}
    counts = Counter()
    for index, (pid, post) in enumerate(sorted(posts.items()), 1):
        for tid, text in post['texts'].items():
            regex = run_regex.detect(text)
            results = analyzer.analyze(text=text, language='ko')
            presidio = [{'start': r.start, 'end': r.end, 'type': r.entity_type}
                        for r in results]
            koreanpii = run_koreanpii.detect_korean_ner(text)
            for name, spans in (('regex', regex), ('presidio', presidio), ('koreanpii', koreanpii)):
                counts[name] += len(spans)
                if any(not isinstance(s['start'], int) or not isinstance(s['end'], int)
                       or not 0 <= s['start'] < s['end'] <= len(text) for s in spans):
                    raise DataError(f'기존 도구의 잘못된 offset: {pid}/{tid}/{name}')
            predicted[(pid, tid)] = regex + presidio + koreanpii
        if index % 25 == 0:
            print(f'baseline {index}/{len(posts)}', flush=True)
    meta = {'engines': ['exp01 regex 8 patterns', 'Presidio ko_core_news_sm + kr_mobile',
                        'spaCy ko_core_news_sm'],
            'versions': {'presidio-analyzer': version('presidio-analyzer'),
                         'spacy': version('spacy'),
                         'ko_core_news_sm': run_koreanpii._NLP.meta.get('version')},
            'raw_prediction_counts': dict(counts),
            'source_sha256': {str(Path('experiments/exp01-baseline') / name): train.file_sha256(BASELINE / name)
                              for name in ('run_regex.py', 'run_presidio.py', 'run_koreanpii.py')}}
    return predicted, meta


def score_additional_rate(gold, predictions, tool_predictions, expected_tp):
    """v1/v2·규칙 켬/끔 모두 받는 공통 경로. 저장 v1 검증 경로와 별개다."""
    if set(predictions) != set(gold):
        raise DataError('모델 예측의 글 목록이 골드와 다릅니다.')
    channels = {(pid, tid) for pid, row in gold.items() for tid in row['texts']}
    if set(tool_predictions) != channels:
        raise DataError('기존 도구의 채널 목록이 다릅니다. 빈 탐지도 []로 기록해야 합니다.')
    for (pid, tid), spans in tool_predictions.items():
        size = len(gold[pid]['texts'][tid])
        for span in spans:
            if (type(span.get('start')) is not int or type(span.get('end')) is not int
                    or not 0 <= span['start'] < span['end'] <= size
                    or not isinstance(span.get('type'), str) or not span['type']):
                raise DataError(f'기존 도구의 잘못된 스팬: {pid}/{tid}')
    matched = model_matched_gold(gold, predictions)
    if len(matched) != expected_tp:
        raise DataError('추가 탐지율의 모델 매칭 수가 공식 partial TP와 다릅니다.')
    missed = baseline_missed_gold(gold, tool_predictions)
    recovered = missed & matched
    def summary(ids):
        denominator, numerator = len(missed & ids), len(recovered & ids)
        return {'recovered': numerator, 'baseline_missed': denominator,
                'additional_rate': numerator / denominator if denominator else None}
    all_ids = {s['span_id'] for row in gold.values() for s in row['spans']}
    return {
        'overall': summary(all_ids),
        'by_level': {level: summary({s['span_id'] for row in gold.values()
                                   for s in row['spans'] if s['level'] == level})
                     for level in evaluate_test.LEVELS},
        'scoring': {'baseline': 'any of 3 tools; type ignored; IoU >= 0.5; no 1:1 restriction',
                    'model': 'type equal; IoU >= 0.5; official greedy 1:1 matching'},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved-test-dir', type=Path,
                        default=ROOT / 'experiments/exp06-finetune/runs/test_v1_lr5e-5_t07')
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT / 'experiments/exp06-finetune/runs/w7_additional_rate')
    args = parser.parse_args()
    if args.output_dir.exists() or 'runs' not in args.output_dir.parts:
        parser.error('새로운 runs/ 하위 출력 디렉터리를 지정하세요. 기존 결과는 덮어쓰지 않습니다.')
    if Path.cwd().resolve() != ROOT:
        parser.error('저장된 평가와 동일한 입력 경로 지문을 위해 저장소 루트에서 실행하세요.')

    posts, gold, audit = evaluate_test.prepare(
        Path('data/corpus/v0'), Path('experiments/exp06-finetune/runs/bio/train.jsonl'))
    saved = evaluate_test.rescore_saved(args.saved_test_dir, posts, gold, audit)
    if saved['model_version'] != 'v1_lr5e-5/checkpoint-epoch-10' or saved['min_span_score'] != 0.7:
        raise DataError('확정 v1 checkpoint-epoch-10, 임계값 0.7의 저장 예측만 사용합니다.')
    raw_rows = evaluate_test.index_posts(evaluate_test.records(args.saved_test_dir / 'predictions.jsonl'))
    model_predictions = {pid: row['candidates'] for pid, row in raw_rows.items()}
    model_matched = model_matched_gold(gold, model_predictions)
    if len(model_matched) != saved['metrics']['overall']['tp']:
        raise DataError('모델 1:1 매칭 결과가 공식 test TP와 다릅니다.')

    tool_predictions, baseline_meta = run_baselines(posts)
    missed = baseline_missed_gold(gold, tool_predictions)
    recovered = missed & model_matched
    by_level = {}
    for level in evaluate_test.LEVELS:
        level_ids = {s['span_id'] for row in gold.values() for s in row['spans'] if s['level'] == level}
        denominator = len(level_ids & missed)
        numerator = len(level_ids & recovered)
        by_level[level] = {'recovered': numerator, 'baseline_missed': denominator,
                           'additional_rate': numerator / denominator if denominator else None}
    report = {
        'measured_at_utc': datetime.now(timezone.utc).isoformat(),
        'data_version': saved['data_version'],
        'checkpoint': saved['checkpoint'],
        'checkpoint_sha256': saved['checkpoint_sha256'],
        'min_span_score': saved['min_span_score'],
        'test_posts': len(posts), 'gold_spans': sum(len(row['spans']) for row in gold.values()),
        'test_sha256': next(value for path, value in audit['input_sha256'].items()
                            if path.endswith('test.jsonl')),
        'scoring': {'baseline': 'any of 3 tools; type ignored; IoU >= 0.5; no 1:1 restriction',
                    'model': 'type equal; IoU >= 0.5; official greedy 1:1 matching'},
        'overall': {'recovered': len(recovered), 'baseline_missed': len(missed),
                    'additional_rate': len(recovered) / len(missed) if missed else None},
        'by_level': by_level,
        'baseline': baseline_meta,
        'saved_model_predictions': str(args.saved_test_dir.resolve().relative_to(ROOT) / 'predictions.jsonl'),
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    target = args.output_dir / 'metrics.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'overall': report['overall'], 'by_level': by_level,
                      'baseline_raw_prediction_counts': baseline_meta['raw_prediction_counts']},
                     ensure_ascii=False, indent=2))
    print(f'Saved: {target}')


if __name__ == '__main__':
    main()
