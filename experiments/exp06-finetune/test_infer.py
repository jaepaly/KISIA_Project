"""추론 입력의 채널·정규화와 출력 계약·의미 검증을 확인한다.

아래 판정 함수는 테스트용이며 운영 로직이 아니다.
"""
import unittest
from unittest.mock import patch
import infer


class InferTest(unittest.TestCase):
    def detector(self):
        detector = infer.SpanDetector.__new__(infer.SpanDetector)
        detector.version = "test-fixture"
        detector.threshold = 0.7
        return detector

    def test_numeric_channels_and_nfc(self):
        _, _, texts = infer.input_channels({"post_id": "p", "texts": {
            "photo_caption:10": "x", "body": "가", "photo_caption:2": "y", "title": "z"}})
        self.assertEqual(list(texts), ["title", "body", "photo_caption:2", "photo_caption:10"])
        self.assertEqual(texts["body"], "가")

    def test_caption_holes_preserved(self):
        _, _, texts = infer.input_channels({"post_id": "p", "photo_captions": [None, "x"]})
        self.assertEqual(texts, {"photo_caption:1": "x"})

    def test_invalid_inputs(self):
        for record in ({"body": "x"}, {"post_id": "p", "body": 42},
                       {"post_id": "p", "texts": {"profile_bio": "x"}},
                       {"persona_id": "p", "record_type": "profile", "post_id": "x", "profile_bio": "x"}):
            with self.assertRaises(infer.InferenceError):
                infer.input_channels(record)

    def test_default_legacy_policy_warns(self):
        detector = self.detector()
        with patch.object(detector, "predict_raw", return_value=self.raw()), self.assertWarns(RuntimeWarning):
            output = detector.detect({"post_id": "p", "body": "가"})
        self.assertEqual(output["spans"][0]["level"], "implicit")
        self.assertEqual(output["spans"][0]["subject"], "self")

    def test_explicit_resolver_overrides_legacy(self):
        detector = self.detector()
        with patch.object(detector, "predict_raw", return_value=self.raw()):
            output = detector.detect({"post_id": "p", "body": "가"},
                                     resolver=lambda texts, candidate: {"level": "explicit", "subject": "other"})
        self.assertEqual(output["spans"][0]["subject"], "other")
        self.assertEqual(output["spans"][0]["level"], "explicit")

    def raw(self, profile=False):
        record = {"persona_id": "p", "profile_bio": "가"} if profile else {"post_id": "p", "body": "가"}
        with patch.object(infer.SpanDetector, "predict_channel", return_value=[
            {"start": 0, "end": 1, "text": "가", "type": "JOB", "score": 0.8}]):
            return self.detector().predict_raw(record)

    def test_raw_explicitly_not_contract(self):
        raw = self.raw()
        self.assertEqual(raw["output_kind"], "raw_bio_candidates_not_contract")
        self.assertNotIn("level", raw["candidates"][0])
        self.assertNotIn("subject", raw["candidates"][0])

    def test_post_contract(self):
        result = infer.format_contract(self.raw(), lambda texts, candidate: {"level": "implicit", "subject": "other"})
        self.assertEqual(result["spans"][0]["subject"], "other")
        self.assertEqual(result["spans"][0]["span_id"], "p_s01")
        self.assertNotIn("persona_id", result)

    def test_profile_contract(self):
        result = infer.format_contract(self.raw(True), lambda texts, candidate: {"level": "inferential", "subject": "unknown"})
        self.assertEqual(result["spans"][0]["span_id"], "p_bio_s01")
        self.assertNotIn("post_id", result)

    def test_resolver_missing_field(self):
        with self.assertRaises(infer.InferenceError):
            infer.format_contract(self.raw(), lambda texts, candidate: {"subject": "unknown"})

    def test_semantic_mismatch_rejected(self):
        raw = self.raw()
        raw["candidates"][0]["text"] = "나"
        with self.assertRaises(infer.InferenceError):
            infer.format_contract(raw, lambda texts, candidate: {"level": "implicit", "subject": "self"})


if __name__ == "__main__":
    unittest.main()
