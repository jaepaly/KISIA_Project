"""Standard-library regression checks; no models, network, or GPU required."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("handoff", Path(__file__).resolve().parents[1] / "handoff.py")
handoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handoff)


def span(start=0, end=3, text="딸과", typ="FAM"):
    return dict(span_id="P_s01", text_id="body", start=start, end=end, text=text,
                type=typ, subject="self", level="implicit")


class ValidationTests(unittest.TestCase):
    def test_canonical_hash_ignores_dictionary_insertion_order(self):
        self.assertEqual(handoff.canonical_texts_hash({"body": "본문", "title": "제목"}),
                         handoff.canonical_texts_hash({"title": "제목", "body": "본문"}))
        self.assertNotEqual(handoff.canonical_texts_hash({"body": "본문"}),
                            handoff.canonical_texts_hash({"body": "변경"}))

    def test_duplicate_post_ids_rejected(self):
        with self.assertRaises(handoff.ValidationError):
            handoff.index_unique([{"post_id": "A"}, {"post_id": "A"}], "fixture")

    def test_offset_and_eojeol_boundary_validation(self):
        handoff.validate_spans("P", {"body": "딸과 산책"}, [span(end=2)])
        with self.assertRaises(handoff.ValidationError):
            handoff.validate_spans("P", {"body": "딸과 산책"}, [span()])
        with self.assertRaises(handoff.ValidationError):
            handoff.validate_spans("P", {"body": "딸과 산책"}, [span(end=1, text="딸")])

    def test_overlap_rejected(self):
        a = span(end=2)
        b = dict(a, span_id="P_s02", type="SEX")
        with self.assertRaises(handoff.ValidationError):
            handoff.validate_spans("P", {"body": "딸과 산책"}, [a, b])

    def test_reference_boundary_warning_does_not_relax_offsets(self):
        warnings = handoff.validate_spans("P", {"body": "딸과 산책"}, [span(end=1, text="딸")], False)
        self.assertEqual(len(warnings), 1)
        with self.assertRaises(handoff.ValidationError):
            handoff.validate_spans("P", {"body": "딸과 산책"}, [span()], False)

    def test_id_and_full_body_leakage_rejected(self):
        sources = {"A": {"texts": {"body": "동일 본문"}}, "B": {"texts": {"body": "동일 본문"}}}
        with self.assertRaisesRegex(handoff.ValidationError, "ID leakage"):
            handoff.validate_split_isolation({"train": {"A"}, "test": {"A"}}, sources)
        with self.assertRaisesRegex(handoff.ValidationError, "Full-body duplicate"):
            handoff.validate_split_isolation({"train": {"A"}, "test": {"B"}}, sources)
        sources["B"]["texts"]["body"] = "다른 본문"
        handoff.validate_split_isolation({"train": {"A"}, "test": {"B"}}, sources)

    def test_nfc_and_extra_span_fields_rejected(self):
        with self.assertRaises(handoff.ValidationError):
            handoff.validate_spans("P", {"body": "가"}, [])
        with self.assertRaises(handoff.ValidationError):
            handoff.validate_spans("P", {"body": "딸과"}, [dict(span(end=2), score=.9)])

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(handoff.ValidationError):
                handoff.contained(Path(temporary), "../outside.json")

    def test_checkpoint_hashes_cover_tokenizer_and_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for name in ("model.safetensors", "config.json", "tokenizer.json"):
                (base / name).write_bytes(b"initial")
            before = handoff.checkpoint_hashes(base)
            self.assertEqual(set(before), {"model.safetensors", "config.json", "tokenizer.json"})
            (base / "tokenizer.json").write_bytes(b"changed")
            self.assertNotEqual(before, handoff.checkpoint_hashes(base))

    def test_frozen_file_hash_failure_precedes_data_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); (base / "labels.jsonl").write_text("{}\n", encoding="utf8")
            manifest = dict(format_version=1, model_id="FacebookAI/xlm-roberta-large", model_revision="a" * 40,
                            threshold=.7, seed=20260911, dev_personas=[f"P{i}" for i in range(9)],
                            train_labels="labels.jsonl", references=[], files_sha256={"labels.jsonl": "0" * 64})
            with self.assertRaisesRegex(handoff.ValidationError, "Frozen file hash mismatch"):
                handoff.validate_dataset(manifest, {}, base)

    def test_typed_greedy_is_one_to_one(self):
        g = [dict(text_id="body", start=0, end=4, type="JOB")]
        p = [dict(g[0]), dict(g[0])]
        self.assertEqual(handoff.match_counts(g, p), (1, 1, 0))
        self.assertEqual(handoff.match_counts(g, [dict(g[0], type="FAM")]), (0, 1, 1))
        self.assertEqual(handoff.match_counts(g, [dict(g[0], text_id="title")]), (0, 1, 1))

    def test_partial_threshold_and_exact(self):
        g = [dict(text_id="body", start=0, end=4, type="JOB")]
        p = [dict(g[0], end=8)]
        self.assertEqual(handoff.match_counts(g, p), (1, 0, 0))
        self.assertEqual(handoff.match_counts(g, p, exact=True), (0, 1, 1))
        self.assertEqual(handoff.match_counts(g, [dict(g[0], end=9)]), (0, 1, 1))

    def test_zero_gold_false_positive_and_support_metadata(self):
        p = dict(text_id="body", start=0, end=2, type="JOB")
        score = handoff.score_reference({"P": {"spans": []}}, {"P": [p]})
        self.assertEqual(score["zero_gold"], dict(posts=1, posts_with_false_spans=1, false_spans=1))
        self.assertEqual(score["by_type"]["JOB"]["interpretation"], "sample_insufficient")


if __name__ == "__main__":
    unittest.main()
