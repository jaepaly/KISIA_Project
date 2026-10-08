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
                '알바비로 80만 원 받았다. 원고료 70만 원 들어왔다. 연봉 1,300.5만 원. '
                '보수 정당에 90만 원 기부했다. 건물 보수에 91만 원 썼다. 상여 운구 비용으로 92만 원 냈다')
        found = {text[start:end] for start, end, kind in income_spans(text)}
        self.assertEqual(found, {'삼백이십만 원', '140만 원', '300.5만 원', '80만 원', '70만 원', '1,300.5만 원'})

    def test_closed_age_is_not_filtered_by_next_word(self):
        """#309 리뷰(B): 나이가 「살·어미」로 끝났으면 다음 낱말(일을 · 해가)은 단위가 아니다."""
        cases = {
            '나는 23살이고 일을 시작했어요': '23살이고',
            '나는 스물셋인데 일을 시작했어요': '스물셋인데',
            '나는 서른 살이고 해가 지면 산책해요': '서른 살이고',
            '나는 서른이고 해가 지면 걷는다': '서른이고',
            '마흔둘인데 날이 좋아서': '마흔둘인데',
        }
        for text, age in cases.items():
            found = {text[start:end] for start, end, kind in age_spans(text) if kind == 'AGE'}
            self.assertEqual(found, {age}, text)
        # 맨몸 수 + 단위는 여전히 뺀다
        for text in ('시청에서 보낸 서른 해보다', '씨감자 묻고 쉰 날', '책이 스물세 권이나'):
            self.assertEqual({t for t in age_spans(text)}, set(), text)

    def test_age_line_idiom_kept(self):
        """「서른 줄에 접어들다」는 나이 — 단위 「줄」로 빼지 않는다 (Codex 검토 10/5)."""
        text = '어느새 서른 줄에 접어들었네. 이제 마흔 줄에 들어섰어'
        found = {text[start:end] for start, end, kind in age_spans(text) if kind == 'AGE'}
        self.assertEqual(found, {'서른', '마흔'})

    def test_model_age_quantity_is_dropped_in_merge(self):
        """재학습 모델이 「서른 해 동안」 「스무 해」를 AGE 로 내면 병합에서 뺀다 (exp17 숫자 함정 7/15)."""
        from rules import is_quantity_age
        cases = {
            ('시청에서 보낸 서른 해 동안', '서른'): True,
            ('스무 해 넘게 살았다', '스무 해'): True,
            ('책이 스물세 권이나', '스물세 권이나'): True,
            ('나는 서른 살이고 해가 지면', '서른 살이고'): False,
            ('스물다섯인데 벌써', '스물다섯인데'): False,
            ('마흔둘인데 날이 좋다', '마흔둘인데'): False,
            ('올해 서른 줄에 접어들었다', '서른'): False,
            # Codex 10/6 — 줄바꿈 뒤 다른 말의 첫 글자를 단위로 읽지 않는다
            ('나이는 서른\n개발자로 일해요', '서른'): False,
            ('올해 서른\n원하는 일을 시작했어요', '서른'): False,
            ('스물 일곱에 결혼했다', '스물 일곱에'): False,
            ('스물 일곱', '스물 일곱'): False,
            # 스팬 끝에 조사·어미가 붙은 수량
            ('스무 해에 걸쳐', '스무 해에'): True,
            ('그게 벌써 스무 해였다', '스무 해였다'): True,
            ('쉰 날간 여행했다', '쉰 날간'): True,
            ('서른 번째 생일', '서른'): True,
            ('마흔 명이 왔다', '마흔'): True,
            ('서른 개월 동안', '서른'): True,
            ('아기는 생후 18개월이에요', '18개월'): False,
            ('그곳에서 스무\n해 동안 일했다', '스무'): True,
            ('마흔 명에게 선물을 줬다', '마흔'): True,
            ('스무 개였다', '스무'): True,
            ('스무 개쯤은 필요하다', '스무'): True,
            ('서른 일하면서 배웠다', '서른'): False,
            ('스물 해서 먹었다', '스물'): False,
            ('올해 서른 주도적으로 살아보려고 한다', '서른'): False,
            ('스무 개짜리 묶음을 샀다', '스무'): True,
            ('마흔 명당 한 명을 뽑는다', '마흔'): True,
            ('서른 분께 인사했다', '서른'): True,
        }
        for (text, span), expected in cases.items():
            start = text.index(span)
            self.assertEqual(is_quantity_age(text, start, start + len(span)), expected, (text, span))

    def test_age_endings_gap_322(self):
        """#322 ② — 「에 · 이다 · 이었다 · 인」으로 끝나는 한글 나이를 잡는다. 수량·단위 앞은 그대로 거른다."""
        cases = {
            '마흔여덟에 퇴직했다': {'마흔여덟에'},
            '스물 일곱에 결혼했다': {'스물 일곱에'},
            '그때 나는 마흔여덟이다': {'마흔여덟이다'},
            '그해 서른셋이었다': {'서른셋이었다'},
            '스물다섯인 동생': {'스물다섯인'},
            '서른 살에 이사했다': {'서른 살에'},
            '마흔에는 달라질 줄 알았다': {'마흔에는'},
            # 거르는 것은 그대로
            '시청에서 보낸 서른 해 동안': set(),
            '마흔 명에게 선물을 줬다': set(),
            '쉰 날이 지났다': set(),
            '다시 셌지만 스물셋에서 그만뒀다': set(),
            '하나부터 스물까지 세었다': set(),
            '총개수는 스물이다': set(),
            '스물에 한 번 당첨된다': set(),
            '점수는 마흔이다': set(),
            '제 나이는 총 마흔 살입니다': {'마흔 살입니다'},
            '나는 마흔 살이고 한 번도 못 가봤다': {'마흔 살이고'},
        }
        for text, expected in cases.items():
            found = {text[s:e] for s, e, _ in age_spans(text)}
            self.assertEqual(found, expected, text)

    def test_location_homonym_idiom_322(self):
        """#322 ② — 지명과 같은 꼴의 관용 표현은 거르고, 진짜 지명은 남긴다."""
        rules = ExplicitRules()
        cases = {
            '요즘 진도가 안 나간다': set(),
            '수학 진도 나가기가 힘들다': set(),
            '오늘따라 구미가 당기는 메뉴': set(),
            '화성 탐사 다큐를 봤다': set(),
            '진도에 놀러 갔다': {'진도에'},
            '구미에서 일한다': {'구미에서'},
            '화성에 산다': {'화성에'},
            '경기도 화성에서 온 친구다': {'경기도', '화성에서'},
            '경북 구미는 맞벌이 가구가 많다': {'구미는'},
            '전남 진도는 빠르게 인구가 줄고 있다': {'진도는'},
            '음식이 구미에 맞는다': set(),
            '경기도에 있는 화성 토양을 조사했다': {'경기도에', '화성'},
        }
        for text, expected in cases.items():
            found = {text[s:e] for s, e, k in rules.location_spans(text) if k == 'LOC_ADMIN'}
            self.assertEqual(found, expected, text)

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
