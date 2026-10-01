"""W7 명시 단서 규칙의 경계·약칭·오탐 가드를 검증한다."""
import unittest

from rules import ExplicitRules, age_spans


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


if __name__ == '__main__':
    unittest.main()
