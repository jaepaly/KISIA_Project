"""Compare epochs 1..10 on INTERNAL eval only. Never opens test or gold files."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gc
import json
from pathlib import Path

import infer
import train
from evaluate_test import exact_span_sets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--data', type=Path, default=train.DEFAULT_DATA)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists() or 'runs' not in args.output_dir.parts or args.threads < 1:
        parser.error('Use a new output directory under runs/ and positive thread count')
    checkpoints = [args.run_dir / f'checkpoint-epoch-{epoch}' for epoch in range(1, 11)]
    states = [json.loads((p / 'trainer_state.json').read_text(encoding='utf-8')) for p in checkpoints]
    baseline = states[0]['eval']
    for epoch, state in enumerate(states, 1):
        if state['completed_epochs'] != epoch or any(state['eval'][k] != baseline[k] for k in ('seed', 'split')):
            raise ValueError('Epoch split/seed mismatch')
    if not baseline['split'].startswith('persona_holdout:'):
        raise ValueError('Internal persona holdout required')
    rows = train.read_jsonl(args.data)
    _, eval_rows, _ = train.split_examples(rows, eval_ratio=float(baseline['split'].split(':')[1]),
                                           seed=baseline['seed'], overfit=0)
    sources, gold = {}, defaultdict(set)
    for row in eval_rows:
        key = (row['post_id'], row['text_id'])
        if key in sources and sources[key] != row['text']:
            raise ValueError('Conflicting internal eval source')
        sources[key] = row['text']
        gold[key].update((s['start'], s['end'], s['type']) for s in row['spans'])
    import torch
    torch.set_num_threads(args.threads)
    results = []
    for epoch, checkpoint in enumerate(checkpoints, 1):
        detector = infer.SpanDetector(checkpoint, device=args.device, min_span_score=0.7)
        pred = {key: {(s['start'], s['end'], s['type']) for s in detector.predict_channel(text)}
                for key, text in sources.items()}
        result = {'epoch': epoch, 'checkpoint': str(checkpoint),
                  'checkpoint_sha256': {p.name: train.file_sha256(p) for p in checkpoint.glob('*.safetensors')},
                  'partial': train.score_span_sets(gold, pred)['overall'],
                  'exact': exact_span_sets(gold, pred)['overall']}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        del detector
        gc.collect()
        if args.device.startswith('cuda'):
            torch.cuda.empty_cache()
    report = {'measured_at_utc': datetime.now(timezone.utc).isoformat(), 'data_version': 'corpus-v0 p2.3',
              'data_sha256': train.file_sha256(args.data), 'seed': baseline['seed'],
              'split': baseline['split'], 'eval_windows': len(eval_rows), 'eval_channels': len(sources),
              'device': args.device, 'threads': args.threads, 'min_span_score': 0.7,
              'merge_policy': 'longest_first_no_overlap_v1', 'test_opened': False,
              'selection_caveat': 'Post-test internal-eval comparison; never compare additional epochs on the opened test.',
              'results': results,
              'best_epoch_by_internal_partial_f1': max(results, key=lambda r: (r['partial']['f1'], -r['epoch']))['epoch']}
    table = '| epoch | partial F1 | exact F1 | P | R | TP / FP / FN |\n|---|---|---|---|---|---|\n'
    for row in results:
        m = row['partial']
        table += f"| {row['epoch']} | {m['f1']:.4f} | {row['exact']['f1']:.4f} | {m['precision']:.4f} | {m['recall']:.4f} | {m['tp']} / {m['fp']} / {m['fn']} |\n"
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / 'metrics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (args.output_dir / 'comparison.md').write_text(table, encoding='utf-8')
    print(table)
    print(f'Saved: {args.output_dir}')


if __name__ == '__main__':
    main()
