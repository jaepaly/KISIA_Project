#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("prepare_bio.py")
SPEC = importlib.util.spec_from_file_location("prepare_bio", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
bio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bio)


class BioAlignmentTest(unittest.TestCase):
    def test_overlap_alignment_and_decode(self) -> None:
        text = "집 근처 신갈저수지에서"
        offsets = [(0, 0), (0, 1), (2, 4), (5, 7), (7, 10), (10, 12), (0, 0)]
        spans = [
            {
                "span_id": "S01_b01_s01",
                "start": 2,
                "end": 4,
                "type": "REL_HOME",
            },
            {
                "span_id": "S01_b01_s02",
                "start": 5,
                "end": 10,
                "type": "LOC_FACILITY",
            },
        ]
        labels, covered = bio.align_bio(offsets, spans)

        self.assertEqual(covered, {"S01_b01_s01", "S01_b01_s02"})
        self.assertEqual(labels[0], -100)
        self.assertEqual(bio.ID2LABEL[labels[2]], "B-REL_HOME")
        self.assertEqual(bio.ID2LABEL[labels[3]], "B-LOC_FACILITY")
        self.assertEqual(bio.ID2LABEL[labels[4]], "I-LOC_FACILITY")
        decoded = bio.decode_bio(text, offsets, labels)
        self.assertEqual(decoded[0], {"start": 2, "end": 4, "type": "REL_HOME", "text": "근처"})
        self.assertEqual(decoded[1]["start"], 5)
        self.assertEqual(decoded[1]["end"], 10)

    def test_span_cut_by_window_is_not_partially_labeled(self) -> None:
        offsets = [(0, 0), (5, 7), (7, 10), (0, 0)]
        spans = [{"span_id": "s1", "start": 4, "end": 10, "type": "LOC_FACILITY"}]
        labels, covered = bio.align_bio(offsets, spans)
        self.assertEqual(covered, set())
        self.assertEqual([bio.ID2LABEL[x] for x in labels if x >= 0], ["O", "O"])

    def test_i_without_matching_b_starts_a_span(self) -> None:
        offsets = [(0, 2)]
        labels = [bio.LABEL2ID["I-AGE"]]
        self.assertEqual(
            bio.decode_bio("마흔", offsets, labels),
            [{"start": 0, "end": 2, "type": "AGE", "text": "마흔"}],
        )

    def test_encode_channels_reports_roundtrip(self) -> None:
        class FakeFastTokenizer:
            is_fast = True

            def __call__(self, text: str, **_: object) -> dict[str, list[list[object]]]:
                # "에서"가 앞 토큰과 합쳐져 골드 경계보다 두 글자 길어진 상황.
                return {
                    "input_ids": [[101, 10, 11, 102]],
                    "attention_mask": [[1, 1, 1, 1]],
                    "offset_mapping": [[(0, 0), (0, 2), (2, 6), (0, 0)]],
                    "overflow_to_sample_mapping": [0],
                }

        channels = [
            {
                "post_id": "S01_b01",
                "persona_id": "S01",
                "text_id": "body",
                "text": "집앞에서",
                "spans": [
                    {
                        "span_id": "S01_b01_s01",
                        "text_id": "body",
                        "start": 0,
                        "end": 3,
                        "text": "집앞에",
                        "type": "REL_HOME",
                        "level": "inferential",
                        "subject": "self",
                    }
                ],
            }
        ]
        examples, metrics = bio.encode_channels(
            channels, FakeFastTokenizer(), max_length=8, stride=2
        )
        self.assertEqual(len(examples), 1)
        self.assertEqual(metrics["roundtrip"]["near"], 1)
        self.assertEqual(metrics["roundtrip"]["bad"], 0)


if __name__ == "__main__":
    unittest.main()
