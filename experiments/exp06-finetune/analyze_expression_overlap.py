"""W7 test 정답을 실제 학습 글의 동일 유형·표기 출현 여부로 나눠 재현율을 계산한다.

저장된 예측과 검수된 공식 test 정답만 재채점한다. 모델은 다시 실행하지 않고
원문·개별 스팬은 출력하지 않는다. 운영 모델 선택을 위한 추가 test 탐색이 아니다.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unicodedata

import evaluate_test
from prepare_bio import DataError, load_split_ids, load_training_channels
import train


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / 'experiments/exp06-finetune/runs'
TEST_SHA256 = '9662a167f530f47318da2bd37a8401988ee74555393d6cd377fa84dfe8a886ad'
PROFILES = {
    'reviewed': {
        'run': RUNS / 'w7_reviewed_only',
        'bio': Path('experiments/exp06-finetune/runs/bio_w7_reviewed/train.jsonl'),
        'saved': RUNS / 'w7_test_reviewed_5e-5',
        'include_unreviewed': False,
    },
    'teacher': {
        'run': RUNS / 'w7_teacher_lr1e-5_diagnostic',
        'bio': Path('experiments/exp06-finetune/runs/bio_w7_teacher/train.jsonl'),
        'saved': RUNS / 'w7_test_teacher_1e-5',
        'include_unreviewed': True,
    },
}

def surface(text: str) -> str:
    """어휘 일부를 조사로 오인하지 않도록 원문 NFC와 앞뒤 공백만 정규화한다."""
    return unicodedata.normalize('NFC', text).strip()


def matched_gold_ids(gold: dict, predictions: dict) -> set[tuple[str, str, int, int, str]]:
    """기존 partial 채점과 동일한 (IoU, gold index, prediction index) 탐욕 매칭."""
    matched = set()
    for pid, row in gold.items():
        for tid in row['texts']:
            actual = sorted({(s['start'], s['end'], s['type']) for s in row['spans']
                             if s['text_id'] == tid})
            predicted = sorted({(s['start'], s['end'], s['type']) for s in predictions[pid]
                                if s['text_id'] == tid})
            candidates = sorted(((train.span_iou(a, p), i, j)
                                 for i, a in enumerate(actual) for j, p in enumerate(predicted)
                                 if a[2] == p[2] and train.span_iou(a, p) >= 0.5), reverse=True)
            used_gold, used_pred = set(), set()
            for _, i, j in candidates:
                if i not in used_gold and j not in used_pred:
                    used_gold.add(i)
                    used_pred.add(j)
            matched.update((pid, tid, *actual[i]) for i in used_gold)
    return matched


def training_surfaces(profile: dict) -> tuple[set[tuple[str, str]],
                                              set[tuple[str, str, str]], dict]:
    state_path = profile['run'] / 'checkpoint-epoch-10/trainer_state.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    config = state['eval']['run_config']
    if config['data_sha256'] != train.file_sha256(profile['bio']):
        raise DataError('저장 체크포인트와 현재 BIO의 지문이 다릅니다.')
    bio = evaluate_test.records(profile['bio'])
    train_personas = set(config['train']['personas'])
    eval_personas = set(config['eval']['personas'])
    if train_personas & eval_personas or not train_personas or not eval_personas:
        raise DataError('저장 run의 train/eval 인물 분리가 잘못됐습니다.')
    actual_train_rows = [r for r in bio if r['persona_id'] in train_personas]
    actual_hash = hashlib.sha256(json.dumps(
        [r['example_id'] for r in actual_train_rows]).encode('utf-8')).hexdigest()
    if (len(actual_train_rows) != config['train']['examples']
            or actual_hash != config['train']['example_ids_sha256']):
        raise DataError('실제 학습 예제 목록이 저장 run과 다릅니다.')
    train_posts = {r['post_id'] for r in actual_train_rows}
    train_ids, test_ids = load_split_ids(Path('data/corpus/v0/splits'))
    channels, _ = load_training_channels(Path('data/corpus/v0/gold'), train_ids, test_ids,
                                          include_unreviewed=profile['include_unreviewed'])
    all_keys, same_keys, sourced_posts = set(), set(), set()
    for channel in channels:
        if channel['post_id'] not in train_posts:
            continue
        sourced_posts.add(channel['post_id'])
        for span in channel['spans']:
            key = (span['type'], surface(span['text']))
            all_keys.add(key)
            same_keys.add((channel['persona_id'], *key))
    if sourced_posts != train_posts:
        raise DataError('학습 BIO와 골드 원본의 글 ID가 다릅니다.')
    return all_keys, same_keys, {
        'train_posts': len(train_posts), 'train_personas': len(train_personas),
        'eval_personas_excluded': len(eval_personas), 'train_examples': len(actual_train_rows),
        'bio_sha256': config['data_sha256'], 'train_example_ids_sha256': actual_hash,
    }


def split_recall(gold: dict, matched: set, all_keys: set, same_keys: set) -> dict:
    counts = defaultdict(lambda: {'gold': 0, 'tp': 0})
    for pid, row in gold.items():
        persona = row['persona_id']
        for span in row['spans']:
            identity = (pid, span['text_id'], span['start'], span['end'], span['type'])
            key = (span['type'], surface(span['text']))
            seen_all = key in all_keys
            seen_same = (persona, *key) in same_keys
            if seen_same and not seen_all:
                raise DataError('같은 인물 출현은 전체 출현에도 포함돼야 합니다.')
            for scope, seen in [('all_personas', seen_all), ('same_persona', seen_same)]:
                for level in ('overall', span['level']):
                    bucket = counts[(scope, level, 'seen' if seen else 'unseen')]
                    bucket['gold'] += 1
                    bucket['tp'] += identity in matched
    result = defaultdict(dict)
    for (scope, level, seen), c in counts.items():
        result[scope].setdefault(level, {})[seen] = {
            **c, 'fn': c['gold'] - c['tp'],
            'recall': c['tp'] / c['gold'] if c['gold'] else None,
        }
    return dict(result)


def analyze(profile: dict) -> tuple[dict, dict, set, set]:
    posts, gold, audit = evaluate_test.prepare(Path('data/corpus/v0'), profile['bio'])
    if audit['input_sha256'][str(Path('data/corpus/v0/splits/test.jsonl'))] != TEST_SHA256:
        raise DataError('공식 test 지문이 변경됐습니다.')
    saved = evaluate_test.rescore_saved(profile['saved'], posts, gold, audit)
    expected_version = f"{profile['run'].name}/checkpoint-epoch-10"
    weight_path = profile['run'] / 'checkpoint-epoch-10/model.safetensors'
    if (saved['model_version'] != expected_version
            or saved['checkpoint_sha256']['model.safetensors'] != train.file_sha256(weight_path)):
        raise DataError('저장 예측과 선택한 체크포인트가 다릅니다.')
    rows = evaluate_test.index_posts(evaluate_test.records(profile['saved'] / 'predictions.jsonl'))
    predictions = {pid: row['candidates'] for pid, row in rows.items()}
    matched = matched_gold_ids(gold, predictions)
    expected = saved['metrics']
    explicit_matches = sum(any(s['text_id'] == tid and s['start'] == start
                               and s['end'] == end and s['type'] == kind
                               and s['level'] == 'explicit' for s in gold[pid]['spans'])
                           for pid, tid, start, end, kind in matched)
    if (len(matched) != expected['overall']['tp']
            or explicit_matches != expected['by_level']['explicit']['tp']):
        raise DataError('동일 표현 분석의 partial 매칭이 공식 채점과 다릅니다.')
    all_keys, same_keys, source = training_surfaces(profile)
    result = split_recall(gold, matched, all_keys, same_keys)
    for scope in result.values():
        for level, expected_gold, expected_tp in (
                ('overall', audit['gold_spans'], expected['overall']['tp']),
                ('explicit', 112, expected['by_level']['explicit']['tp'])):
            rows = scope[level]
            if (sum(v['gold'] for v in rows.values()) != expected_gold
                    or sum(v['tp'] for v in rows.values()) != expected_tp):
                raise DataError('동일 표현 분석의 정답 수/TP가 공식 점수와 다릅니다.')
    report = {
        'model_version': saved['model_version'], 'checkpoint': saved['checkpoint'],
        'checkpoint_sha256': saved['checkpoint_sha256'], 'source': source,
        'matching': 'official partial: same type, IoU >= 0.5, greedy one-to-one',
        'surface_policy': 'Exact original text after NFC and surrounding-whitespace stripping; no particle removal',
        'scope': 'actual BIO training posts only; exclude held-out eval personas and every official test post',
        'result': result,
    }
    return report, gold, matched, all_keys


def fixed_cohort_recall(gold: dict, reference_keys: set,
                        matches: dict[str, set]) -> dict:
    """교사 학습 글에도 원문 동일 표기가 없는 명시 정답을 두 모델에 공통 적용한다."""
    cohort = {
        (pid, span['text_id'], span['start'], span['end'], span['type'])
        for pid, row in gold.items() for span in row['spans']
        if span['level'] == 'explicit'
        and (span['type'], surface(span['text'])) not in reference_keys
    }
    if not cohort:
        raise DataError('고정 비교 묶음에 명시 정답이 없습니다.')
    return {
        'definition': 'teacher training posts: explicit gold without same type and exact NFC surface',
        'gold': len(cohort),
        'profiles': {
            name: {'tp': len(cohort & matched), 'fn': len(cohort - matched),
                   'recall': len(cohort & matched) / len(cohort)}
            for name, matched in matches.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=RUNS / 'w7_expression_overlap')
    args = parser.parse_args()
    if Path.cwd().resolve() != ROOT:
        parser.error('입력 지문 비교를 위해 저장소 루트에서 실행하세요.')
    if not args.output_dir.resolve().is_relative_to(RUNS.resolve()) or args.output_dir.exists():
        parser.error('기존 결과를 덮어쓰지 않도록 새 runs/ 출력 경로를 지정하세요.')
    analyses = {name: analyze(profile) for name, profile in PROFILES.items()}
    gold = analyses['teacher'][1]
    if {pid: row['spans'] for pid, row in analyses['reviewed'][1].items()} != {
            pid: row['spans'] for pid, row in gold.items()}:
        raise DataError('두 모델의 test 정답 묶음이 달라 고정 비교를 할 수 없습니다.')
    report = {
        'measured_at_utc': datetime.now(timezone.utc).isoformat(),
        'data_version': 'corpus-v0 p2.3', 'test_sha256': TEST_SHA256,
        'test_posts': 239, 'test_gold_spans': 358,
        'profiles': {name: item[0] for name, item in analyses.items()},
        'fixed_cohort': fixed_cohort_recall(
            gold, analyses['teacher'][3],
            {name: item[2] for name, item in analyses.items()}),
        'limitations': [
            'Surface equality is a heuristic, not a guarantee of memorization or generalization.',
            'Post holdout is not persona holdout; similar wording and shared facts remain possible.',
            'Teacher label and rule directions were selected after test error analysis.',
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    target = args.output_dir / 'metrics.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for name, item in report['profiles'].items():
        print(json.dumps({'profile': name, 'result': item['result']}, ensure_ascii=False))
    print(json.dumps({'fixed_cohort': report['fixed_cohort']}, ensure_ascii=False))
    print(f'Saved: {target}')


if __name__ == '__main__':
    main()
