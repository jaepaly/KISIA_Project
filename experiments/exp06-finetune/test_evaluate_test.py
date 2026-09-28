"""모델 없이 평가 대상 선택과 채점 로직을 검증하는 회귀 테스트."""
import json
from pathlib import Path
import tempfile
import unittest

from evaluate_test import prepare as prepare_data, score_subset, legacy_iaa_ids, exact_span_sets, rescore_saved
from prepare_bio import DataError


def prepare(root, bio):
    return prepare_data(root, bio, expected_iaa_count=1)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bio = self.root / 'bio.jsonl'
        self.posts = [{'post_id': 'X_b01', 'persona_id': 'X', 'kind': 'clue', 'texts': {'body': '집'}},
                      {'post_id': 'X_b02', 'persona_id': 'X', 'kind': 'noise', 'texts': {'body': '집'}},
                      {'post_id': 'X_b03', 'persona_id': 'X', 'kind': 'clue', 'texts': {'body': '새 글'}}]
        self.span = {'span_id': 'X_b01_s01', 'text_id': 'body', 'start': 0, 'end': 1,
                     'text': '집', 'type': 'REL_HOME', 'level': 'inferential', 'subject': 'self'}
        self.blind = {**self.posts[0], 'reviewed': True, 'spans': [self.span]}
        self.noise = {**self.posts[1], 'reviewed': True, 'spans': [{**self.span, 'span_id': 'X_b02_s01'}]}
        self.write('splits/test.jsonl', self.posts)
        self.write('splits/train.jsonl', [{'post_id': 'X_b04', 'persona_id': 'X'}])
        self.write('bio.jsonl', [{'post_id': 'X_b04', 'persona_id': 'X'}])
        self.write('gold/blind/X_spans.jsonl', [self.blind])
        self.write('gold/X_spans.jsonl', [self.noise])
        path = self.root / 'gold/iaa/_assignment.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'글': [{'persona_id': 'X', 'post': 'b03'}]}), encoding='utf-8')

    def write(self, relative, rows):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')

    def test_exclusion_and_positive_noise(self):
        posts, gold, audit = prepare(self.root, self.bio)
        self.assertEqual(set(posts), {'X_b01', 'X_b02'})
        self.assertEqual(audit['excluded_legacy_iaa_ids'], ['X_b03'])
        self.assertEqual(audit['gold_spans'], 2)
        self.assertEqual(audit['noise_zero_gold_posts'], 0)
        predictions = {pid: row['spans'] for pid, row in gold.items()}
        self.assertEqual(score_subset(posts, gold, predictions)['overall']['f1'], 1.0)

    def test_missing_gold_not_empty(self):
        self.write('gold/X_spans.jsonl', [])
        with self.assertRaisesRegex(DataError, 'Missing accepted gold'):
            prepare(self.root, self.bio)

    def test_current_source_required(self):
        self.write('gold/blind/X_spans.jsonl', [{**self.blind, 'texts': {'body': '옛 글'}}])
        with self.assertRaisesRegex(DataError, 'source mismatch'):
            prepare(self.root, self.bio)

    def test_excluded_iaa_still_checked_for_leakage(self):
        self.write('bio.jsonl', [{'post_id': 'X_b03', 'persona_id': 'X'}])
        with self.assertRaisesRegex(DataError, 'leakage'):
            prepare(self.root, self.bio)

    def test_wrong_type_is_not_true_positive(self):
        posts, gold, _ = prepare(self.root, self.bio)
        guesses = {pid: [{**span, 'type': 'AGE'} for span in row['spans']] for pid, row in gold.items()}
        metrics = score_subset(posts, gold, guesses)['overall']
        self.assertEqual((metrics['tp'], metrics['fp'], metrics['fn']), (0, 2, 2))

    def test_duplicate_iaa_ids_fail(self):
        row = {'persona_id': 'X', 'post': 'b03'}
        with self.assertRaisesRegex(DataError, 'Duplicate IAA'):
            legacy_iaa_ids({'글': [row, row]}, {'X_b03'}, 2)

    def test_missing_iaa_id_fails(self):
        with self.assertRaisesRegex(DataError, 'missing from official test'):
            legacy_iaa_ids({'글': [{'persona_id': 'X', 'post': 'typo'}]}, {'X_b03'}, 1)

    def test_iaa_count_fails(self):
        with self.assertRaisesRegex(DataError, 'must be 16'):
            legacy_iaa_ids({'글': [{'persona_id': 'X', 'post': 'b03'}]}, {'X_b03'})

    def test_partial_boundary_is_not_exact(self):
        gold = {'p': {'texts': {'body': '집 근처'}, 'spans': [{'start': 0, 'end': 4, 'type': 'REL_HOME', 'text_id': 'body', 'level': 'explicit'}]}}
        pred = {'p': [{'start': 0, 'end': 3, 'type': 'REL_HOME', 'text_id': 'body'}]}
        metrics = score_subset(['p'], gold, pred)
        self.assertEqual(metrics['overall']['f1'], 1.0)
        self.assertEqual(metrics['exact']['overall']['f1'], 0.0)

    def test_exact_one_to_one_and_wrong_type(self):
        truth = {('p', 'body'): {(0, 4, 'REL_HOME')}}
        pred = {('p', 'body'): {(0, 4, 'REL_HOME'), (0, 4, 'AGE')}}
        metrics = exact_span_sets(truth, pred)['overall']
        self.assertEqual((metrics['tp'], metrics['fp'], metrics['fn']), (1, 1, 0))

    def test_level_formulas_and_iaa(self):
        def span(start, level):
            return {'start': start, 'end': start + 2, 'type': 'AGE',
                    'text_id': 'body', 'level': level}
        spans = [span(0, 'explicit'), span(3, 'implicit'), span(6, 'implicit'),
                 span(9, 'inferential')]
        gold = {'p': {'texts': {'body': 'x' * 20}, 'spans': spans}}
        # TP·FP·FN은 각각 2개이며, 예측의 level은 의도적으로 틀리게 넣는다.
        pred = {'p': [{**spans[0], 'level': 'inferential'}, spans[1],
                      span(12, 'explicit'), span(15, 'explicit')]}
        result = score_subset(['p'], gold, pred)
        self.assertEqual(result['overall']['f1'], 0.5)
        explicit, implicit, inferential = (result['by_level'][k]
                                          for k in ('explicit', 'implicit', 'inferential'))
        self.assertAlmostEqual(explicit['proxy_f1'], 2 / 3)
        self.assertEqual(explicit['conservative_f1'], 0.5)
        self.assertEqual(implicit['recall'], 0.5)
        self.assertEqual(implicit['proxy_f1'], 0.5)
        self.assertEqual(implicit['conservative_f1'], 0.4)
        self.assertEqual(inferential['proxy_f1'], 0)
        self.assertEqual(sum(c['proxy_allocated_fp'] for c in result['by_level'].values()), 2)
        self.assertAlmostEqual(result['implicit_iaa_comparison']['proxy_ratio'], 0.5 / 0.444)

    def test_partial_tie_uses_existing_global_matching(self):
        gold = {'p': {'texts': {'body': 'abcdef'}, 'spans': [
            {'start': 0, 'end': 4, 'type': 'AGE', 'text_id': 'body', 'level': 'explicit'},
            {'start': 2, 'end': 6, 'type': 'AGE', 'text_id': 'body', 'level': 'implicit'}]}}
        pred = {'p': [{'start': 0, 'end': 6, 'type': 'AGE', 'text_id': 'body'}]}
        result = score_subset(['p'], gold, pred)
        self.assertEqual(result['by_level']['implicit']['tp'], 1)
        self.assertEqual(result['by_level']['explicit']['fn'], 1)
        self.assertIsNone(result['by_level']['inferential']['proxy_f1'])
        self.assertEqual(result['exact']['overall']['tp'], 0)

    def test_zero_tp_and_no_predictions(self):
        posts, gold, _ = prepare(self.root, self.bio)
        for pred in ({p: [] for p in posts},
                     {p: [{**self.span, 'type': 'AGE'}] for p in posts}):
            result = score_subset(posts, gold, pred)
            self.assertEqual(result['by_level']['inferential']['proxy_f1'], 0)
            self.assertEqual(result['by_level']['inferential']['conservative_f1'], 0)
            self.assertIsNone(result['by_level']['inferential']['proxy_allocated_fp'])

    def test_invalid_or_duplicate_gold_level_fails(self):
        posts, gold, _ = prepare(self.root, self.bio)
        pred = {p: [] for p in posts}
        gold['X_b01']['spans'][0]['level'] = 'unknown'
        with self.assertRaisesRegex(DataError, 'gold level'):
            score_subset(posts, gold, pred)
        gold['X_b01']['spans'][0]['level'] = 'explicit'
        gold['X_b01']['spans'].append(dict(gold['X_b01']['spans'][0]))
        with self.assertRaisesRegex(DataError, 'Duplicate gold'):
            score_subset(posts, gold, pred)

    def test_saved_rescore_preserves_source_and_reports_fp(self):
        posts, gold, audit = prepare(self.root, self.bio)
        predictions = {'X_b01': [self.span], 'X_b02': [{**self.span, 'type': 'AGE'}]}
        overall = score_subset(posts, gold, predictions)['overall']
        report = {'audit': audit, 'metrics': {'overall': overall}, 'checkpoint': 'original'}
        self.write('saved/predictions.jsonl', [
            {'post_id': p, 'texts': gold[p]['texts'], 'candidates': predictions[p]} for p in posts])
        path = self.root / 'saved/metrics.json'
        original = json.dumps(report)
        path.write_text(original, encoding='utf-8')
        result = rescore_saved(path.parent, posts, gold, audit)
        self.assertEqual(result['metrics']['overall'], overall)
        self.assertEqual(result['checkpoint'], 'original')
        self.assertFalse(result['model_inference_repeated'])
        self.assertEqual(result['fp_breakdown']['by_kind'], {'clue': 0, 'noise': 1})
        self.assertEqual(result['fp_breakdown']['by_type']['AGE'], 1)
        self.assertEqual(path.read_text(encoding='utf-8'), original)
        with self.assertRaisesRegex(DataError, 'hashes differ'):
            rescore_saved(path.parent, posts, gold, {'input_sha256': {}})
        report['metrics']['overall']['tp'] = 99
        path.write_text(json.dumps(report), encoding='utf-8')
        with self.assertRaisesRegex(DataError, 'Original partial metric changed'):
            rescore_saved(path.parent, posts, gold, audit)


if __name__ == '__main__':
    unittest.main()
