"""Offline checks for the isolated large-model training handoff."""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from transformers import PreTrainedTokenizerFast, XLMRobertaConfig, XLMRobertaForTokenClassification
from tokenizers import Tokenizer
from tokenizers.models import WordLevel


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "train_large", ROOT / "experiments/exp44-xlmr-handoff/train_large.py"
)
train = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(train)


def tiny_model():
    config = XLMRobertaConfig(
        vocab_size=24, hidden_size=12, num_hidden_layers=1,
        num_attention_heads=3, intermediate_size=18, max_position_embeddings=32,
        pad_token_id=1, num_labels=3, hidden_dropout_prob=0.0,
        attention_probs_dropout_prob=0.0, classifier_dropout=0.0,
    )
    config._attn_implementation = "eager"
    return XLMRobertaForTokenClassification(config)


def fixture(folder):
    bio = folder / "bio"
    bio.mkdir()
    rows = []
    for index in range(10):
        rows.append({
            "example_id": f"P{index}_b01_body", "post_id": f"P{index}_b01",
            "persona_id": f"P{index}", "text_id": "body", "text": "가 나",
            "input_ids": [0, 4, 5, 2], "attention_mask": [1] * 4,
            "offset_mapping": [[0, 0], [0, 1], [2, 3], [0, 0]],
            "labels": [-100, 1, 0, -100],
            "spans": [{"start": 0, "end": 1, "type": "JOB"}],
        })
    (bio / "train.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    labels = ["O", "B-JOB", "I-JOB"]
    mapping = {label: i for i, label in enumerate(labels)}
    (bio / "labels.json").write_text(json.dumps({"labels": labels, "label2id": mapping}), encoding="utf-8")
    _, dev_rows, _ = train.shared.split_examples(rows, eval_ratio=.1, seed=train.SEED, overfit=0)
    package = {
        "model_id": "FacebookAI/xlm-roberta-large", "model_revision": "a" * 40,
        "seed": train.SEED, "eval_ratio": .1, "threshold": .7,
        "dev_personas": sorted({row["persona_id"] for row in dev_rows}),
    }
    manifest = folder / "manifest.json"
    train.save_json(manifest, package)
    prepared = {key: package[key] for key in ("model_id", "model_revision", "seed", "eval_ratio", "dev_personas")}
    prepared.update({
        "bio_sha256": train.shared.file_sha256(bio / "train.jsonl"),
        "labels_sha256": train.shared.file_sha256(bio / "labels.json"),
        "source_manifest_sha256": train.shared.file_sha256(manifest),
        "labels": labels, "label2id": mapping,
    })
    train.save_json(bio / "prepare_manifest.json", prepared)
    backend = Tokenizer(WordLevel({"<s>": 0, "<pad>": 1, "</s>": 2, "<unk>": 3, "가": 4, "나": 5}, unk_token="<unk>"))
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=backend, unk_token="<unk>", pad_token="<pad>",
        bos_token="<s>", eos_token="</s>", model_max_length=16,
    )
    return bio, manifest, tokenizer


class LargeTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_accumulation_matches_joint_weighted_ce_gradient(self):
        torch.manual_seed(11)
        model = tiny_model()
        joint = copy.deepcopy(model)
        ids = torch.tensor([[0, 4, 5, 6, 7, 2], [0, 8, 9, 10, 11, 2]])
        targets = torch.tensor([[-100, 0, 0, 0, 0, -100], [-100, 1, 2, 0, -100, -100]])
        masks = torch.ones_like(ids)
        weights = torch.tensor([.02, 1., 1.])
        batches = [{"input_ids": ids[i:i+1], "attention_mask": masks[i:i+1],
                    "labels": targets[i:i+1], "example_index": [i]} for i in range(2)]
        scaler = torch.amp.GradScaler("cuda", enabled=False)
        stats = train.train_epoch(model, batches, torch.optim.SGD(model.parameters(), lr=0),
                                  scaler, torch.device("cpu"), weights, 16, False)
        # One short final accumulation group: weights and supervised token counts differ.
        joint.train()
        logits = joint(input_ids=ids, attention_mask=masks).logits
        loss = torch.nn.functional.cross_entropy(logits.reshape(-1, 3), targets.reshape(-1),
                                                 weight=weights, ignore_index=-100)
        loss.backward()
        self.assertEqual(stats["optimizer_steps"], 1)
        self.assertAlmostEqual(stats["loss"], loss.item(), places=6)
        for (name, param), (_, expected) in zip(model.named_parameters(), joint.named_parameters()):
            torch.testing.assert_close(param.grad, expected.grad, rtol=2e-4, atol=2e-6, msg=name)

    def test_frozen_holdout_hash_mapping_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            bio, manifest, _ = fixture(folder)
            result = train.validate_inputs(bio, manifest)
            train_rows, dev_rows = result[-2:]
            self.assertFalse({r["persona_id"] for r in train_rows} & {r["persona_id"] for r in dev_rows})
            prepared = train.read_object(bio / "prepare_manifest.json")
            for key, wrong in (("dev_personas", ["other"]), ("bio_sha256", "wrong"),
                               ("label2id", {"O": 2})):
                with self.subTest(key=key):
                    train.save_json(bio / "prepare_manifest.json", {**prepared, key: wrong})
                    with self.assertRaises(train.TrainError):
                        train.validate_inputs(bio, manifest)
            output = folder / "already-exists"
            output.mkdir()
            with self.assertRaises(train.TrainError):
                train.reserve_output(output)

    def test_cpu_tiny_run_saves_earliest_best_only_after_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            bio, manifest, tokenizer = fixture(folder)
            output = folder / "run"
            before = (bio / "train.jsonl").read_bytes()
            model = tiny_model()
            # Fresh random tiny weights and a tokenizer constructed in memory:
            # no from_pretrained implementation may download anything.
            with patch("transformers.AutoTokenizer.from_pretrained", return_value=tokenizer), \
                 patch("transformers.AutoModelForTokenClassification.from_pretrained", return_value=model):
                with patch.object(train.shared, "evaluate", wraps=train.shared.evaluate) as evaluated:
                    train.main(["--bio-dir", str(bio), "--manifest", str(manifest),
                                "--output-dir", str(output), "--device", "cpu", "--epochs", "2"])
            selection = train.read_object(output / "selection.json")
            run = train.read_object(output / "run_metrics.json")
            self.assertTrue(run["completed"])
            self.assertEqual(len(run["history"]), 2)
            self.assertEqual(evaluated.call_count, 2)
            scores = [entry["dev"]["overall"]["f1"] for entry in run["history"]]
            self.assertEqual(selection["epoch"], scores.index(max(scores)) + 1)
            self.assertEqual(selection["checkpoint"], "best")
            self.assertEqual(selection["min_span_score"], .7)
            self.assertTrue(selection["weights_sha256"])
            self.assertIn("config.json", selection["checkpoint_files_sha256"])
            self.assertIn("tokenizer.json", selection["checkpoint_files_sha256"])
            for name, digest in selection["checkpoint_files_sha256"].items():
                self.assertEqual(train.shared.file_sha256(output / "best" / name), digest)
            self.assertFalse(list(output.rglob("optimizer.pt")))
            self.assertFalse(list(output.glob("checkpoint-epoch-*")))
            self.assertFalse(model.config.use_cache)
            self.assertTrue(model.is_gradient_checkpointing)
            self.assertTrue(all(parameter.requires_grad for parameter in model.parameters()))
            self.assertEqual(before, (bio / "train.jsonl").read_bytes())
            with self.assertRaises(train.TrainError):
                train.main(["--bio-dir", str(bio), "--manifest", str(manifest),
                            "--output-dir", str(output), "--device", "cpu"])

            failed = folder / "interrupted-run"
            # The first invocation already configured strict deterministic mode
            # in this process. Production commands each start in a fresh process.
            with patch("transformers.AutoTokenizer.from_pretrained", return_value=tokenizer), \
                 patch("transformers.AutoModelForTokenClassification.from_pretrained", return_value=tiny_model()), \
                 patch.object(train.shared, "configure_determinism"), \
                 patch.object(train.shared, "evaluate", side_effect=[run["history"][0]["dev"], torch.cuda.OutOfMemoryError("simulated")]) as evaluation:
                with self.assertRaisesRegex(train.TrainError, "OOM.*aborted"):
                    train.main(["--bio-dir", str(bio), "--manifest", str(manifest),
                                "--output-dir", str(failed), "--device", "cpu", "--epochs", "2"])
            self.assertEqual(evaluation.call_count, 2)
            self.assertFalse((failed / "selection.json").exists())
            self.assertFalse(train.read_object(failed / "run_metrics.json")["completed"])


if __name__ == "__main__":
    unittest.main()
