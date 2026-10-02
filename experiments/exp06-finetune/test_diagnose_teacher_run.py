"""저장된 후보의 임계값별 재채점이 기존 partial 채점과 일치하는지 확인한다."""
import unittest

import diagnose_teacher_run as diagnostic


class ThresholdRescoreTest(unittest.TestCase):
    def test_threshold_changes_only_saved_candidate_selection(self):
        key = ("P01_b01", "body")
        gold = {key: {(0, 2, "AGE")}}
        raw = {key: [
            {"start": 0, "end": 2, "type": "AGE", "score": 0.5},
            {"start": 4, "end": 6, "type": "JOB", "score": 0.8},
        ]}
        result = diagnostic.score_thresholds(gold, raw, [0.0, 0.3, 0.7])
        self.assertEqual(result["0.0"]["partial"]["tp"], 1)
        self.assertEqual(result["0.3"]["candidates"], 2)
        self.assertEqual(result["0.7"]["partial"]["tp"], 0)
        self.assertEqual(result["0.7"]["partial"]["fp"], 1)


if __name__ == "__main__":
    unittest.main()
