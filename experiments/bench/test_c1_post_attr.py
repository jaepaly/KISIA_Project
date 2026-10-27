"""글×속성 보조 지표 — 반복 · 경계는 접히고, 다른 곳을 짚으면 FN · FP 둘 다인지 확인한다."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / 'src', Path(__file__).resolve().parent):
    sys.path.insert(0, str(path))

import c1_post_attr as post_attr


def span(start, end, type_='AGE', text_id='body'):
    return {'text_id': text_id, 'start': start, 'end': end, 'type': type_, 'level': 'explicit', 'subject': 'self'}


class PostAttrTests(unittest.TestCase):
    def test_repeats_and_boundary_fold_into_one_unit(self):
        gold = {'x': {'spans': [span(0, 4)]}}
        predictions = {'x': [span(0, 6), span(10, 14), span(20, 24)]}
        overall = post_attr.score(gold, predictions)['overall']
        self.assertEqual((overall['tp'], overall['fp'], overall['fn']), (1, 0, 0))

    def test_same_attribute_elsewhere_is_both_fp_and_fn(self):
        gold = {'x': {'spans': [span(0, 4)]}}
        predictions = {'x': [span(10, 14)]}
        overall = post_attr.score(gold, predictions)['overall']
        self.assertEqual((overall['tp'], overall['fp'], overall['fn']), (0, 1, 1))

    def test_overlap_needs_same_channel(self):
        gold = {'x': {'spans': [span(0, 4, text_id='title')]}}
        predictions = {'x': [span(0, 4)]}
        overall = post_attr.score(gold, predictions)['overall']
        self.assertEqual((overall['tp'], overall['fp'], overall['fn']), (0, 1, 1))

    def test_types_map_to_service_attributes(self):
        # LOC_ADMIN 과 LOC_FACILITY 는 같은 location — 유형이 갈려도 속성 단위로는 맞다
        gold = {'x': {'spans': [span(0, 4, 'LOC_ADMIN')]}}
        predictions = {'x': [span(0, 6, 'LOC_FACILITY')]}
        result = post_attr.score(gold, predictions)
        self.assertEqual(result['overall']['tp'], 1)
        self.assertEqual(result['by_attribute']['location']['tp'], 1)

    def test_touching_endpoints_do_not_overlap(self):
        gold = {'x': {'spans': [span(0, 4)]}}
        predictions = {'x': [span(4, 8)]}
        overall = post_attr.score(gold, predictions)['overall']
        self.assertEqual((overall['tp'], overall['fp'], overall['fn']), (0, 1, 1))

    def test_level_and_subject_are_ignored(self):
        gold = {'x': {'spans': [span(0, 4)]}}
        predictions = {'x': [{**span(0, 4), 'level': 'inferential', 'subject': 'other'}]}
        self.assertEqual(post_attr.score(gold, predictions)['overall']['tp'], 1)

    def test_counts_add_up_across_posts_and_attributes(self):
        gold = {'x': {'spans': [span(0, 4), span(10, 14, 'JOB')]}, 'y': {'spans': [span(0, 4, 'FAM')]}}
        predictions = {'x': [span(0, 4), span(20, 24, 'INCOME')], 'y': []}
        result = post_attr.score(gold, predictions)
        self.assertEqual({k: result['overall'][k] for k in ('tp', 'fp', 'fn')}, {'tp': 1, 'fp': 1, 'fn': 2})
        self.assertAlmostEqual(result['overall']['precision'], 0.5)
        self.assertAlmostEqual(result['overall']['recall'], 1 / 3)
        self.assertEqual(sum(v['tp'] + v['fp'] + v['fn'] for v in result['by_attribute'].values()), 4)

    def test_every_contract_type_has_an_attribute(self):
        types = {'AGE', 'SEX', 'LOC_ADMIN', 'LOC_FACILITY', 'REL_HOME', 'REL_WORK', 'JOB', 'FAM', 'COMMUTE', 'INCOME'}
        self.assertLessEqual(types, set(post_attr.TYPE_TO_ATTR))

    def test_empty_post_counts_nothing(self):
        result = post_attr.score({'x': {'spans': []}}, {'x': []})
        self.assertEqual(result['overall']['f1'], 0.0)
        self.assertEqual(result['overall']['tp'] + result['overall']['fp'] + result['overall']['fn'], 0)


if __name__ == '__main__':
    unittest.main()
