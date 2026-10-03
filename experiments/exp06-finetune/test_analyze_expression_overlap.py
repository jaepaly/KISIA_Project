"""저장 예측의 동일 표기 분리와 공식 partial 매칭 정합성을 작은 표본으로 검증한다."""
import unittest

from analyze_expression_overlap import fixed_cohort_recall, matched_gold_ids, split_recall, surface


class ExpressionOverlapTests(unittest.TestCase):
    def test_exact_surface_nfc_without_lexical_truncation(self):
        self.assertEqual(surface(' 서울에서 '), '서울에서')
        self.assertEqual(surface('시누이'), '시누이')
        self.assertEqual(surface('늙은이'), '늙은이')
        self.assertEqual(surface('학원가'), '학원가')
        self.assertEqual(surface('큰아이'), '큰아이')
        self.assertEqual(surface('큰아이가'), '큰아이가')
        self.assertNotEqual(surface('큰아이'), surface('큰아이가'))
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
                              {('LOC_ADMIN', '서울에서')},
                              {('A01', 'LOC_ADMIN', '서울에서')})
        self.assertEqual(result['all_personas']['explicit']['seen'],
                         {'gold': 2, 'tp': 1, 'fn': 1, 'recall': 0.5})
        self.assertEqual(result['all_personas']['overall']['unseen']['gold'], 1)
        self.assertEqual(result['same_persona']['overall']['seen']['tp'], 1)

    def test_fixed_cohort_is_shared_between_models(self):
        gold = {'A01_b01': {'spans': [
            {'text_id': 'body', 'start': 0, 'end': 3, 'text': '큰아이',
             'type': 'FAM', 'level': 'explicit'},
            {'text_id': 'body', 'start': 4, 'end': 8, 'text': '큰아이가',
             'type': 'FAM', 'level': 'explicit'},
        ]}}
        first = ('A01_b01', 'body', 0, 3, 'FAM')
        second = ('A01_b01', 'body', 4, 8, 'FAM')
        result = fixed_cohort_recall(
            gold, {('FAM', '큰아이가')},
            {'reviewed': {first}, 'teacher': {second}})
        self.assertEqual(result['gold'], 1)
        self.assertEqual(result['profiles']['reviewed']['recall'], 1.0)
        self.assertEqual(result['profiles']['teacher']['recall'], 0.0)


if __name__ == '__main__':
    unittest.main()
