"""Offline checks for the isolated large-model training handoff."""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from transformers import PreTrainedTokenizerFast, XLMRobertaConfig, XLMRobertaForTokenClassification
from tokenizers import Tokenizer
from tokenizers.models import WordLevel


ROOT = Path(__file__).resolve().parents[3]
PARENT_COMMIT = "1cb782d9ae03741520f4565daea46fbfd3cbf0e1"  # original handoff runner
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

    # ---- follow-up options: schedule / clipping / train seed --------------

    def _run(self, module, folder, name, extra=()):
        """Tiny CPU run; the model is built inside main() after its seeding."""
        if not (folder / "bio").exists():
            self._fixture = fixture(folder)
        bio, manifest, tokenizer = self._fixture
        output = folder / name
        # CPU-only: keep CUDA uninitialized so the strict-determinism test in
        # this process still runs before any CUDA initialization.
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=tokenizer), \
             patch("transformers.AutoModelForTokenClassification.from_pretrained",
                   side_effect=lambda *a, **k: tiny_model()), \
             patch.object(module.shared, "configure_determinism"), \
             patch("torch.cuda.is_available", return_value=False):
            module.main(["--bio-dir", str(bio), "--manifest", str(manifest),
                         "--output-dir", str(output), "--device", "cpu", "--epochs", "2", *extra])
        return (train.read_object(output / "selection.json"),
                train.read_object(output / "run_metrics.json"))

    def test_defaults_match_parent_commit_training_exactly(self):
        args = train.parse_args(["--bio-dir", "b", "--output-dir", "o"])
        self.assertEqual((args.schedule, args.warmup_ratio, args.max_grad_norm, args.train_seed),
                         ("constant", 0.0, 0.0, train.SEED))
        for bad in (["--warmup-ratio", "0.1"],  # warmup needs the linear schedule
                    ["--schedule", "linear", "--warmup-ratio", "1"],
                    ["--max-grad-norm", "-1"]):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                train.parse_args(["--bio-dir", "b", "--output-dir", "o", *bad])
        try:
            source = subprocess.run(
                ["git", "show", f"{PARENT_COMMIT}:experiments/exp44-xlmr-handoff/train_large.py"],
                cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("parent commit not available (shallow clone)")
        source = source.replace("ROOT = Path(__file__).resolve().parents[2]",
                                f"ROOT = Path({str(ROOT)!r})")
        parent = types.ModuleType("train_large_parent")
        parent.__file__ = str(ROOT / "experiments/exp44-xlmr-handoff/train_large.py")
        exec(compile(source, "train_large_parent", "exec"), parent.__dict__)
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            old, old_run = self._run(parent, folder, "parent")
            new, new_run = self._run(train, folder, "current")
        # Same initial weights, shuffle order and updates -> identical best weights.
        self.assertEqual(old["weights_sha256"], new["weights_sha256"])
        self.assertEqual(old["epoch"], new["epoch"])
        self.assertEqual([e["train"]["loss"] for e in old_run["history"]],
                         [e["train"]["loss"] for e in new_run["history"]])

    def test_train_seed_changes_init_but_not_the_frozen_split(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            a, _ = self._run(train, folder, "seed-a", ["--train-seed", "1"])
            b, _ = self._run(train, folder, "seed-b", ["--train-seed", "2"])
            manifest = train.read_object(folder / "manifest.json")
        self.assertNotEqual(a["weights_sha256"], b["weights_sha256"])
        self.assertEqual(a["dev_personas"], b["dev_personas"])
        self.assertEqual(a["dev_personas"], manifest["dev_personas"])
        self.assertEqual((a["seed"], a["train_seed"], b["train_seed"]), (train.SEED, 1, 2))

    def test_linear_schedule_shape_and_warmup_boundaries(self):
        self.assertEqual(train.optimizer_steps_per_epoch(33, 1, 16), 3)
        self.assertEqual(train.optimizer_steps_per_epoch(32, 1, 16), 2)
        total, warm = 100, 10
        factors = [train.lr_factor(i, total, warm, "linear") for i in range(total)]
        self.assertAlmostEqual(factors[0], .1)  # warmup starts at base_lr / warmup_steps
        self.assertAlmostEqual(factors[warm - 1], 1.0)
        self.assertAlmostEqual(factors[warm], 1.0)
        self.assertTrue(all(a >= b for a, b in zip(factors[warm:], factors[warm + 1:])))
        self.assertGreater(factors[-1], 0.0)  # the last update still uses a positive lr
        self.assertAlmostEqual(train.lr_factor(total, total, warm, "linear"), 0.0)
        self.assertEqual({train.lr_factor(i, total, warm, "constant") for i in range(total)}, {1.0})
        # A high ratio on a tiny run still leaves a decay step and ends at 0.
        for steps, ratio in ((1, .5), (2, .9), (3, .99)):
            with self.subTest(steps=steps, ratio=ratio):
                warmup = train.warmup_step_count(steps, ratio)
                self.assertLess(warmup, steps)
                self.assertEqual(train.lr_factor(steps, steps, warmup, "linear"), 0.0)

    def test_clipping_uses_unscaled_gradient_with_active_scaler(self):
        torch.manual_seed(3)
        model = tiny_model()
        ids = torch.tensor([[0, 4, 5, 6, 7, 2]])
        batch = [{"input_ids": ids, "attention_mask": torch.ones_like(ids),
                  "labels": torch.tensor([[-100, 1, 2, 0, 1, -100]]), "example_index": [0]}]
        seen = {}

        class Probe(torch.optim.SGD):
            def step(self, closure=None):
                seen["norm"] = torch.norm(torch.stack(
                    [p.grad.norm() for g in self.param_groups for p in g["params"] if p.grad is not None]))
                return super().step(closure)

        scaler = torch.amp.GradScaler("cpu", enabled=True, init_scale=1024.0)
        stats = train.train_epoch(model, batch, Probe(model.parameters(), lr=0), scaler,
                                  torch.device("cpu"), torch.tensor([.02, 1., 1.]), 16, False,
                                  max_grad_norm=1e-3)
        # Without unscale_ the clipped gradient would be 1024x too large here.
        self.assertLessEqual(float(seen["norm"]), 1e-3 * 1.0001)
        self.assertEqual((stats["clipped_steps"], stats["skipped_steps"]), (1, 0))

    def test_skipped_amp_steps_do_not_advance_the_schedule(self):
        torch.manual_seed(5)
        model = tiny_model()
        ids = torch.tensor([[0, 4, 5, 6, 7, 2]])
        batches = [{"input_ids": ids, "attention_mask": torch.ones_like(ids),
                    "labels": torch.tensor([[-100, 1, 2, 0, 1, -100]]), "example_index": [i]}
                   for i in range(3)]

        class SkippingScaler:
            """Mimics GradScaler: a skip means no optimizer step and a lower scale."""
            def __init__(self, skips):
                self.skips, self.calls, self.scale_value, self.skip = skips, 0, 8.0, False

            def is_enabled(self):
                return True

            def get_scale(self):
                return self.scale_value

            def scale(self, loss):
                return loss

            def unscale_(self, optimizer):
                pass

            def step(self, optimizer):
                self.skip = self.calls in self.skips
                if not self.skip:
                    optimizer.step()

            def update(self):
                if self.skip:
                    self.scale_value /= 2
                self.calls += 1

        optimizer = torch.optim.SGD(model.parameters(), lr=1.0)
        scheduler = torch.optim.lr_scheduler.LambdaLR(
            optimizer, lambda step: train.lr_factor(step, 2, 0, "linear"))
        # Groups of one batch: the first and the third group overflow.
        stats = train.train_epoch(model, batches, optimizer, SkippingScaler({0, 2}),
                                  torch.device("cpu"), torch.tensor([.02, 1., 1.]), 1, False,
                                  scheduler=scheduler)
        self.assertEqual((stats["optimizer_steps"], stats["skipped_steps"]), (3, 2))
        self.assertEqual(scheduler.last_epoch, 1)  # advanced only for the one real update
        self.assertAlmostEqual(stats["lr_end"], .5)

    def test_cpu_tiny_run_records_schedule(self):
        with tempfile.TemporaryDirectory() as temporary:
            selection, run = self._run(train, Path(temporary), "run-linear",
                                       ["--schedule", "linear", "--warmup-ratio", "0.1",
                                        "--max-grad-norm", "1.0", "--train-seed", "7"])
        config = selection["training_config"]
        self.assertEqual(run["training_config"], config)
        self.assertEqual((config["schedule"], config["warmup_ratio"], config["max_grad_norm"]),
                         ("linear", .1, 1.0))
        self.assertLess(config["warmup_steps"], config["total_optimizer_steps"])
        self.assertEqual(sum(e["train"]["optimizer_steps"] for e in run["history"]),
                         config["total_optimizer_steps"])
        self.assertAlmostEqual(run["history"][-1]["train"]["lr_end"], 0.0)


if __name__ == "__main__":
    unittest.main()
