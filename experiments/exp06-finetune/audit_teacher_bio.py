"""공식 test를 읽지 않고 학습 BIO의 검수/교사 라벨 분포를 집계한다."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

import train


def summarize(rows):
    counts = defaultdict(Counter)
    seen_spans = defaultdict(set)
    for row in rows:
        if not isinstance(row.get("reviewed"), bool):
            raise ValueError("BIO row is missing reviewed marker")
        group = "reviewed" if row["reviewed"] else "teacher"
        count = counts[group]
        count["windows"] += 1
        count["o_tokens"] += sum(label == 0 for label in row["labels"])
        count["positive_tokens"] += sum(label > 0 for label in row["labels"])
        count["ignored_tokens"] += sum(label == -100 for label in row["labels"])
        if not row["spans"]:
            count["zero_span_windows"] += 1
        for span in row["spans"]:
            identity = (row["post_id"], row["text_id"], span["span_id"])
            if identity not in seen_spans[group]:
                seen_spans[group].add(identity)
                count[f"type_{span['type']}"] += 1
                count["unique_spans"] += 1
    return {group: dict(counts[group]) for group in ("reviewed", "teacher")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--eval-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=20260911)
    args = parser.parse_args()
    if args.output_dir.exists() or "runs" not in args.output_dir.parts:
        parser.error("Use a new output directory under runs/")
    rows = train.read_jsonl(args.data)
    train_rows, eval_rows, split = train.split_examples(
        rows, eval_ratio=args.eval_ratio, seed=args.seed, overfit=0,
        eval_reviewed_only=True,
    )
    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "training BIO only; official test not read",
        "data_sha256": train.file_sha256(args.data),
        "seed": args.seed, "split": split,
        "train_windows": len(train_rows), "eval_windows": len(eval_rows),
        "groups": summarize(train_rows),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Saved: {args.output_dir / 'metrics.json'}")


if __name__ == "__main__":
    main()
