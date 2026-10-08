"""저장된 학습 설정과 지문으로 내부 eval을 복원한다 (test는 읽지 않음)."""
import hashlib
import json

import train


def restore_eval(data, expected):
    split = expected['split']
    mode, ratio = split.split(':')
    if mode not in ('persona_holdout', 'persona_holdout_reviewed_only'):
        raise train.TrainError('Internal persona holdout required')
    config = expected.get('run_config')
    if config and train.file_sha256(data) != config['data_sha256']:
        raise train.TrainError('Training data hash differs from checkpoint')
    rows = train.read_jsonl(data)
    _, eval_rows, restored = train.split_examples(
        rows, eval_ratio=float(ratio), seed=expected['seed'], overfit=0,
        eval_reviewed_only=mode == 'persona_holdout_reviewed_only')
    if restored != split:
        raise train.TrainError('Restored split differs from checkpoint')
    digest = hashlib.sha256(json.dumps([r['example_id'] for r in eval_rows]).encode('utf-8')).hexdigest()
    if config:
        if config['eval']['examples'] != len(eval_rows) or config['eval']['example_ids_sha256'] != digest:
            raise train.TrainError('Internal eval example hash/count differs from checkpoint')
    return eval_rows, digest
