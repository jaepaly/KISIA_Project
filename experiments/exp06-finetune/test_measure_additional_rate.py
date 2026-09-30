"""추가 탐지율의 기존 도구 유리 매칭과 v1의 1:1 매칭을 검증한다."""

import unittest

from measure_additional_rate import baseline_missed_gold, model_matched_gold


class AdditionalRateTests(unittest.TestCase):
    def setUp(self):
        self.gold = {
            'X_b01': {
                'texts': {'body': 'abcdefghij'},
                'spans': [
                    {'span_id': 'X_b01_s01', 'text_id': 'body', 'start': 0, 'end': 4,
                     'type': 'AGE', 'level': 'explicit'},
                    {'span_id': 'X_b01_s02', 'text_id': 'body', 'start': 6, 'end': 10,
                     'type': 'JOB', 'level': 'implicit'},
                ],
            },
        }

    def test_baseline_ignores_type_but_requires_iou(self):
        tools = {('X_b01', 'body'): [
            {'start': 0, 'end': 4, 'type': 'PERSON'},
            {'start': 6, 'end': 7, 'type': 'PERSON'},
        ]}
        self.assertEqual(baseline_missed_gold(self.gold, tools), {'X_b01_s02'})

    def test_model_requires_type_and_matches_gold_once(self):
        predictions = {'X_b01': [
            {'text_id': 'body', 'start': 0, 'end': 4, 'type': 'FAM'},
            {'text_id': 'body', 'start': 6, 'end': 10, 'type': 'JOB'},
        ]}
        self.assertEqual(model_matched_gold(self.gold, predictions), {'X_b01_s02'})

    def test_model_tie_break_matches_official_scorer(self):
        gold = {'X_b01': {'texts': {'body': 'abcdefghij'}, 'spans': [
            {'span_id': 'X_b01_s01', 'text_id': 'body', 'start': 0, 'end': 3, 'type': 'AGE'},
            {'span_id': 'X_b01_s02', 'text_id': 'body', 'start': 1, 'end': 4, 'type': 'AGE'},
        ]}}
        predictions = {'X_b01': [{'text_id': 'body', 'start': 0, 'end': 4, 'type': 'AGE'}]}
        self.assertEqual(model_matched_gold(gold, predictions), {'X_b01_s02'})


if __name__ == '__main__':
    unittest.main()
