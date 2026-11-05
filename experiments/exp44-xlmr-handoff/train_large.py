#!/usr/bin/env python3
"""Train the isolated XLM-R-large diagnostic; never reads test labels.

BIO preparation and the package manifest must be frozen before this command.
Only an internal persona holdout selects the best checkpoint (earliest tie).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import platform
import re
import sys
import time
from itertools import islice
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_MANIFEST = Path(__file__).with_name("manifest.json")
SEED = 20260911
EVAL_RATIO = 0.1
THRESHOLD = 0.7

_spec = importlib.util.spec_from_file_location(
    "exp44_shared_train", ROOT / "experiments/exp06-finetune/train.py"
)
shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shared)
TrainError = shared.TrainError


def read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TrainError(f"Cannot read JSON object: {path.name}") from exc
    if not isinstance(value, dict):
        raise TrainError(f"Expected JSON object: {path.name}")
    return value


def validate_inputs(bio_dir: Path, manifest_path: Path):
    """Verify frozen provenance and recompute the existing persona split."""
    package = read_object(manifest_path)
    prepared_path = bio_dir / "prepare_manifest.json"
    prepared = read_object(prepared_path)
    model_id, revision = package.get("model_id"), package.get("model_revision")
    if not isinstance(model_id, str) or not model_id:
        raise TrainError("manifest requires model_id")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise TrainError("model_revision must be an immutable 40-character commit hash")
    for key, expected in (("seed", SEED), ("eval_ratio", EVAL_RATIO)):
        if package.get(key) != expected or prepared.get(key) != expected:
            raise TrainError(f"Frozen {key} differs from the experiment configuration")
    if package.get("threshold") != THRESHOLD:
        raise TrainError("The frozen threshold must be 0.7")
    for key in ("model_id", "model_revision"):
        if prepared.get(key) != package[key]:
            raise TrainError(f"Prepared {key} differs from package manifest")
    hashes = {
        "bio_sha256": shared.file_sha256(bio_dir / "train.jsonl"),
        "labels_sha256": shared.file_sha256(bio_dir / "labels.json"),
        "source_manifest_sha256": shared.file_sha256(manifest_path),
        "prepare_manifest_sha256": shared.file_sha256(prepared_path),
    }
    for key in ("bio_sha256", "labels_sha256", "source_manifest_sha256"):
        if prepared.get(key) != hashes[key]:
            raise TrainError(f"Prepared input hash mismatch: {key}")
    labels, label2id = shared.load_labels(bio_dir / "labels.json")
    if "O" not in label2id or len(labels) != len(label2id):
        raise TrainError("BIO labels must have a one-to-one mapping including O")
    if prepared.get("labels") != labels or prepared.get("label2id") != label2id:
        raise TrainError("Prepared label mapping differs from labels.json")
    rows = shared.read_jsonl(bio_dir / "train.jsonl")
    shared.validate_examples(rows, len(labels))
    if any(not isinstance(row.get("persona_id"), str) or not row["persona_id"] for row in rows):
        raise TrainError("Every BIO example must have a persona_id")
    train_rows, dev_rows, _ = shared.split_examples(
        rows, eval_ratio=EVAL_RATIO, seed=SEED, overfit=0
    )
    dev_personas = sorted({row["persona_id"] for row in dev_rows})
    for value in (package.get("dev_personas"), prepared.get("dev_personas")):
        if not isinstance(value, list) or value != dev_personas:
            raise TrainError("Recomputed dev personas differ from the frozen holdout")
    if {r["persona_id"] for r in train_rows} & set(dev_personas):
        raise TrainError("Train/dev persona overlap")
    return package, prepared, hashes, labels, label2id, train_rows, dev_rows


def reserve_output(path: Path) -> None:
    """Never overwrite even an empty directory from a previous attempt."""
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise TrainError("Output already exists; choose a new output directory") from exc


def accumulation_groups(loader, accumulation: int):
    iterator = iter(loader)
    while group := list(islice(iterator, accumulation)):
        yield group


def weighted_denominator(group, class_weights):
    """The CE mean denominator is the sum of target-class weights, not tokens."""
    import torch

    targets = torch.cat([batch["labels"].reshape(-1) for batch in group])
    valid = targets[targets != -100].to(class_weights.device)
    denominator = class_weights[valid].sum()
    if not bool(denominator > 0):
        raise TrainError("Accumulation group has no supervised tokens")
    return denominator


def weighted_loss_sum(logits, targets, class_weights):
    import torch.nn.functional as functional

    return functional.cross_entropy(
        logits.float().reshape(-1, logits.shape[-1]), targets.reshape(-1),
        weight=class_weights, ignore_index=-100, reduction="sum",
    )


def optimizer_steps_per_epoch(n_examples: int, batch_size: int, accumulation: int) -> int:
    """One optimizer step per accumulation group, including a short final group."""
    return math.ceil(math.ceil(n_examples / batch_size) / accumulation)


def lr_factor(step: int, total_steps: int, warmup_steps: int, schedule: str) -> float:
    """Multiplier of the base lr before optimizer step `step` (0-based).

    constant: 1.0 throughout (the original handoff run).
    linear: linear warmup to 1.0 over `warmup_steps`, then linear decay to 0
    at `total_steps` (the usual fine-tuning schedule for large encoders).
    Warmup starts at base_lr / warmup_steps (not 0), so the peak is used for
    two consecutive updates; the factor reaches 0 only after the last update.
    """
    if schedule == "constant":
        return 1.0
    if warmup_steps > 0 and step < warmup_steps:
        return (step + 1) / warmup_steps
    remaining = total_steps - warmup_steps
    if remaining <= 0:
        return 0.0
    return max(0.0, (total_steps - step) / remaining)


def warmup_step_count(total_steps: int, warmup_ratio: float) -> int:
    """Rounded warmup length, always leaving at least one decay step."""
    return max(0, min(int(round(total_steps * warmup_ratio)), total_steps - 1))


def train_epoch(model, loader, optimizer, scaler, device, class_weights,
                accumulation: int, fp16: bool, scheduler=None,
                max_grad_norm: float = 0.0) -> dict:
    import torch

    model.train()
    numerator_total = denominator_total = 0.0
    updates = 0
    clipped = skipped = 0
    for group in accumulation_groups(loader, accumulation):
        # Hold only small CPU input tensors for one effective batch. Each graph
        # is backpropagated immediately; sixteen XLM-R graphs never coexist.
        denominator = weighted_denominator(group, class_weights)
        optimizer.zero_grad(set_to_none=True)
        for batch in group:
            inputs = {
                key: value.to(device) for key, value in batch.items()
                if key not in {"labels", "example_index"}
            }
            targets = batch["labels"].to(device)
            with torch.amp.autocast(device.type, enabled=fp16):
                output = model(**inputs)
                numerator = weighted_loss_sum(output.logits, targets, class_weights)
                loss = numerator / denominator
            if not bool(torch.isfinite(loss)):
                raise TrainError("Non-finite training loss; run aborted")
            scaler.scale(loss).backward()
            numerator_total += float(numerator.detach().cpu())
        denominator_total += float(denominator.detach().cpu())
        if max_grad_norm > 0:
            # Clip the true (unscaled) gradient; GradScaler skips inf/NaN steps itself.
            scaler.unscale_(optimizer)
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm)
            clipped += int(bool(torch.isfinite(norm)) and float(norm) > max_grad_norm)
        scale_before = scaler.get_scale() if scaler.is_enabled() else None
        scaler.step(optimizer)
        scaler.update()
        # GradScaler skips the optimizer step on inf/NaN and lowers the scale;
        # the lr schedule advances only on updates that actually happened.
        step_skipped = scale_before is not None and scaler.get_scale() < scale_before
        skipped += int(step_skipped)
        if scheduler is not None and not step_skipped:
            scheduler.step()
        updates += 1
    # optimizer_steps keeps its original meaning: accumulation groups attempted.
    stats = {"loss": numerator_total / denominator_total, "optimizer_steps": updates}
    if scaler.is_enabled():
        stats["skipped_steps"] = skipped
    if max_grad_norm > 0:
        stats["clipped_steps"] = clipped
    if scheduler is not None:
        stats["lr_end"] = float(scheduler.get_last_lr()[0])
    return stats


def environment(model, device) -> dict:
    import torch
    import transformers

    return {
        "python": platform.python_version(), "os": platform.system(),
        "torch": str(torch.__version__), "transformers": transformers.__version__,
        "cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
        "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "device": str(device), "attention_backend": model.config._attn_implementation,
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
    }


def save_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def weight_hashes(checkpoint: Path) -> dict[str, str]:
    paths = sorted(set(checkpoint.glob("model*.safetensors")) |
                   set(checkpoint.glob("pytorch_model*.bin")))
    if not paths:
        raise TrainError("Best checkpoint contains no model weights")
    return {path.name: shared.file_sha256(path) for path in paths}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bio-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=PACKAGE_MANIFEST)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--accumulation", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--o-weight", type=float, default=0.02)
    # Defaults reproduce the original handoff run exactly (constant lr, no
    # clipping, init/shuffle seed = split seed). The dev holdout split always
    # uses the frozen SEED regardless of --train-seed.
    parser.add_argument("--schedule", choices=("constant", "linear"), default="constant")
    parser.add_argument("--warmup-ratio", type=float, default=0.0)
    parser.add_argument("--max-grad-norm", type=float, default=0.0,
                        help="0 disables gradient clipping")
    parser.add_argument("--train-seed", type=int, default=SEED,
                        help="seed for head init and shuffle order; the dev split stays fixed")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    args = parser.parse_args(argv)
    if min(args.epochs, args.batch_size, args.accumulation) < 1:
        parser.error("epochs, batch-size and accumulation must be positive")
    if not math.isfinite(args.lr) or args.lr <= 0 or not 0 < args.o_weight <= 1:
        parser.error("lr must be positive and 0 < o-weight <= 1")
    if not math.isfinite(args.warmup_ratio) or not 0 <= args.warmup_ratio < 1:
        parser.error("warmup-ratio must be in [0, 1)")
    if not math.isfinite(args.max_grad_norm) or args.max_grad_norm < 0:
        parser.error("max-grad-norm must be >= 0")
    if args.schedule == "constant" and args.warmup_ratio:
        parser.error("warmup-ratio requires --schedule linear")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.output_dir.exists():
        raise TrainError("Output already exists; choose a new output directory")
    package, prepared, hashes, labels, label2id, train_rows, dev_rows = validate_inputs(
        args.bio_dir, args.manifest
    )
    import torch

    shared.configure_determinism(True)
    if args.device == "cuda" and not torch.cuda.is_available():
        raise TrainError("CUDA is required; CPU is only an explicit smoke-test option")
    shared.set_seed(args.train_seed)
    from torch.utils.data import DataLoader
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    device = torch.device(args.device)
    fp16 = device.type == "cuda"
    reserve_output(args.output_dir)
    history = []
    run_state = {"completed": False, **hashes, "history": history}
    save_json(args.output_dir / "run_metrics.json", run_state)
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            package["model_id"], revision=package["model_revision"], use_fast=True
        )
        model = AutoModelForTokenClassification.from_pretrained(
            package["model_id"], revision=package["model_revision"],
            num_labels=len(labels), label2id=label2id,
            id2label={i: label for i, label in enumerate(labels)},
            attn_implementation="eager",
        )
        model.config.use_cache = False
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        for parameter in model.parameters():
            parameter.requires_grad_(True)
        model.to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
        steps_per_epoch = optimizer_steps_per_epoch(
            len(train_rows), args.batch_size, args.accumulation)
        total_steps = steps_per_epoch * args.epochs
        warmup_steps = warmup_step_count(total_steps, args.warmup_ratio)
        scheduler = None
        if args.schedule != "constant":
            scheduler = torch.optim.lr_scheduler.LambdaLR(
                optimizer, lambda step: lr_factor(step, total_steps, warmup_steps, args.schedule))
        scaler = torch.amp.GradScaler("cuda", enabled=fp16)
        weights = torch.ones(len(labels), device=device)
        weights[label2id["O"]] = args.o_weight
        collator = shared.make_collator(tokenizer)
        loader = DataLoader(
            shared.BioDataset(train_rows), batch_size=args.batch_size, shuffle=True,
            collate_fn=collator, num_workers=0,
            generator=torch.Generator().manual_seed(args.train_seed),
        )
        dev_loader = DataLoader(
            shared.BioDataset(dev_rows), batch_size=args.batch_size, shuffle=False,
            collate_fn=collator, num_workers=0,
            generator=torch.Generator().manual_seed(SEED + 1),
        )
        config = {
            "epochs": args.epochs, "batch_size": args.batch_size,
            "accumulation": args.accumulation,
            "effective_batch_size": args.batch_size * args.accumulation,
            "lr": args.lr, "o_weight": args.o_weight, "weight_decay": 0.01,
            "seed": SEED, "train_seed": args.train_seed,
            "schedule": args.schedule, "warmup_ratio": args.warmup_ratio,
            "warmup_steps": warmup_steps, "total_optimizer_steps": total_steps,
            "max_grad_norm": args.max_grad_norm,
            "eval_ratio": EVAL_RATIO, "fp16": fp16,
            "gradient_checkpointing": True, "use_reentrant": False,
            "all_parameters_trainable": True, "use_cache": False,
            "attention_backend": "eager", "min_span_score": THRESHOLD,
            "loss_normalization": "group_sum_weighted_ce/group_sum_target_class_weights",
        }
        run_state["training_config"] = config  # kept even when a run fails
        best_f1 = -1.0
        selection = None
        started = time.monotonic()
        for epoch in range(1, args.epochs + 1):
            trained = train_epoch(
                model, loader, optimizer, scaler, device, weights, args.accumulation, fp16,
                scheduler=scheduler, max_grad_norm=args.max_grad_norm,
            )
            dev = shared.evaluate(
                model, dev_loader, dev_rows, device,
                {i: label for i, label in enumerate(labels)}, THRESHOLD,
            )
            f1 = float(dev["overall"]["f1"])
            if not math.isfinite(f1):
                raise TrainError("Non-finite dev F1; run aborted")
            history.append({"epoch": epoch, "train": trained, "dev": dev})
            if f1 > best_f1:  # A tie retains the earlier epoch.
                best_f1 = f1
                best = args.output_dir / "best"
                model.save_pretrained(best)
                tokenizer.save_pretrained(best)
                selection = {
                    "checkpoint": "best", "epoch": epoch, "dev": dev,
                    "prepared_dir": os.path.relpath(args.bio_dir.resolve(), args.output_dir.resolve()),
                    "model_id": package["model_id"],
                    "model_revision": package["model_revision"],
                    "min_span_score": THRESHOLD, **hashes,
                    "dev_personas": prepared["dev_personas"], "seed": SEED,
                    "train_seed": args.train_seed,
                    "training_config": config, "environment": environment(model, device),
                }
            save_json(args.output_dir / "run_metrics.json", run_state)
            print(f"epoch={epoch}/{args.epochs} dev_f1={f1:.6f} best_epoch={selection['epoch']}", flush=True)
        selection["weights_sha256"] = weight_hashes(args.output_dir / "best")
        selection["checkpoint_files_sha256"] = {
            path.relative_to(args.output_dir / "best").as_posix(): shared.file_sha256(path)
            for path in sorted((args.output_dir / "best").rglob("*")) if path.is_file()
        }
        # No selection file is published until every requested epoch succeeds.
        save_json(args.output_dir / "selection.json", selection)
        run_state.update({"completed": True, "completed_epochs": args.epochs,
                          "requested_epochs": args.epochs, "selection": selection,
                          "elapsed_seconds": round(time.monotonic() - started, 2)})
        save_json(args.output_dir / "run_metrics.json", run_state)
    except torch.cuda.OutOfMemoryError as exc:
        run_state["error"] = "CUDA OOM: aborted; batch size, precision and model were not changed"
        save_json(args.output_dir / "run_metrics.json", run_state)
        raise TrainError(run_state["error"]) from exc
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TrainError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
