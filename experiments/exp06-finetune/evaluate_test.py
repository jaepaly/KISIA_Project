"""승인된 기존 IAA 글 ID를 제외하고 공식 test 분할을 평가한다.

체크포인트로 예측하거나 저장된 예측을 재채점해 전체·등급별 지표를 기록한다.
분할·골드·체크포인트는 수정하지 않으며, 추론 호출에 골드를 전달하지 않는다.
경계·유형만 평가하며 기존 level/subject 임시 고정값은 평가하지 않는다.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import unicodedata

import infer
from prepare_bio import DataError, TYPES, read_jsonl, validate_channel
import train


def records(path):
    return [row for _, row in read_jsonl(path)]


def index_posts(rows):
    indexed = {}
    for row in rows:
        pid = row.get('post_id')
        if not isinstance(pid, str) or not pid or pid in indexed:
            raise DataError(f'Missing/duplicate post_id: {pid}')
        indexed[pid] = row
    return indexed


def legacy_iaa_ids(assignment, tests, expected_count=16):
    rows = assignment.get('글')
    if not isinstance(rows, list):
        raise DataError('Invalid IAA assignment')
    ids = []
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k] for k in ('persona_id', 'post')):
            raise DataError('Invalid IAA assignment ID')
        ids.append(f"{row['persona_id']}_{row['post']}")
    if len(set(ids)) != len(ids):
        raise DataError('Duplicate IAA assignment ID')
    if len(ids) != expected_count:
        raise DataError(f'IAA assignment count must be {expected_count}, got {len(ids)}')
    missing = set(ids) - set(tests)
    if missing:
        raise DataError(f'IAA IDs missing from official test: {sorted(missing)}')
    return set(ids)


def prepare(root: Path, bio_path: Path, *, expected_iaa_count=16):
    tests = index_posts(records(root / 'splits/test.jsonl'))
    training = index_posts(records(root / 'splits/train.jsonl'))
    bio = records(bio_path)
    leak = set(tests) & (set(training) | {r['post_id'] for r in bio})
    if leak:
        raise DataError(f'Test leakage, including excluded IAA: {sorted(leak)}')
    assignment = json.loads((root / 'gold/iaa/_assignment.json').read_text(encoding='utf-8-sig'))
    excluded = legacy_iaa_ids(assignment, tests, expected_iaa_count)
    selected = {pid: row for pid, row in tests.items() if pid not in excluded}
    gold, provenance, redundant = {}, {}, []
    source_files = []
    # 단서 글은 blind 정답을 우선하고, 잡담 글은 gold 최상위의 검수 정본을 사용한다.
    for source, files in [('blind', sorted((root / 'gold/blind').glob('*_spans.jsonl'))),
                          ('reviewed', sorted((root / 'gold').glob('*_spans.jsonl')))]:
        seen = set()
        for path in files:
            source_files.append(path)
            for row in records(path):
                pid = row.get('post_id')
                if pid not in selected or row.get('reviewed') is not True:
                    continue
                if pid in seen:
                    raise DataError(f'Duplicate {source} gold: {pid}')
                seen.add(pid)
                if pid in gold:
                    redundant.append(pid)
                    continue
                kind = selected[pid].get('kind')
                if (kind == 'noise' and source != 'reviewed') or (kind == 'clue' and source != 'blind'):
                    continue
                gold[pid], provenance[pid] = row, source
    missing = set(selected) - set(gold)
    if missing:
        raise DataError(f'Missing accepted gold (never assumed empty): {sorted(missing)}')
    span_ids = set()
    for pid, row in gold.items():
        _, _, texts = infer.input_channels(selected[pid])
        if row.get('texts') != texts:
            raise DataError(f'Gold/current NFC source mismatch: {pid}')
        if any(unicodedata.normalize('NFC', text) != text for text in row['texts'].values()):
            raise DataError(f'Non-NFC gold: {pid}')
        grouped = defaultdict(list)
        if not isinstance(row.get('spans'), list):
            raise DataError(f'Invalid gold spans: {pid}')
        for span in row['spans']:
            if span['span_id'] in span_ids:
                raise DataError(f'Duplicate span_id: {span["span_id"]}')
            span_ids.add(span['span_id'])
            grouped[span['text_id']].append(span)
        if set(grouped) - set(texts):
            raise DataError(f'Gold has an unknown channel: {pid}')
        for tid, text in texts.items():
            validate_channel(source=pid, text_id=tid, text=text, spans=grouped[tid])
    audit = {
        'official_test_posts': len(tests), 'evaluated_posts': len(selected),
        'excluded_legacy_iaa_ids': sorted(excluded),
        'exclusion_reason': 'Team approved excluding legacy IAA IDs from evaluation only; split unchanged.',
        'kind_counts': dict(Counter(r['kind'] for r in selected.values())),
        'gold_sources': dict(Counter(provenance.values())),
        'gold_spans': sum(len(r['spans']) for r in gold.values()),
        'noise_zero_gold_posts': sum(not gold[p]['spans'] for p, r in selected.items() if r['kind'] == 'noise'),
        'redundant_reviewed_ids_ignored': sorted(redundant),
        'test_train_post_overlap': 0, 'test_bio_post_overlap': 0,
        'test_bio_persona_overlap': len({r['persona_id'] for r in selected.values()} & {r['persona_id'] for r in bio}),
        'limitations': ['Post holdout, not persona holdout.',
                       'Noise is teacher-assisted reviewed gold, not blind; actual gold spans are retained.',
                       'Legacy IAA excluded, including any newer IAA work on different samples.',
                       'Current BIO checked for leakage; original checkpoint did not store its training-data hash.'],
        'input_sha256': {str(p): train.file_sha256(p) for p in
                         [root / 'splits/test.jsonl', root / 'splits/train.jsonl',
                          root / 'gold/iaa/_assignment.json', bio_path] + source_files},
    }
    return selected, gold, audit


def exact_span_sets(truth, guessed):
    counts = defaultdict(lambda: {'tp': 0, 'fp': 0, 'fn': 0})
    for key in truth.keys() | guessed.keys():
        actual, predicted = truth.get(key, set()), guessed.get(key, set())
        for label, spans in [('tp', actual & predicted), ('fp', predicted - actual), ('fn', actual - predicted)]:
            for span in spans:
                counts[span[2]][label] += 1
    def finish(c):
        tp, fp, fn = c['tp'], c['fp'], c['fn']
        return {**c, 'precision': tp / (tp + fp) if tp + fp else 0.0,
                'recall': tp / (tp + fn) if tp + fn else 0.0,
                'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}
    return {'overall': finish({k: sum(c[k] for c in counts.values()) for k in ('tp', 'fp', 'fn')}),
            'by_type': {kind: finish(c) for kind, c in sorted(counts.items())},
            'match_policy': 'identical start/end/type; one-to-one unique spans per channel'}


LEVELS = ('explicit', 'implicit', 'inferential')


def level_breakdown(truth, guessed, levels, overall):
    """일대일 부분 일치 결과를 예측 등급이 아닌 정답 스팬의 등급별로 집계한다.

    기존 채점기의 (IoU, 정답 인덱스, 예측 인덱스) 내림차순 탐욕 매칭을
    동점 처리까지 유지한다. 매칭되지 않은 예측은 등급 없는 FP로 남긴다.
    """
    counts = {level: {'tp': 0, 'fn': 0} for level in LEVELS}
    for key in truth.keys() | guessed.keys():
        actual, predicted = sorted(truth.get(key, set())), sorted(guessed.get(key, set()))
        candidates = sorted(
            ((train.span_iou(g, p), i, j)
             for i, g in enumerate(actual) for j, p in enumerate(predicted)
             if g[2] == p[2] and train.span_iou(g, p) >= 0.5), reverse=True)
        used_gold, used_pred = set(), set()
        for _, i, j in candidates:
            if i not in used_gold and j not in used_pred:
                used_gold.add(i)
                used_pred.add(j)
        for i, span in enumerate(actual):
            counts[levels[key][span]]['tp' if i in used_gold else 'fn'] += 1
    if any(sum(c[k] for c in counts.values()) != overall[k] for k in ('tp', 'fn')):
        raise DataError('Level matching differs from original partial scorer')
    precision, fp = overall['precision'], overall['fp']
    result = {}
    for level, c in counts.items():
        tp, fn = c['tp'], c['fn']
        support = tp + fn
        # 해당 등급의 정답이 없으면 성능을 0으로 단정하지 않는다.
        recall = tp / support if support else None
        proxy = (2 * precision * recall / (precision + recall)
                 if recall and precision else 0.0) if support else None
        conservative = 2 * tp / (2 * tp + fp + fn) if support else None
        result[level] = {
            **c, 'gold_spans': support, 'recall': recall,
            'proxy_f1': proxy,
            'proxy_allocated_fp': fp * tp / overall['tp'] if overall['tp'] else None,
            'conservative_fp': fp, 'conservative_f1': conservative,
        }
    return {
        'by_level': result,
        'level_policy': {
            'source': 'gold level; model level/subject are not evaluated',
            'matching': 'type equal, IoU >= 0.5; descending (IoU, gold index, prediction index), one-to-one',
            'proxy_formula': '2 * overall_precision * level_recall / (overall_precision + level_recall)',
            'proxy_assumption': 'Allocate FP proportionally to level TP; shared overall precision. Not level prediction F1.',
            'conservative_formula': '2 * level_tp / (2 * level_tp + overall_fp + level_fn)',
            'conservative_policy': 'Freeze global matches; remove predictions matched to other gold levels; retain every unmatched FP for each level.',
            'zero_policy': 'No gold support: recall/F1 null. Supported level with TP=0: F1=0. Total TP=0: proportional FP allocation undefined (null).',
        },
        'implicit_iaa_comparison': {
            'version': 'IAA v2, common 16 posts',
            'source': 'docs/evidence/iaa-v2-comparison.md',
            'baseline_partial_f1': 0.444,
            'baseline_policy': 'Use published rounded 44.4% per PM decision',
            'target_ratio': 0.8, 'target_f1': 0.444 * 0.8,
            'proxy_ratio': result['implicit']['proxy_f1'] / 0.444 if result['implicit']['proxy_f1'] is not None else None,
            'conservative_ratio': result['implicit']['conservative_f1'] / 0.444 if result['implicit']['conservative_f1'] is not None else None,
            'limitation': 'Different samples and metric definitions; proxy comparison is not level classification agreement.',
        },
    }


def score_subset(posts, gold, predictions):
    truth, guessed = {}, {}
    levels = {}
    for pid in posts:
        for tid in gold[pid]['texts']:
            levels[(pid, tid)] = {}
            for s in gold[pid]['spans']:
                if s['text_id'] != tid:
                    continue
                identity = (s['start'], s['end'], s['type'])
                if s.get('level') not in LEVELS:
                    raise DataError(f'Missing/invalid gold level: {pid}/{tid}')
                if identity in levels[(pid, tid)]:
                    raise DataError(f'Duplicate gold span identity: {pid}/{tid}')
                levels[(pid, tid)][identity] = s['level']
            truth[(pid, tid)] = {(s['start'], s['end'], s['type']) for s in gold[pid]['spans'] if s['text_id'] == tid}
            guessed[(pid, tid)] = {(s['start'], s['end'], s['type']) for s in predictions[pid] if s['text_id'] == tid}
    result = train.score_span_sets(truth, guessed)
    result['exact'] = exact_span_sets(truth, guessed)
    result.update(level_breakdown(truth, guessed, levels, result['overall']))
    return result


def fp_breakdown(metrics, by_kind):
    """부분 일치 채점의 등급 없는 FP를 빠짐없이 글 종류·스팬 유형별로 집계한다."""
    return {'total': metrics['overall']['fp'],
            'by_type': {k: v['fp'] for k, v in metrics['by_type'].items()},
            'by_kind': {k: v['overall']['fp'] for k, v in by_kind.items()},
            'by_kind_and_type': {k: {t: c['fp'] for t, c in v['by_type'].items()}
                                 for k, v in by_kind.items()}}


def rescore_saved(directory, posts, gold, audit):
    report = json.loads((directory / 'metrics.json').read_text(encoding='utf-8'))
    if report['audit']['input_sha256'] != audit['input_sha256']:
        raise DataError('Saved test input hashes differ; refusing to rescore changed data')
    rows = index_posts(records(directory / 'predictions.jsonl'))
    if set(rows) != set(posts):
        raise DataError('Saved prediction IDs differ from approved test selection')
    predictions = {}
    for pid, raw in rows.items():
        if raw.get('texts') != gold[pid]['texts']:
            raise DataError(f'Saved prediction source mismatch: {pid}')
        seen = set()
        for span in raw['candidates']:
            tid, start, end = span['text_id'], span['start'], span['end']
            if tid not in raw['texts'] or not 0 <= start < end <= len(raw['texts'][tid]) or raw['texts'][tid][start:end] != span['text']:
                raise DataError(f'Invalid saved prediction offset: {pid}')
            if span['type'] not in TYPES:
                raise DataError(f'Invalid saved prediction type: {pid}')
            identity = (tid, start, end, span['type'])
            if identity in seen:
                raise DataError(f'Duplicate saved prediction: {pid}')
            seen.add(identity)
        predictions[pid] = raw['candidates']
    scored = score_subset(posts, gold, predictions)
    if scored['overall'] != report['metrics']['overall']:
        raise DataError('Original partial metric changed during rescore')
    report['metrics'] = scored
    report['by_kind'] = {kind: score_subset([p for p, r in posts.items() if r['kind'] == kind], gold, predictions)
                         for kind in sorted({r['kind'] for r in posts.values()})}
    report['rescored_at_utc'] = datetime.now(timezone.utc).isoformat()
    report['fp_breakdown'] = fp_breakdown(scored, report['by_kind'])
    report['rescore_source'] = str(directory)
    report['model_inference_repeated'] = False
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus-dir', type=Path, default=Path('data/corpus/v0'))
    parser.add_argument('--bio-data', type=Path, default=train.DEFAULT_DATA)
    parser.add_argument('--audit-only', action='store_true')
    parser.add_argument('--checkpoint-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--min-span-score', type=float, default=0.7)
    parser.add_argument('--rescore-from', type=Path, help='Add exact, gold-level and FP metrics using saved predictions; no model execution')
    args = parser.parse_args()
    posts, gold, audit = prepare(args.corpus_dir, args.bio_data)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    if args.audit_only:
        return
    if (not args.checkpoint_dir and not args.rescore_from) or not args.output_dir or args.threads < 1:
        parser.error('Evaluation requires --checkpoint-dir, --output-dir and positive --threads')
    if args.output_dir.exists():
        parser.error('Output directory already exists; refusing to overwrite any previous test result')
    if 'runs' not in args.output_dir.parts:
        parser.error('Store local evaluation output under runs/')
    if args.rescore_from:
        report = rescore_saved(args.rescore_from, posts, gold, audit)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / 'metrics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report['metrics'], ensure_ascii=False, indent=2))
        print(f'Saved: {args.output_dir / "metrics.json"}')
        return
    import torch
    import transformers
    torch.set_num_threads(args.threads)
    detector = infer.SpanDetector(args.checkpoint_dir, device=args.device, min_span_score=args.min_span_score)
    predictions, outputs = {}, []
    started = time.perf_counter()
    for index, (pid, row) in enumerate(sorted(posts.items()), 1):
        # 공식 원문만 전달하며, 골드나 clue_plan 메타데이터는 추론에 사용하지 않는다.
        raw = detector.predict_raw({'post_id': pid, 'texts': row['texts']})
        predictions[pid] = raw['candidates']
        outputs.append(raw)
        if index % 25 == 0:
            print(f'test {index}/{len(posts)}', flush=True)
    elapsed = time.perf_counter() - started
    zero_noise = [p for p, r in posts.items() if r['kind'] == 'noise' and not gold[p]['spans']]
    report = {
        'measured_at_utc': datetime.now(timezone.utc).isoformat(), 'data_version': 'corpus-v0 p2.3',
        'checkpoint': str(args.checkpoint_dir), 'model_version': detector.version,
        'checkpoint_sha256': {p.name: train.file_sha256(p) for p in sorted(args.checkpoint_dir.glob('*.safetensors'))},
        'device': str(detector.device), 'threads': args.threads, 'torch': torch.__version__,
        'transformers': transformers.__version__,
        'min_span_score': args.min_span_score, 'max_length': 256, 'stride': 64,
        'threshold_policy': '0.7 selected on internal eval before test; no test threshold sweep.',
        'evaluated_attributes': ['boundary', 'type'], 'level_subject_evaluated': False,
        'audit': audit, 'metrics': score_subset(posts, gold, predictions),
        'by_kind': {kind: score_subset([p for p, r in posts.items() if r['kind'] == kind], gold, predictions)
                    for kind in sorted({r['kind'] for r in posts.values()})},
        'zero_gold_noise': {'posts': len(zero_noise),
                            'posts_with_false_spans': sum(bool(predictions[p]) for p in zero_noise),
                            'false_spans': sum(len(predictions[p]) for p in zero_noise)},
        'inference_seconds_excluding_model_load_and_save': elapsed,
        'latency_benchmark': False,
    }
    report['fp_breakdown'] = fp_breakdown(report['metrics'], report['by_kind'])
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / 'predictions.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in outputs), encoding='utf-8')
    (args.output_dir / 'metrics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['metrics'], ensure_ascii=False, indent=2))
    print(f'Saved: {args.output_dir / "metrics.json"}')


if __name__ == '__main__':
    main()
