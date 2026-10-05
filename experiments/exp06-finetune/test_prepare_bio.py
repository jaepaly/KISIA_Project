#!/usr/bin/env python3
"""문자 스팬의 BIO 정렬·복원과 창 경계에서의 스팬 처리를 검증한다."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("prepare_bio.py")
SPEC = importlib.util.spec_from_file_location("prepare_bio", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
bio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bio)


class BioAlignmentTest(unittest.TestCase):
    def test_teacher_option_respects_split_and_skips_invalid_record(self) -> None:
        def record(post_id: str, reviewed: bool, *, overlapping: bool = False) -> dict:
            spans = [{
                "span_id": f"{post_id}_s01", "text_id": "body", "start": 0,
                "end": 2, "text": "서울", "type": "LOC_ADMIN",
                "level": "explicit", "subject": "self",
            }]
            if overlapping:
                spans.append({**spans[0], "span_id": f"{post_id}_s02"})
            return {
                "post_id": post_id, "persona_id": post_id.split("_")[0],
                "reviewed": reviewed, "texts": {"body": "서울에서"}, "spans": spans,
            }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "A01_spans.jsonl"
            rows = [
                record("A01_b01", True), record("A01_b02", False),
                record("A01_b03", False, overlapping=True), record("A01_b04", False),
            ]
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                            encoding="utf-8")
            train_ids = {"A01_b01", "A01_b02", "A01_b03"}
            test_ids = {"A01_b04"}

            reviewed_channels, reviewed_stats = bio.load_training_channels(
                Path(directory), train_ids, test_ids
            )
            self.assertEqual([channel["post_id"] for channel in reviewed_channels], ["A01_b01"])
            self.assertEqual(reviewed_stats["reviewed_records_accepted"], 1)

            all_channels, all_stats = bio.load_training_channels(
                Path(directory), train_ids, test_ids, include_unreviewed=True
            )
            self.assertEqual([channel["post_id"] for channel in all_channels],
                             ["A01_b01", "A01_b02"])
            self.assertEqual(all_stats["teacher_records_accepted"], 1)
            self.assertEqual(all_stats["teacher_records_invalid"], 1)
            self.assertEqual(all_stats["test_records_excluded"], 1)

    def test_extra_gold_dir_is_train_only_and_rejects_split_collision(self) -> None:
        """#310 — 학습 전용 추가 데이터: 분할에 없는 글만 받고, 기존 분할과 post_id 가 겹치면 멈춘다."""
        span = {"span_id": "AUG1_0001_s01", "text_id": "body", "start": 0, "end": 2, "text": "합정",
                "type": "LOC_ADMIN", "level": "explicit", "subject": "self"}
        good = {"post_id": "AUG1_0001", "persona_id": "AUG1", "reviewed": False,
                "texts": {"body": "합정동 산책"}, "spans": [span]}
        bad = {"post_id": "AUG1_0002", "persona_id": "AUG1", "reviewed": False,
               "texts": {"body": "합"}, "spans": [{**span, "span_id": "AUG1_0002_s01"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "AUG1_spans.jsonl"
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in (good, bad)) + "\n", encoding="utf-8")
            channels, stats = bio.load_extra_channels([Path(directory)], {"A01_b01"}, {"A01_b02"})
            self.assertEqual([c["post_id"] for c in channels], ["AUG1_0001"])
            self.assertEqual(stats["augment_records_accepted"], 1)
            self.assertEqual(stats["augment_records_invalid"], 1)
            with self.assertRaises(bio.DataError):
                bio.load_extra_channels([Path(directory)], {"AUG1_0001"}, set())

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
