"""모델 없이 내부 eval 복원과 지문 불일치 거부를 검증한다."""
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import train
from internal_eval import restore_eval


class RestoreEvalTest(unittest.TestCase):
    def expected(self):
        ids = ['eval_1']
        return {'split': 'persona_holdout_reviewed_only:0.100', 'seed': 42,
                'run_config': {'data_sha256': 'data_hash', 'eval': {'examples': 1,
                    'example_ids_sha256': hashlib.sha256(json.dumps(ids).encode()).hexdigest()}}}

    def restore(self, expected):
        with patch.object(train, 'file_sha256', return_value='data_hash'), \
             patch.object(train, 'read_jsonl', return_value=[]), \
             patch.object(train, 'split_examples', return_value=([], [{'example_id': 'eval_1'}],
                          'persona_holdout_reviewed_only:0.100')) as split:
            result = restore_eval(Path('unused'), expected)
            self.assertTrue(split.call_args.kwargs['eval_reviewed_only'])
            return result

    def test_reviewed_only_restored(self):
        self.assertEqual(len(self.restore(self.expected())[0]), 1)

    def test_changed_data_rejected(self):
        expected = self.expected()
        expected['run_config']['data_sha256'] = 'changed'
        with self.assertRaises(train.TrainError):
            self.restore(expected)

    def test_changed_eval_ids_rejected(self):
        expected = self.expected()
        expected['run_config']['eval']['example_ids_sha256'] = 'changed'
        with self.assertRaises(train.TrainError):
            self.restore(expected)

    def test_legacy_split_supported(self):
        expected = {'split': 'persona_holdout:0.100', 'seed': 42}
        with patch.object(train, 'read_jsonl', return_value=[]), \
             patch.object(train, 'split_examples', return_value=([], [], expected['split'])) as split:
            restore_eval(Path('unused'), expected)
            self.assertFalse(split.call_args.kwargs['eval_reviewed_only'])


if __name__ == '__main__':
    unittest.main()
