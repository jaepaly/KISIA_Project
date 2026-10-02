"""저장된 재학습 체크포인트를 내부 검수 eval에서만 재채점한다.

공식 test는 읽지 않는다. 임계값 때문에 예측이 사라졌는지, 토큰 예측 자체가
O로 쏠렸는지 구분하며 기존 epoch 평가와 0.7 결과가 일치하는지도 확인한다.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gc
import hashlib
import json
import math
from pathlib import Path

import infer
import train


def score_thresholds(gold, raw_predictions, thresholds):
    """이미 겹침 해소된 0.0 후보에 같은 점수 필터만 다시 적용한다."""
    results = {}
    for threshold in thresholds:
        selected = {
            key: {(span["start"], span["end"], span["type"])
                  for span in spans if span["score"] >= threshold}
            for key, spans in raw_predictions.items()
        }
        results[str(threshold)] = {
            "candidates": sum(len(spans) for spans in selected.values()),
            "partial": train.score_span_sets(gold, selected)["overall"],
        }
    return results


def token_tag_counts(detector, sources):
    """유효 텍스트 토큰의 O/비O argmax와 비유한 logit 수를 센다."""
    torch = detector.torch
    counts = Counter()
    with torch.no_grad():
        for text in sources.values():
            encoded = detector.tok(
                text, truncation=True, max_length=detector.max_length,
                stride=detector.stride, return_overflowing_tokens=True,
                return_offsets_mapping=True,
            )
            for first in range(0, len(encoded["input_ids"]), detector.batch_size):
                indexes = range(first, min(first + detector.batch_size, len(encoded["input_ids"])))
                features = [
                    {key: encoded[key][i] for key in detector.tok.model_input_names if key in encoded}
                    for i in indexes
                ]
                batch = detector.tok.pad(features, padding=True, return_tensors="pt")
                logits = detector.model(
                    **{key: value.to(detector.device) for key, value in batch.items()}
                ).logits.cpu()
                for local, index in enumerate(indexes):
                    offsets = encoded["offset_mapping"][index]
                    valid = [i for i, (start, end) in enumerate(offsets) if start < end]
                    if not valid:
                        continue
                    values = logits[local, valid]
                    counts["logit_values"] += values.numel()
                    counts["nonfinite_logits"] += int((~torch.isfinite(values)).sum())
                    tags = values.argmax(-1)
                    counts["tokens"] += len(valid)
                    counts["o_tokens"] += int((tags == 0).sum())
                    counts["non_o_tokens"] += int((tags != 0).sum())
    return dict(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--epochs", nargs="+", type=int, default=[3, 5, 10])
    parser.add_argument("--thresholds", nargs="+", type=float, default=[0.0, 0.3, 0.7])
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists() or "runs" not in args.output_dir.parts:
        parser.error("Use a new output directory under runs/")
    if args.threads < 1 or not args.epochs or len(set(args.epochs)) != len(args.epochs):
        parser.error("Positive threads and unique epochs are required")
    if args.thresholds != sorted(set(args.thresholds)) or any(
        not math.isfinite(t) or not 0 <= t <= 1 for t in args.thresholds
    ) or 0.0 not in args.thresholds or 0.7 not in args.thresholds:
        parser.error("Thresholds must be unique, ascending, within [0,1], and include 0 and 0.7")

    checkpoints = [args.run_dir / f"checkpoint-epoch-{epoch}" for epoch in args.epochs]
    states = [json.loads((path / "trainer_state.json").read_text(encoding="utf-8"))
              for path in checkpoints]
    first = states[0]["eval"]
    config = first["run_config"]
    if not config["settings"].get("eval_reviewed_only"):
        raise ValueError("This diagnostic requires a reviewed-only internal eval")
    if config["data_sha256"] != train.file_sha256(args.data):
        raise ValueError("BIO input hash differs from the checkpoint run")
    if not first["split"].startswith("persona_holdout_reviewed_only:"):
        raise ValueError("Unexpected internal split")
    for epoch, state in zip(args.epochs, states):
        current = state["eval"]
        if state["completed_epochs"] != epoch or current["run_config"] != config:
            raise ValueError(f"Checkpoint epoch/config mismatch: {epoch}")

    rows = train.read_jsonl(args.data)
    _, eval_rows, split = train.split_examples(
        rows, eval_ratio=config["settings"]["eval_ratio"], seed=config["settings"]["seed"],
        overfit=0, eval_reviewed_only=True,
    )
    if split != first["split"] or not all(row["reviewed"] for row in eval_rows):
        raise ValueError("Internal eval reconstruction mismatch")
    eval_ids_sha = hashlib.sha256(
        json.dumps([row["example_id"] for row in eval_rows]).encode("utf-8")
    ).hexdigest()
    if eval_ids_sha != config["eval"]["example_ids_sha256"]:
        raise ValueError("Internal eval example IDs differ from the checkpoint")
    sources = {}
    gold = defaultdict(set)
    for row in eval_rows:
        key = (row["post_id"], row["text_id"])
        if key in sources and sources[key] != row["text"]:
            raise ValueError(f"Conflicting eval text for {key}")
        sources[key] = row["text"]
        gold[key].update((span["start"], span["end"], span["type"]) for span in row["spans"])

    import torch
    torch.set_num_threads(args.threads)
    results = []
    for epoch, checkpoint, state in zip(args.epochs, checkpoints, states):
        detector = infer.SpanDetector(checkpoint, device=args.device, min_span_score=0.0)
        raw_predictions = {key: detector.predict_channel(text) for key, text in sources.items()}
        if any(not math.isfinite(span["score"]) for spans in raw_predictions.values() for span in spans):
            raise ValueError(f"Nonfinite candidate score at epoch {epoch}")
        thresholds = score_thresholds(gold, raw_predictions, args.thresholds)
        if thresholds["0.7"]["partial"] != state["eval"]["overall"]:
            raise ValueError(f"0.7 score does not match saved train evaluation at epoch {epoch}")
        candidate_scores = sorted(span["score"] for spans in raw_predictions.values() for span in spans)
        row = {
            "epoch": epoch,
            "checkpoint_sha256": {p.name: train.file_sha256(p)
                                  for p in checkpoint.glob("*.safetensors")},
            "train_loss": state["eval"]["train_loss"],
            "global_step": state["global_step"],
            "thresholds": thresholds,
            "candidate_score_min": candidate_scores[0] if candidate_scores else None,
            "candidate_score_median": candidate_scores[len(candidate_scores) // 2]
                if candidate_scores else None,
            "candidate_score_max": candidate_scores[-1] if candidate_scores else None,
            "token_tags": token_tag_counts(detector, sources),
        }
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        del detector
        gc.collect()
        if args.device.startswith("cuda"):
            torch.cuda.empty_cache()

    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "internal reviewed-only eval; official test not read",
        "run_dir": str(args.run_dir), "data_sha256": config["data_sha256"],
        "eval_example_ids_sha256": eval_ids_sha, "eval_windows": len(eval_rows),
        "eval_channels": len(sources), "gold_spans": sum(map(len, gold.values())),
        "device": args.device, "threads": args.threads,
        "results": results,
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Saved: {args.output_dir / 'metrics.json'}")


if __name__ == "__main__":
    main()
