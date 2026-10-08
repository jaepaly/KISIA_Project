"""저장된 내부 eval 예측으로 JOB 문턱만 높여 비교한다. 모델·test는 읽지 않는다."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from internal_eval import restore_eval
import train


def filter_job(predictions, scores, threshold, baseline_threshold):
    """이미 겹침 해소·기본 문턱을 통과한 후보의 부분집합만 남긴다."""
    if not baseline_threshold <= threshold <= 1:
        raise train.TrainError('JOB threshold must not be lower than saved baseline')
    return {key: {s for s in spans if s[2] != 'JOB' or scores[(key, s)] >= threshold}
            for key, spans in predictions.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis-dir', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--job-thresholds', type=float, nargs='+', default=[0.7, 0.75, 0.8, 0.85, 0.9, 0.95])
    args = parser.parse_args()
    if args.output_dir.exists() or 'runs' not in args.output_dir.parts:
        parser.error('Choose a new output directory under runs/')
    summary = json.loads((args.analysis_dir / 'summary.json').read_text(encoding='utf-8'))
    expected = json.loads((Path(summary['checkpoint']) / 'trainer_state.json').read_text(encoding='utf-8'))['eval']
    rows, digest = restore_eval(args.data, expected)
    if train.file_sha256(args.data) != summary['data_sha256'] or digest != summary['eval_example_ids_sha256']:
        raise train.TrainError('Saved analysis input/eval hashes differ')
    baseline = summary['min_span_score']
    if baseline != expected['min_span_score']:
        raise train.TrainError('Use analysis at checkpoint operational threshold')
    gold, sources = defaultdict(set), {}
    for row in rows:
        key = (row['post_id'], row['text_id'])
        sources[key] = row['text']
        gold[key].update((s['start'], s['end'], s['type']) for s in row['spans'])
    pred, scores = {}, {}
    for line in (args.analysis_dir / 'predictions.jsonl').read_text(encoding='utf-8').splitlines():
        rec = json.loads(line)
        key = (rec['post_id'], rec['text_id'])
        if key not in sources or key in pred or rec['text'] != sources[key]:
            raise train.TrainError('Saved prediction channel/source mismatch')
        spans = set()
        for s in rec['predicted']:
            span = (s['start'], s['end'], s['type'])
            confidence = s['confidence']
            if (span in spans or not 0 <= span[0] < span[1] <= len(sources[key])
                    or s['text'] != sources[key][span[0]:span[1]]
                    or not isinstance(confidence, (int, float)) or not math.isfinite(confidence)
                    or not baseline <= confidence <= 1):
                raise train.TrainError('Invalid saved span/confidence')
            spans.add(span)
            scores[(key, span)] = confidence
        if spans != train.resolve_overlapping_spans(spans):
            raise train.TrainError('Saved spans overlap')
        pred[key] = spans
    if set(pred) != set(sources):
        raise train.TrainError('Missing internal eval channels')
    base_metrics = train.score_span_sets(gold, pred)
    for original in (summary['metrics'], expected):
        if any(base_metrics['overall'][k] != original['overall'][k] for k in ('tp', 'fp', 'fn')):
            raise train.TrainError('Saved counts do not reproduce baseline')
    results = []
    for threshold in sorted(set([baseline, *args.job_thresholds])):
        filtered = filter_job(pred, scores, threshold, baseline)
        metrics = train.score_span_sets(gold, filtered)
        removed = [{'post_id': key[0], 'text_id': key[1], 'start': s[0], 'end': s[1],
                    'type': s[2], 'text': sources[key][s[0]:s[1]], 'confidence': scores[(key, s)],
                    'context': sources[key][max(0, s[0]-60):s[1]+60]}
                   for key in sorted(pred) for s in sorted(pred[key] - filtered[key])]
        result = {'job_threshold': threshold, 'other_threshold': baseline, 'metrics': metrics,
                  'removed_spans': removed,
                  'tp_lost': base_metrics['overall']['tp'] - metrics['overall']['tp'],
                  'fp_reduced': base_metrics['overall']['fp'] - metrics['overall']['fp']}
        results.append(result)
        print(json.dumps({'job_threshold': threshold, 'overall': metrics['overall'],
                          'job': metrics['by_type'].get('JOB'),
                          'tp_lost': result['tp_lost'], 'fp_reduced': result['fp_reduced']}, ensure_ascii=False))
    report = {'measured_at_utc': datetime.now(timezone.utc).isoformat(),
              'checkpoint': summary['checkpoint'], 'data_sha256': summary['data_sha256'],
              'checkpoint_sha256': {p.name: train.file_sha256(p)
                                    for p in Path(summary['checkpoint']).glob('*.safetensors')},
              'eval_example_ids_sha256': digest, 'eval_windows': len(rows),
              'rules_included': False, 'test_opened': False, 'exp17b_opened': False,
              'scope': 'exploratory internal eval; no operational setting change',
              'merge_policy': 'resolve overlap first; raise JOB threshold; no suppressed span revival',
              'results': results}
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / 'metrics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Saved: {args.output_dir / "metrics.json"}')


if __name__ == '__main__':
    main()
