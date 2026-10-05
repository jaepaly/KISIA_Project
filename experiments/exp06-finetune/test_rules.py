"""W7 명시 단서 규칙의 경계·약칭·오탐 가드를 검증한다."""
import unittest

import infer
from rules import ExplicitRules, age_spans, merge_with_model


class FakeRegions:
    def __init__(self):
        self.regions = {
            '1': {'name': '서울특별시', 'aliases': ['서울특별시'], 'level': 'sido'},
            '2': {'name': '부천시', 'aliases': ['부천시'], 'level': 'sigungu'},
            '3': {'name': '해운대구', 'aliases': ['해운대구'], 'level': 'sigungu'},
            '4': {'name': '판교동', 'aliases': ['판교동'], 'level': 'emd'},
            '5': {'name': '화성시', 'aliases': ['화성시'], 'level': 'sigungu'},
            '6': {'name': '고성군', 'aliases': ['고성군'], 'level': 'sigungu'},
            '7': {'name': '고성군', 'aliases': ['고성군'], 'level': 'sigungu'},
        }

    def resolve(self, name):
        return [code for code, region in self.regions.items() if name in region['aliases']]


class RuleTests(unittest.TestCase):
    def test_age_forms_and_quantity_guard(self):
        text = '스물셋임, 23살이고, 세 살, 88년생. 서른 번, 마흔 명, 서른분'
        found = {text[start:end] for start, end, kind in age_spans(text) if kind == 'AGE'}
        self.assertEqual(found, {'스물셋임', '23살이고', '세 살', '88년생'})

    def test_duration_and_count_units_are_not_age(self):
        """「서른 해보다」(근속 30년) · 「쉰 날」(쉬다) — 기간·횟수 단위 앞의 수는 나이가 아니다 (인스턴스 테스트 10/5)."""
        text = ('시청에서 보낸 서른 해보다, 씨감자 묻고 쉰 날, 스무 해 동안, 마흔 군데. 책이 스물세 권이나. '
                '서른하나 되던 해, 쉰셋이에요, 스물다섯인데 벌써, 스물하나인데 벌써 해가')
        found = {text[start:end] for start, end, kind in age_spans(text) if kind == 'AGE'}
        self.assertEqual(found, {'서른하나', '쉰셋이에요', '스물다섯인데', '스물하나인데'})

    def test_numeric_age_after_nai(self):
        """「나이 48에」 — 살·세 없는 숫자 나이 (인스턴스 비교 측정 10/5 · 네 구성 모두 못 잡던 표현)."""
        text = '나이 48에 처음 배운다. 나이는 35인데. 나이 3개월 차 아님, 2024년 나이'
        found = {text[start:end] for start, end, kind in age_spans(text) if kind == 'AGE'}
        self.assertEqual(found, {'48에', '35인데'})

    def test_income_amount_needs_income_context(self):
        from rules import income_spans
        text = ('이번 달 월급 삼백이십만 원 들어왔다. 커피는 4,500원. 연금 140만 원 받는다. 집값이 3억이라니. '
                '월급 300.5만 원 받았어. 택배로 5만 원짜리 받았다. 월세 60만 원 들어갔다. '
                '알바비로 80만 원 받았다. 원고료 70만 원 들어왔다. 연봉 1,300.5만 원')
        found = {text[start:end] for start, end, kind in income_spans(text)}
        self.assertEqual(found, {'삼백이십만 원', '140만 원', '300.5만 원', '80만 원', '70만 원', '1,300.5만 원'})

    def test_age_line_idiom_kept(self):
        """「서른 줄에 접어들다」는 나이 — 단위 「줄」로 빼지 않는다 (Codex 검토 10/5)."""
        text = '어느새 서른 줄에 접어들었네. 이제 마흔 줄에 들어섰어'
        found = {text[start:end] for start, end, kind in age_spans(text) if kind == 'AGE'}
        self.assertEqual(found, {'서른', '마흔'})

    def test_location_particle_and_long_suffix_alias(self):
        rules = ExplicitRules(FakeRegions())
        text = '서울에서 부천으로 해운대구는 판교동에 갔다'
        found = {text[start:end] for start, end, kind in rules.location_spans(text) if kind == 'LOC_ADMIN'}
        self.assertEqual(found, {'서울에서', '부천으로', '해운대구는', '판교동에'})
        self.assertIn('고성', rules.aliases)  # 동명 지명이 여럿이어도 유형 탐지는 허용
        self.assertNotIn('판교', rules.aliases)  # 읍·면·동에는 약칭을 만들지 않음

    def test_excluded_alias_preserves_full_name(self):
        rules = ExplicitRules(FakeRegions(), excluded_aliases={'화성'})
        self.assertEqual(rules.location_spans('화성 여행, 화성시 방문'),
                         {(7, 10, 'LOC_ADMIN')})

    def test_longest_first_merge_keeps_original_untouched(self):
        class FixedRules:
            def predict_channel(self, text):
                return {(0, 4, 'LOC_ADMIN')}

        original = [{'text_id': 'body', 'start': 0, 'end': 2, 'text': '서울',
                     'type': 'LOC_ADMIN', 'score': 0.91, 'span_id': 'old_s01'}]
        merged, stats = merge_with_model('p_b01', {'body': '서울에서'}, original, FixedRules())
        self.assertEqual(merged, [{'start': 0, 'end': 4, 'text': '서울에서',
                                   'type': 'LOC_ADMIN', 'text_id': 'body', 'span_id': 'p_b01_s01'}])
        self.assertEqual((stats['selected_rule_only'], stats['suppressed_by_overlap']), (1, 1))
        self.assertEqual(original[0]['span_id'], 'old_s01')

    def test_same_span_preserves_model_score_without_source_field(self):
        class FixedRules:
            def predict_channel(self, text):
                return {(0, 3, 'AGE')}

        model = [{'text_id': 'body', 'start': 0, 'end': 3, 'text': '23살',
                  'type': 'AGE', 'score': 0.8}]
        merged, stats = merge_with_model('p_b01', {'body': '23살'}, model, FixedRules())
        self.assertEqual(merged[0]['score'], 0.8)
        self.assertEqual(set(merged[0]), {'start', 'end', 'text', 'type', 'score', 'text_id', 'span_id'})
        self.assertEqual(stats['selected_both'], 1)

    def test_channel_order_and_no_cross_channel_conflict(self):
        class FixedRules:
            def predict_channel(self, text):
                return {(0, 3, 'AGE')}

        texts = {'photo_caption:10': '23살', 'body': '23살', 'photo_caption:2': '23살'}
        merged, stats = merge_with_model('p_b01', texts, [], FixedRules())
        self.assertEqual([s['text_id'] for s in merged],
                         ['body', 'photo_caption:2', 'photo_caption:10'])
        self.assertEqual([s['span_id'] for s in merged],
                         ['p_b01_s01', 'p_b01_s02', 'p_b01_s03'])
        self.assertEqual(stats['selected_rule_only'], 3)

    def test_model_candidate_with_wrong_offset_fails(self):
        with self.assertRaisesRegex(ValueError, '문자 경계'):
            merge_with_model('p_b01', {'body': '서울'},
                             [{'text_id': 'body', 'start': 0, 'end': 2, 'text': '부천',
                               'type': 'LOC_ADMIN'}], ExplicitRules(FakeRegions()))

    def test_merged_candidate_passes_existing_contract(self):
        class FixedRules:
            def predict_channel(self, text):
                return {(0, 3, 'AGE')}

        texts = {'body': '23살'}
        merged, _ = merge_with_model('p_b01', texts, [], FixedRules())
        raw = {'record_type': 'post', 'post_id': 'p_b01', 'model_version': 'test',
               'texts': texts, 'candidates': merged}
        result = infer.format_contract(raw, lambda _texts, _span:
                                       {'level': 'explicit', 'subject': 'self'})
        self.assertEqual(result['spans'][0]['text'], '23살')


if __name__ == '__main__':
    unittest.main()
