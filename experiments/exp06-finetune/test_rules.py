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

    def test_numeric_age_with_direct_ending(self):
        """「45세다」 「아들이 5세다」 — 살·세 뒤에 「이」 없이 붙는 어미 (#323 추가 · 인스턴스 핫패치와 같은 내용)."""
        for text, want in (('나는 45세다', '45세다'), ('45세야', '45세야'), ('아들이 5세다', '5세다'),
                           ('올해 45세라고 했다', '45세라고'), ('45세라서 그런지', '45세라서'), ('딸이 7살이네', '7살이네'),
                           ('제가 45세요', '45세요'), ('45세란다', '45세란다')):
            found = {text[start:end] for start, end, kind in age_spans(text) if kind == 'AGE'}
            self.assertEqual(found, {want}, text)

    def test_century_and_generation_are_not_age(self):
        """「세기 · 세대」와 세 자리 수는 나이가 아니다 — 어미를 넓혀도 그대로 빈 결과."""
        for text in ('12세기 건축', '45세대 아파트', '2세대 아이돌', '245세', '100세 시대'):
            self.assertEqual(age_spans(text), set(), text)

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

    def test_generic_place_words_are_dropped_in_merge(self):
        """실제 글 시험(10/16) — 1단이 「노을맛집」 「디자인 여행」 「지면병원행」을 시설로 내면 병합에서 뺀다.
        골드(test 제외 2,281편)의 시설 스팬 359개에 이 꼴은 0개. 「국민은행 · 비행장 · 성수동 맛집」은 그대로 둔다."""
        from rules import is_generic_place_word
        cases = {'노을맛집': True, '디자인 여행': True, '지면병원행': True, '이기면감옥행': True,
                 '노을맛집에서': True, '노을맛집이네': True, '노을맛집이에요': True, '디자인 여행에서': True,  # Codex — 조사가 붙어도
                 '국민은행': False, '은행': False, '비행장': False, '성수동 맛집': False, '모던하우스도': False,
                 '맛집': False, '여행': False, '진행': False}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(is_generic_place_word(text), expected)
        body = '노을맛집 이네. 국민은행 들렀다'
        model = [{'text_id': 'body', 'start': 0, 'end': 4, 'text': '노을맛집', 'type': 'LOC_FACILITY', 'score': 0.9},
                 {'text_id': 'body', 'start': 9, 'end': 13, 'text': '국민은행', 'type': 'LOC_FACILITY', 'score': 0.9}]
        out, stats = merge_with_model('p1', {'body': body}, model, ExplicitRules(FakeRegions()))
        self.assertEqual([s['text'] for s in out if s['type'] == 'LOC_FACILITY'], ['국민은행'])
        self.assertEqual(stats['model_generic_place_dropped'], 1)

    def test_fragment_model_spans_are_dropped_in_merge(self):
        """exp41 C1 — 모델이 낸 조사 · 어미 조각(「에」 「에서」 「하는」)과 글자 없는 스팬은 병합에서 뺀다.
        한 글자라도 골드에 있는 말(샵 · 형 · 집 · 면 · 차)은 그대로 둔다 — 「면」은 「면 우체국」(읍면) 때문에 목록에서 뺐다."""
        from rules import is_fragment_span
        for text in ('에', '에서', '로', '의', '서', '고', '하는', '한테', '에서도', ' 에 ', '…', '🥲', '!!', 'ㅋㅋ'):
            with self.subTest(text=text):
                self.assertTrue(is_fragment_span(text))
        for text in ('샵', '형', '집', '면', '차', '면 우체국', '서울', '평택 쪽', '수지 쪽은', '에버랜드', '3', 'KTX',
                     '서구', '고성', '의정부', '하남'):
            with self.subTest(text=text):
                self.assertFalse(is_fragment_span(text))
        body = '면 우체국에 들렀다가 샵에서 형이랑'
        model = [{'text_id': 'body', 'start': 0, 'end': 1, 'text': '면', 'type': 'LOC_ADMIN', 'score': 0.9},
                 {'text_id': 'body', 'start': 5, 'end': 6, 'text': '에', 'type': 'LOC_FACILITY', 'score': 0.9},
                 {'text_id': 'body', 'start': 12, 'end': 13, 'text': '샵', 'type': 'LOC_FACILITY', 'score': 0.9},
                 {'text_id': 'body', 'start': 13, 'end': 15, 'text': '에서', 'type': 'COMMUTE', 'score': 0.9},
                 {'text_id': 'body', 'start': 16, 'end': 17, 'text': '형', 'type': 'FAM', 'score': 0.9}]
        out, stats = merge_with_model('p1', {'body': body}, model, ExplicitRules(FakeRegions()))
        self.assertEqual([s['text'] for s in out], ['면', '샵', '형'])
        self.assertEqual(stats['model_fragment_dropped'], 2)

    def test_admin_inside_tail_is_trimmed_in_merge(self):
        """exp41 C2 — LOC_ADMIN 「서울 안에서도」 → 「서울」(오프셋도 같이). 「평택 쪽」 「수지 쪽은」 · 다른 유형은 그대로."""
        from rules import trim_admin_inside
        cases = {'서울 안에서도': '서울', '마포구 안에서': '마포구', '강남 안에선': '강남', '성남시 안쪽으로': '성남시',
                 '서울 안에서는': '서울', '동네 안쪽': '동네',
                 '평택 쪽': None, '수지 쪽은': None, '안에서': None, '서울 안에': None, '서울안에서': None,
                 '경기 남부 안에서': None}   # 두 낱말 앞말은 범위 밖
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(trim_admin_inside(text), expected)
        body = '그래도 서울 안에서도 평택 쪽은'
        model = [{'text_id': 'body', 'start': 4, 'end': 11, 'text': '서울 안에서도', 'type': 'LOC_ADMIN', 'score': 0.93},
                 {'text_id': 'body', 'start': 12, 'end': 17, 'text': '평택 쪽은', 'type': 'LOC_ADMIN', 'score': 0.9}]
        out, stats = merge_with_model('p1', {'body': body}, model, ExplicitRules(FakeRegions()))
        self.assertEqual([(s['start'], s['end'], s['text'], s['score']) for s in out],
                         [(4, 6, '서울', 0.93), (12, 17, '평택 쪽은', 0.9)])
        self.assertTrue(all(body[s['start']:s['end']] == s['text'] for s in out))
        self.assertEqual(stats['model_admin_inside_trimmed'], 1)
        out, _ = merge_with_model('p1', {'body': '서울 안에서'}, [{'text_id': 'body', 'start': 0, 'end': 6, 'text': '서울 안에서',
                                                                'type': 'REL_HOME', 'score': 0.9}], ExplicitRules(FakeRegions()))
        self.assertEqual(out[0]['text'], '서울 안에서')   # LOC_ADMIN 만

    def test_rule_admin_without_model_candidate_is_kept(self):
        """규칙만 낸 지명은 모델 후보가 없어도 그대로 남는다 — 모델이 놓친 진짜 지명을 규칙이 보완하는 길.
        exp41 C3(모델이 안 본 자리의 규칙 지명 버림)은 B 리뷰(#397)로 채택하지 않았다."""
        class FixedRules:
            def predict_channel(self, text):
                return {(0, 2, 'LOC_ADMIN'), (13, 15, 'LOC_ADMIN'), (19, 22, 'AGE')}

        body = '하남 갔다가 수지 쪽은 광주 들러 스물셋'
        model = [{'text_id': 'body', 'start': 7, 'end': 12, 'text': '수지 쪽은', 'type': 'LOC_ADMIN', 'score': 0.9}]
        out, stats = merge_with_model('p1', {'body': body}, model, FixedRules())
        self.assertEqual([s['text'] for s in out], ['하남', '수지 쪽은', '광주', '스물셋'])
        self.assertNotIn('rule_admin_unbacked_dropped', stats)

    def test_ordinal_cha_commute_is_dropped_in_merge(self):
        """실제 글 시험(#385 3-1) — 1단이 「야간 3일차 퇴근길」의 「차」를 COMMUTE 로 내면 병합에서 뺀다.
        「일 · 주 · 회 · 년」 바로 뒤 한 글자 「차」이고 그 앞이 수일 때만. 탈것 「차」는 그대로 둔다."""
        from rules import is_ordinal_cha
        cases = {
            # 버린다 — 차례의 「차」
            '야간 3일차 퇴근길': True, '입사 5년차 직장인': True, '운동 2주차인데': True, '2회차 관람': True,
            '12주차 검진': True, '삼일차 아침': True, '이십일차에': True, '몇년차인지': True,
            # 둔다 — 탈것 · 범위 밖
            '차를 타고 갔다': False, '차로 출근한다': False, '자차로 다닌다': False,
            '2차 회식': False,            # 단위가 없다 — 범위 밖
            '3년 차 직장인': False,        # 띄어 썼다 — 범위 밖
            '세계일주 차 안에서': False,    # 띄어 씀 · 앞이 수가 아니다
            '회사일차 빼고': False,        # 「사」 앞이 한글 — 수로 읽지 않는다
            '매일차 막혀': False, '휴일차 많네': False, '주말 주차 공간': False,
            '오늘 재택이라 차 못 태워 준다고': False,
            '출장 3일\n차 타고 출근한다': False,   # 줄이 바뀌면 바로 앞 글자가 「일」이 아니다
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                i = text.index('차')
                self.assertEqual(is_ordinal_cha(text, i, i + 1), expected)
        self.assertFalse(is_ordinal_cha('3일차에', 2, 4))   # 스팬이 「차」 한 글자일 때만 — 「차에」는 안 건드린다
        body = '야간 3일차 퇴근길. 차 막혀서 늦음'
        model = [{'text_id': 'body', 'start': 5, 'end': 6, 'text': '차', 'type': 'COMMUTE', 'score': 0.9},
                 {'text_id': 'body', 'start': 12, 'end': 13, 'text': '차', 'type': 'COMMUTE', 'score': 0.9}]
        out, stats = merge_with_model('p1', {'body': body}, model, ExplicitRules(FakeRegions()))
        self.assertEqual([(s['start'], s['text']) for s in out if s['type'] == 'COMMUTE'], [(12, '차')])
        self.assertEqual(stats['model_ordinal_cha_dropped'], 1)

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
            '총개수는 스물세이다': set(),
            '점수는 스물세이다': set(),
            '스물세에 한 번 당첨된다': set(),
            '제 나이는 총 스물세 살입니다': {'스물세 살입니다'},
            '23세에 한 번 갔다': {'23세에'},
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
            '경북 구미는 맞벌이 가구가 많다': {'경북', '구미는'},
            '전남 진도는 빠르게 인구가 줄고 있다': {'전남', '진도는'},
            '음식이 구미에 맞는다': set(),
            '오늘 업무 진도는 여기까지': set(),
            '공부 진도가 밀렸다': set(),
            '진도가 느려서 걱정이다': set(),
            '목표 달성을 했다': set(),
            '이 진도로 가면 끝난다': set(),
            '진도 항상 느리다': set(),
            '진도에 놀러 갔다': {'진도에'},
            '진도군에 산다': {'진도군에'},
            '진도 여행을 다녀왔다': {'진도'},
            '대구 달성에 산다': {'대구', '달성에'},
            '대구 달성군에 산다': {'대구', '달성군에'},
            '목표 달성에 가까워졌다': set(),
            '업무 진도로 가득한 하루': set(),
            '진도에 오래 머물렀다': set(),
            '진도에 가서 쉬었다': {'진도에'},
            '진도로 이사 왔다': {'진도로'},
            '진도에 와서 좋았다': {'진도에'},
            '충남 공주로 이사했다': {'충남', '공주로'},
            '경남에서 일한다': {'경남에서'},
            '충북 청주 출신': {'충북', '청주'},
            '봉천동 우리 집에 왔다': {'봉천동'},
            '망원동으로 이사 왔다': {'망원동으로'},
            '두 기능이 연동되는 구조': set(),
            '아침마다 운동을 한다': set(),
            '책상 모서리에 부딪혔다': set(),
            '목소리가 잠깐 멈췄다': set(),
            '수정 요청은 내일까지': set(),
            '도면 계획을 바꿨다': set(),
            '음식은 한 번 상하면 끝': set(),
            '경기도에 있는 화성 토양을 조사했다': {'경기도에', '화성'},
        }
        for text, expected in cases.items():
            found = {text[s:e] for s, e, k in rules.location_spans(text) if k == 'LOC_ADMIN'}
            self.assertEqual(found, expected, text)

    def test_location_common_word_homonyms_exp42(self):
        """exp42 R1 — 일반어로 더 자주 쓰는 군 · 시 · 면 이름은 지명 문맥이 있을 때만 지명 (합성 문장)."""
        rules = ExplicitRules()
        cases = {
            'AI 음성으로 읽어 준다': set(),
            '녹음된 음성을 글자로 바꿨다': set(),
            '음성 메시지를 보냈다': set(),
            'AI 음성으로 들어 보니 자연스럽다': set(),
            '음성으로 내려받기 버튼': set(),
            '동화 속 공주가 왕자를 만났다': set(),
            '여행 예산을 미리 짰다': set(),
            '예산이 부족하다': set(),
            '장수 비결은 산책이다': set(),
            '한번 해보면 안다': set(),
            '냄새가 강하면 뺀다': set(),
            '음성군에 산다': {'음성군에'},
            '충북 음성에 산다': {'충북', '음성에'},
            '음성에 산다': {'음성에'},
            '퇴근하고 음성 쪽 시장에 들렀다': {'음성'},
            '공주에 놀러 갔다': {'공주에'},
            '요즘 공주에 놀러 간다': {'공주에'},
            '공주로 향했다': {'공주로'},
            '공주시 터미널': {'공주시'},
            '충남 예산으로 이사했다': {'충남', '예산으로'},
            '예산군 방역 날짜': {'예산군'},
            '예산 농사소식지를 받았다': {'예산'},
            '전북 장수에 간다': {'전북', '장수에'},
            '함평군 해보면에 산다': {'함평군', '해보면에'},
            # 일반화한 목록 (README §1)
            '상당 시간이 걸렸다': set(),
            '규제 강화가 필요하다': set(),
            '영양 성분표를 봤다': set(),
            '종이 이천 장을 샀다': set(),
            '물고기 두 마리면 충분하다': set(),
            '고집 부리면 곤란하다': set(),
            '보안면에서 약하다': set(),
            '고령 인구가 늘었다': set(),
            '영광의 순간': set(),
            '직원 일동': set(),
            '청주 상당구에 산다': {'청주', '상당구에'},
            '강화도 말고 강화에 놀러 갔다': {'강화도', '강화에'},
            '경북 영양에 산다': {'경북', '영양에'},
            '이천으로 이사했다': {'이천으로'},
            '충북 보은 장날': {'충북', '보은'},
            # Codex 검토 반례 (10/26) — 섬 이름 · 복합 조사 · 특산 · 축제
            '강화도 여행을 갔다': {'강화도'},
            '이천 도자기 축제에 갔다': {'이천'},
            '이천에는 산다': {'이천에는'},
            '이천 쌀이 맛있다': {'이천'},
            '공주 알밤을 샀다': {'공주'},
            '이천 역에서 내렸다': {'이천'},
            '음성 역할을 한다': set(),
        }
        for text, expected in cases.items():
            found = {text[s:e] for s, e, k in rules.location_spans(text) if k == 'LOC_ADMIN'}
            self.assertEqual(found, expected, text)

    def test_model_homonym_place_and_counterfactual_job_are_dropped_in_merge(self):
        """exp42 R1 · R3 — 모델 후보에도 같은 동형이의어 판단 · 반사실 가정 직업은 버린다."""
        from rules import is_counterfactual, is_model_homonym_place

        self.assertTrue(is_model_homonym_place('AI 음성으로 읽어 준다', 3, 7))
        self.assertFalse(is_model_homonym_place('음성으로 이사 왔다', 0, 4))
        self.assertFalse(is_model_homonym_place('음성 쪽 시장', 0, 4))      # 「음성 쪽」은 다른 말이 붙은 스팬
        self.assertFalse(is_model_homonym_place('서울에 산다', 0, 3))       # 목록 밖 이름은 건드리지 않는다
        s = '만약 내가 가수였거나 무대에서 일했다면 달랐겠지.'
        self.assertTrue(is_counterfactual(s, s.index('가수'), s.index('가수') + 2))
        s2 = '만약 내가 교사가 아니었다면 몰랐을 거다.'
        self.assertFalse(is_counterfactual(s2, s2.index('교사가'), s2.index('교사가') + 3))   # 부정 — 실제 직업
        s3 = '나는 교사였다. 만약 비가 왔다면 쉬었겠지.'
        self.assertFalse(is_counterfactual(s3, 3, 5))   # 「만약」이 다른 문장
        # Codex 검토 반례 — 가정 어미가 그 직업 말을 서술할 때만
        for text, span, expected in [
                ('만약 교사인 내가 복권에 당첨됐다면 일을 그만뒀을 것이다.', '교사', False),
                ('만약 내가 의사가 됐다면 바빴겠지.', '의사가', True),
                ('만약 내가 가수였다면 무대에 섰겠지.', '가수', True),
                ('만약 내가 간호사로 일하지 않았다면 몰랐다.', '간호사로', False)]:
            i = text.index(span)
            self.assertEqual(is_counterfactual(text, i, i + len(span)), expected, text)
        self.assertFalse(is_model_homonym_place('강화도에 놀러 갔다', 0, 3))   # 섬 이름 — 「도」는 조사가 아니다
        self.assertFalse(is_model_homonym_place('이천에는 산다', 0, 4))

        class NoRules:
            def predict_channel(self, text):
                return set()

        text = 'AI 음성으로 읽어 준다. 만약 내가 가수였다면 좋았겠다. 나는 교사다.'
        model = [{'text_id': 'body', 'start': 3, 'end': 7, 'text': '음성으로', 'type': 'LOC_ADMIN', 'score': 0.9},
                 {'text_id': 'body', 'start': text.index('가수'), 'end': text.index('가수') + 2, 'text': '가수',
                  'type': 'JOB', 'score': 0.9},
                 {'text_id': 'body', 'start': text.index('교사'), 'end': text.index('교사') + 2, 'text': '교사',
                  'type': 'JOB', 'score': 0.9}]
        merged, stats = merge_with_model('p_b01', {'body': text}, model, NoRules())
        self.assertEqual([s['text'] for s in merged], ['교사'])
        self.assertEqual((stats['model_homonym_place_dropped'], stats['model_counterfactual_job_dropped']), (1, 1))

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
