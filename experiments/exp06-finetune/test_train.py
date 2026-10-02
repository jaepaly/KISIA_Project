"""학습기의 창 병합·점수 필터·결정적 실행 설정을 검증한다.

모델 다운로드나 GPU는 필요하지 않다.
"""
import unittest
import os
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import train


class WindowMergeTest(unittest.TestCase):
    def test_identical_dedup(self):
        self.assertEqual(train.resolve_overlapping_spans([(0, 3, "JOB")] * 2), {(0, 3, "JOB")})

    def test_nested_longest(self):
        self.assertEqual(train.resolve_overlapping_spans([(0, 3, "SEX"), (0, 6, "SEX")]),
                         {(0, 6, "SEX")})

    def test_different_types_still_conflict(self):
        self.assertEqual(train.resolve_overlapping_spans([(0, 2, "SEX"), (0, 6, "FAM")]),
                         {(0, 6, "FAM")})

    def test_partial_overlap_not_union(self):
        self.assertEqual(train.resolve_overlapping_spans([(0, 5, "JOB"), (3, 9, "JOB")]),
                         {(3, 9, "JOB")})

    def test_adjacent_retained(self):
        self.assertEqual(train.resolve_overlapping_spans([(0, 3, "JOB"), (3, 5, "FAM")]),
                         {(0, 3, "JOB"), (3, 5, "FAM")})

    def test_ties_and_order_are_deterministic(self):
        spans = [(1, 4, "JOB"), (0, 3, "SEX"), (0, 3, "FAM")]
        self.assertEqual(train.resolve_overlapping_spans(spans), {(0, 3, "FAM")})
        self.assertEqual(train.resolve_overlapping_spans(reversed(spans)), {(0, 3, "FAM")})

    def test_channels_are_independent(self):
        by_text = {("p", "title"): {(0, 3, "FAM")}, ("p", "body"): {(0, 3, "JOB")}}
        merged = {k: train.resolve_overlapping_spans(v) for k, v in by_text.items()}
        self.assertEqual(merged, by_text)

    def test_invalid_span_rejected(self):
        with self.assertRaises(train.TrainError):
            train.resolve_overlapping_spans([(3, 3, "JOB")])


class SpanScoreFilterTest(unittest.TestCase):
    def test_default_needs_no_scores(self):
        self.assertEqual(train.filter_span_predictions({("p", "body"): {(0, 3, "JOB")}}, {}, 0),
                         {("p", "body"): {(0, 3, "JOB")}})

    def test_threshold_inclusive_and_window_average(self):
        key = ("p", "body")
        a, b = (0, 3, "JOB"), (4, 6, "FAM")
        scores = {(key, a): [0.6, 0.8], (key, b): [0.69]}
        self.assertEqual(train.filter_span_predictions({key: {a, b}}, scores, 0.7), {key: {a}})

    def test_filter_does_not_resurrect_shorter_overlap(self):
        key = ("p", "body")
        a, b = (0, 3, "JOB"), (0, 6, "JOB")
        self.assertEqual(train.filter_span_predictions(
            {key: {a, b}}, {(key, a): [0.9], (key, b): [0.6]}, 0.7), {key: set()})

    def test_invalid_threshold_and_missing_scores(self):
        for threshold in (-0.1, 1.1, float("nan")):
            with self.assertRaises(train.TrainError):
                train.filter_span_predictions({}, {}, threshold)
        with self.assertRaises(train.TrainError):
            train.filter_span_predictions({("p", "body"): {(0, 3, "JOB")}}, {}, 0.7)

    def test_empty_predictions(self):
        self.assertEqual(train.filter_span_predictions({("p", "body"): set()}, {}, 0.7),
                         {("p", "body"): set()})


class DeterminismTest(unittest.TestCase):
    def test_cli_opt_in(self):
        self.assertFalse(train.parse_args([]).deterministic)
        self.assertTrue(train.parse_args(["--deterministic"]).deterministic)

    def test_disabled_changes_nothing(self):
        fake = MagicMock()
        with patch.dict("sys.modules", {"torch": fake}):
            train.configure_determinism(False)
        fake.use_deterministic_algorithms.assert_not_called()

    def test_strict_configuration(self):
        fake = MagicMock()
        fake.cuda.is_initialized.return_value = False
        with patch.dict("sys.modules", {"torch": fake}), patch.dict(os.environ):
            train.configure_determinism(True)
            self.assertEqual(os.environ["CUBLAS_WORKSPACE_CONFIG"], ":4096:8")
        fake.use_deterministic_algorithms.assert_called_once_with(True)
        self.assertTrue(fake.backends.cudnn.deterministic)
        self.assertFalse(fake.backends.cudnn.benchmark)
        self.assertFalse(fake.backends.cuda.matmul.allow_tf32)

    def test_already_initialized_rejected(self):
        fake = MagicMock()
        fake.cuda.is_initialized.return_value = True
        with patch.dict("sys.modules", {"torch": fake}):
            with self.assertRaises(train.TrainError):
                train.configure_determinism(True)
        fake.use_deterministic_algorithms.assert_not_called()

    def test_hash_matches_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.jsonl"
            path.write_bytes(b"test\n")
            self.assertEqual(train.file_sha256(path), hashlib.sha256(b"test\n").hexdigest())


class ReviewedEvalSplitTest(unittest.TestCase):
    def test_same_reviewed_eval_with_additional_teacher_personas(self):
        reviewed = [
            {"example_id": f"R{i}", "persona_id": f"P{i}", "reviewed": True}
            for i in range(20)
        ]
        teacher = [
            {"example_id": f"U{i}", "persona_id": f"P{i}", "reviewed": False}
            for i in range(20)
        ] + [
            {"example_id": "U20", "persona_id": "P20", "reviewed": False}
        ]
        base_train, base_eval, _ = train.split_examples(
            reviewed, eval_ratio=0.1, seed=42, overfit=0, eval_reviewed_only=True
        )
        mixed_train, mixed_eval, _ = train.split_examples(
            reviewed + teacher, eval_ratio=0.1, seed=42, overfit=0,
            eval_reviewed_only=True,
        )
        self.assertEqual([row["example_id"] for row in base_eval],
                         [row["example_id"] for row in mixed_eval])
        eval_personas = {row["persona_id"] for row in base_eval}
        self.assertTrue(eval_personas.isdisjoint({row["persona_id"] for row in mixed_train}))
        self.assertEqual(len(base_train), 18)
        self.assertEqual(len(mixed_train), 37)

    def test_missing_reviewed_marker_rejected(self):
        with self.assertRaises(train.TrainError):
            train.split_examples([{"persona_id": "P1"}, {"persona_id": "P2"}],
                                 eval_ratio=0.5, seed=42, overfit=0,
                                 eval_reviewed_only=True)


if __name__ == "__main__":
    unittest.main()
