"""저장 예측의 동일 표기 분리와 공식 partial 매칭 정합성을 작은 표본으로 검증한다."""
import unittest

from analyze_expression_overlap import matched_gold_ids, split_recall, surface


class ExpressionOverlapTests(unittest.TestCase):
    def test_one_trailing_particle_and_nfc(self):
        self.assertEqual(surface(' 서울에서 '), '서울')
        self.assertEqual(surface('서울'), '서울')
        self.assertEqual(surface('남편은'), '남편')
        self.assertEqual(surface('가'), '가')
        self.assertEqual(surface('23살'), '23살')

    def test_partial_one_to_one_and_seen_scopes(self):
        gold = {
            'A01_b01': {'persona_id': 'A01', 'texts': {'body': '서울에서 서울에서'},
                        'spans': [
                            {'text_id': 'body', 'start': 0, 'end': 4, 'text': '서울에서',
                             'type': 'LOC_ADMIN', 'level': 'explicit'},
                            {'text_id': 'body', 'start': 5, 'end': 9, 'text': '서울에서',
                             'type': 'LOC_ADMIN', 'level': 'explicit'},
                        ]},
            'B01_b01': {'persona_id': 'B01', 'texts': {'body': '남편은'},
                        'spans': [
                            {'text_id': 'body', 'start': 0, 'end': 3, 'text': '남편은',
                             'type': 'FAM', 'level': 'implicit'},
                        ]},
        }
        predictions = {
            'A01_b01': [{'text_id': 'body', 'start': 0, 'end': 4, 'type': 'LOC_ADMIN'}],
            'B01_b01': [{'text_id': 'body', 'start': 0, 'end': 3, 'type': 'JOB'}],
        }
        matched = matched_gold_ids(gold, predictions)
        self.assertEqual(matched, {('A01_b01', 'body', 0, 4, 'LOC_ADMIN')})
        result = split_recall(gold, matched,
                              {('LOC_ADMIN', '서울')},
                              {('A01', 'LOC_ADMIN', '서울')})
        self.assertEqual(result['all_personas']['explicit']['seen'],
                         {'gold': 2, 'tp': 1, 'fn': 1, 'recall': 0.5})
        self.assertEqual(result['all_personas']['overall']['unseen']['gold'], 1)
        self.assertEqual(result['same_persona']['overall']['seen']['tp'], 1)


if __name__ == '__main__':
    unittest.main()
