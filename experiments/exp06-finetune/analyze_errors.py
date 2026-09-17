"""Read-only checkpoint evaluation; write review candidates under ignored runs/."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import train


def match_spans(gold, pred):
    candidates = sorted(
        ((train.span_iou(g, p), gi, pi)
         for gi, g in enumerate(gold) for pi, p in enumerate(pred)
         if g[2] == p[2] and train.span_iou(g, p) >= 0.5),
        reverse=True,
    )
    used_gold, used_pred = set(), set()
    for _, gi, pi in candidates:
        if gi not in used_gold and pi not in used_pred:
            used_gold.add(gi)
            used_pred.add(pi)
    return used_gold, used_pred


def pack(span, text):
    start, end, kind = span
    return {"start": start, "end": end, "type": kind, "text": text[start:end]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=train.DEFAULT_DATA)
    parser.add_argument("--labels", type=Path, default=train.DEFAULT_LABELS)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("experiments/exp06-finetune/runs/error_analysis"))
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--min-span-score", type=float, default=0.0)
    args = parser.parse_args()
    if args.batch_size < 1 or not 0 <= args.min_span_score <= 1:
        raise train.TrainError("Invalid batch size or span-score threshold.")

    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    # Use the recorded split instead of guessing its seed or evaluation ratio.
    state = json.loads((args.checkpoint / "trainer_state.json").read_text(encoding="utf-8"))
    expected = state["eval"]
    split_name = expected["split"]
    if not split_name.startswith("persona_holdout:"):
        raise train.TrainError("Only persona_holdout checkpoints are supported.")
    labels, label2id = train.load_labels(args.labels)
    id2label = dict(enumerate(labels))
    rows = train.read_jsonl(args.data)
    train.validate_examples(rows, len(labels))
    _, eval_rows, _ = train.split_examples(
        rows, eval_ratio=float(split_name.split(":")[1]), seed=expected["seed"], overfit=0)
    tokenizer = AutoTokenizer.from_pretrained(args.checkpoint, local_files_only=True, use_fast=True)
    model = AutoModelForTokenClassification.from_pretrained(args.checkpoint, local_files_only=True)
    if model.config.label2id != label2id:
        raise train.TrainError("Checkpoint and BIO label mappings differ.")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device).eval()
    loader = DataLoader(train.BioDataset(eval_rows), batch_size=args.batch_size,
                        shuffle=False, collate_fn=train.make_collator(tokenizer))
    gold_by_text, pred_by_text = defaultdict(set), defaultdict(set)
    sources, span_scores = {}, defaultdict(list)
    span_origins = defaultdict(list)
    with torch.no_grad():
        for batch in loader:
            indexes = batch.pop("example_index")
            output = model(**{k: v.to(device) for k, v in batch.items()})
            probs = output.logits.softmax(dim=-1).cpu()
            predictions = output.logits.argmax(dim=-1).cpu().tolist()
            for bi, ri in enumerate(indexes):
                row = eval_rows[ri]
                key = (str(row["post_id"]), str(row["text_id"]))
                if key in sources and sources[key]["text"] != row["text"]:
                    raise train.TrainError(f"Conflicting source text: {key}")
                sources[key] = row
                for s in row.get("spans", []):
                    gold_by_text[key].add((int(s["start"]), int(s["end"]), str(s["type"])))
                valid = [-100 if g == -100 else p
                         for p, g in zip(predictions[bi], batch["labels"][bi].tolist())]
                spans = train.decode_token_spans(row["offset_mapping"], valid, id2label)
                pred_by_text[key].update(spans)
                for span in spans:
                    span_origins[(key, span)].append(row["example_id"])
                    scores = [float(probs[bi, ti, tag])
                              for ti, ((start, end), tag) in enumerate(zip(row["offset_mapping"], valid))
                              if tag != -100 and start < end
                              and start < span[1] and end > span[0]]
                    if scores:
                        span_scores[(key, span)].append(train.mean_span_score(scores))

    raw_metrics = train.score_span_sets(gold_by_text, pred_by_text)
    unfiltered_predictions = pred_by_text
    merged_metrics = train.score_span_sets(
        gold_by_text, train.filter_span_predictions(unfiltered_predictions, span_scores, 0.0))
    recorded_policy_metrics = train.score_span_sets(
        gold_by_text, train.filter_span_predictions(unfiltered_predictions, span_scores,
                                                   expected.get("min_span_score", 0.0)))
    pred_by_text = train.filter_span_predictions(unfiltered_predictions, span_scores, args.min_span_score)
    metrics = train.score_span_sets(gold_by_text, pred_by_text)
    # Exploratory validation only: do not alter checkpoint, gold, or train.py.
    threshold_sweep = []
    for threshold in (0.0, 0.5, 0.6, 0.7, 0.8, 0.9):
        filtered = train.filter_span_predictions(unfiltered_predictions, span_scores, threshold)
        threshold_sweep.append({"threshold": threshold,
                                "metrics": train.score_span_sets(gold_by_text, filtered)})
    # Support both old (raw union) and new (overlap-resolved) checkpoints.
    if not any(all(candidate["overall"][name] == expected["overall"][name]
                   for name in ("tp", "fp", "fn")) for candidate in (raw_metrics, recorded_policy_metrics)):
        raise train.TrainError(f"Evaluation did not reproduce recorded counts: "
                               f"{metrics['overall']} vs {expected['overall']}. No files written.")

    errors, predictions_out = [], []
    for key in sorted(sources):
        row, text = sources[key], sources[key]["text"]
        gold, pred = sorted(gold_by_text[key]), sorted(pred_by_text[key])
        used_gold, used_pred = match_spans(gold, pred)
        base = {"post_id": key[0], "text_id": key[1], "persona_id": row["persona_id"], "text": text}
        predictions_out.append({**base, "gold": [pack(s, text) for s in gold],
                                "predicted": [{**pack(s, text), "windows": span_origins[(key, s)],
                                               "confidence": train.mean_span_score(span_scores[(key, s)])}
                                              for s in pred]})
        for category, spans, used, opposite in (
            ("FP", pred, used_pred, gold), ("FN", gold, used_gold, pred)):
            for index, span in enumerate(spans):
                if index in used:
                    continue
                overlapping = [s for s in opposite if min(s[1], span[1]) > max(s[0], span[0])]
                same_type = [s for s in overlapping if s[2] == span[2]]
                if category == "FP" and any(
                    gold[gi][2] == span[2] and train.span_iou(gold[gi], span) >= 0.5
                    for gi in used_gold):
                    hint = "duplicate_candidate"
                elif same_type:
                    hint = "boundary_candidate"
                elif overlapping:
                    hint = "type_confusion_candidate"
                else:
                    hint = "unmatched_requires_semantic_review"
                values = span_scores.get((key, span), []) if category == "FP" else []
                errors.append({"error_id": f"{category}_{sum(e['category'] == category for e in errors) + 1:03}",
                               **base, "category": category, "span": pack(span, text),
                               "hint": hint, "review_status": "pending",
                               "windows": span_origins[(key, span)] if category == "FP" else [],
                               "context": text[max(0, span[0] - 70):span[1] + 70],
                               "overlapping": [{**pack(s, text), "iou": train.span_iou(span, s)}
                                               for s in overlapping],
                               "gold": [pack(s, text) for s in gold],
                               "confidence": sum(values) / len(values) if values else None})
    assert sum(e["category"] == "FP" for e in errors) == metrics["overall"]["fp"]
    assert sum(e["category"] == "FN" for e in errors) == metrics["overall"]["fn"]
    summary = {"checkpoint": str(args.checkpoint), "data_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
               "seed": expected["seed"], "split": split_name, "eval_examples": len(eval_rows),
               "eval_personas": sorted({r["persona_id"] for r in eval_rows}), "metrics": metrics,
               "raw_metrics": raw_metrics, "merge_policy": "longest_first_no_overlap_v1",
               "merged_unfiltered_metrics": merged_metrics, "min_span_score": args.min_span_score,
               "score_policy": "mean_token_probability_then_mean_windows_v1",
               "exploratory_threshold_sweep": threshold_sweep,
               "hints": {c: dict(Counter(e["hint"] for e in errors if e["category"] == c))
                         for c in ("FP", "FN")},
               "note": "Hints are geometric candidates, not confirmed causes. Confidence is mean "
                       "argmax token probability, averaged over windows; not calibrated."}
    targets = [args.output_dir / name for name in ("errors.jsonl", "predictions.jsonl", "summary.json")]
    if any(p.exists() for p in targets):
        raise train.TrainError("Analysis outputs already exist. Choose a new --output-dir.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for path, records in zip(targets[:2], (errors, predictions_out)):
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    targets[2].write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Review files: {args.output_dir}")


if __name__ == "__main__":
    main()
