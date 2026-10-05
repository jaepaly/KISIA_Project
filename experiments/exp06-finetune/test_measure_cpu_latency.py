"""CPU 지연 측정의 표본 선택·분위수·워밍업 횟수를 검증한다."""
import unittest

from measure_cpu_latency import measure_one, nearest_rank, select_length_spaced


class CpuLatencyTests(unittest.TestCase):
    def test_length_spaced_posts_are_unique_and_stable(self):
        posts = {f'p{i:02d}': {'post_id': f'p{i:02d}', 'body': '가' * (i + 1)}
                 for i in range(10)}
        sample = select_length_spaced(posts, 4)
        self.assertEqual([row['post_id'] for row in sample],
                         ['p01', 'p03', 'p06', 'p08'])
        with self.assertRaises(ValueError):
            select_length_spaced(posts, 11)

    def test_p95_uses_nearest_rank(self):
        self.assertEqual(nearest_rank(list(range(1, 21))), 19)
        with self.assertRaises(ValueError):
            nearest_rank([])

    def test_warmup_calls_are_not_timed(self):
        class Detector:
            calls = 0

            def detect(self, _post):
                self.calls += 1

        detector = Detector()
        ticks = iter([0.0, 0.01, 0.02, 0.05])
        times = measure_one(detector, {'post_id': 'p01', 'body': '가'}, 2, 2,
                            clock=lambda: next(ticks))
        self.assertEqual(detector.calls, 4)
        self.assertAlmostEqual(times[0], 10.0)
        self.assertAlmostEqual(times[1], 30.0)


if __name__ == '__main__':
    unittest.main()
