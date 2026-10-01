"""실제 test를 열지 않고 W7 규칙 결합 전용 채점 경로를 검증한다."""
import unittest

import evaluate_test
from evaluate_rules import headline, score_augmented
from prepare_bio import DataError


class FixedRules:
    def predict_channel(self, text):
        return {(0, 3, 'AGE')} if text.startswith('23살') else {(0, 3, 'LOC_ADMIN')}


class RuleEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.posts = {
            'p1': {'kind': 'clue', 'texts': {'body': '23살입니다'}},
            'p2': {'kind': 'noise', 'texts': {'body': '서울에서'}},
        }
        self.gold = {
            'p1': {'texts': {'body': '23살입니다'}, 'spans': [
                {'text_id': 'body', 'start': 0, 'end': 3, 'text': '23살',
                 'type': 'AGE', 'level': 'explicit'}]},
            'p2': {'texts': {'body': '서울에서'}, 'spans': []},
        }
        self.rows = {'p1': {'candidates': []}, 'p2': {'candidates': []}}

    def test_separate_score_and_noise_fp(self):
        before = evaluate_test.score_subset(self.posts, self.gold,
                                            {pid: [] for pid in self.posts})
        after = score_augmented(self.posts, self.gold, self.rows, FixedRules())
        summary = headline(after['metrics'], after['by_kind'])
        self.assertEqual((before['overall']['tp'], before['overall']['fp']), (0, 0))
        self.assertEqual((summary['overall_tp'], summary['overall_fp'], summary['overall_fn']), (1, 1, 0))
        self.assertEqual(summary['explicit_recall'], 1.0)
        self.assertAlmostEqual(summary['explicit_proxy_f1'], 2 / 3)
        self.assertEqual(summary['noise_fp'], 1)
        self.assertEqual(summary['by_type_tp_fp']['AGE'], {'tp': 1, 'fp': 0})
        self.assertEqual(after['source_stats']['selected_rule_only'], 2)
        self.assertEqual(self.rows['p1']['candidates'], [])

    def test_saved_prediction_ids_must_match(self):
        with self.assertRaisesRegex(DataError, 'ID'):
            score_augmented(self.posts, self.gold, {'p1': self.rows['p1']}, FixedRules())


if __name__ == '__main__':
    unittest.main()
