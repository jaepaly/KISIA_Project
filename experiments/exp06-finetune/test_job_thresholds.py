"""JOB 문턱 비교는 다른 유형·겹침 해소 결과를 바꾸지 않는다."""
import unittest

from compare_job_thresholds import filter_job
import train


class JobThresholdTest(unittest.TestCase):
    def setUp(self):
        self.key = ('p', 'body')
        self.job = (0, 2, 'JOB')
        self.age = (3, 5, 'AGE')
        self.pred = {self.key: {self.job, self.age}}
        self.scores = {(self.key, self.job): .8, (self.key, self.age): .7}

    def test_equal_threshold_preserves_baseline(self):
        self.assertEqual(filter_job(self.pred, self.scores, .7, .7), self.pred)

    def test_other_type_unchanged_and_input_not_mutated(self):
        self.assertEqual(filter_job(self.pred, self.scores, .85, .7), {self.key: {self.age}})
        self.assertEqual(self.pred[self.key], {self.age, self.job})

    def test_threshold_boundary_inclusive(self):
        self.assertIn(self.job, filter_job(self.pred, self.scores, .8, .7)[self.key])

    def test_lower_threshold_rejected(self):
        with self.assertRaises(train.TrainError):
            filter_job(self.pred, self.scores, .6, .7)


if __name__ == '__main__':
    unittest.main()
