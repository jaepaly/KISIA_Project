#!/usr/bin/env python3
"""KoELECTRA BIO token-classification 학습기.

기본 실행은 BIO 학습 예제를 persona 단위로 train/eval 분리해 1 epoch를 학습한다.
``--overfit 100``은 같은 100개 예제로 학습·평가하여 파이프라인이 작은
표본을 외울 수 있는지 확인한다. 평가는 계약과 동일하게 type 일치와
문자 스팬 IoU >= 0.5인 partial-match F1을 사용한다.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_DATA = Path("experiments/exp06-finetune/runs/bio/train.jsonl")
DEFAULT_LABELS = Path("experiments/exp06-finetune/runs/bio/labels.json")
DEFAULT_OUTPUT = Path("experiments/exp06-finetune/runs/model")
DEFAULT_MODEL = "monologg/koelectra-base-v3-discriminator"


class TrainError(RuntimeError):
    """학습을 시작하기 전에 고쳐야 하는 입력·환경 오류."""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise TrainError(f"BIO 파일이 없습니다: {path}\n먼저 prepare_bio.py를 실행하세요.")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TrainError(f"JSON 오류: {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise TrainError(f"객체가 아닌 JSON: {path}:{line_number}")
            rows.append(row)
    if not rows:
        raise TrainError(f"BIO 예제가 없습니다: {path}")
    return rows


def load_labels(path: Path) -> tuple[list[str], dict[str, int]]:
    if not path.is_file():
        raise TrainError(f"라벨 파일이 없습니다: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    labels = value.get("labels")
    label2id = value.get("label2id")
    if not isinstance(labels, list) or not labels or not isinstance(label2id, dict):
        raise TrainError(f"labels/label2id 형식 오류: {path}")
    if any(label2id.get(label) != index for index, label in enumerate(labels)):
        raise TrainError("labels 순서와 label2id가 일치하지 않습니다.")
    return [str(label) for label in labels], {str(k): int(v) for k, v in label2id.items()}


def validate_examples(rows: Sequence[dict[str, Any]], label_count: int) -> None:
    required = {"example_id", "post_id", "text_id", "text", "input_ids", "attention_mask", "offset_mapping", "labels"}
    seen: set[str] = set()
    for index, row in enumerate(rows):
        missing = required - row.keys()
        if missing:
            raise TrainError(f"BIO 예제 {index}: 필드 누락 {sorted(missing)}")
        example_id = row["example_id"]
        if not isinstance(example_id, str) or example_id in seen:
            raise TrainError(f"BIO 예제 {index}: example_id 누락 또는 중복 {example_id!r}")
        seen.add(example_id)
        lengths = [len(row[key]) for key in ("input_ids", "attention_mask", "offset_mapping", "labels")]
        if len(set(lengths)) != 1:
            raise TrainError(f"{example_id}: 토큰 필드 길이가 다릅니다: {lengths}")
        for label in row["labels"]:
            if not isinstance(label, int) or (label != -100 and not 0 <= label < label_count):
                raise TrainError(f"{example_id}: 잘못된 label id {label!r}")


def split_examples(
    rows: Sequence[dict[str, Any]], *, eval_ratio: float, seed: int, overfit: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    if overfit:
        if overfit > len(rows):
            raise TrainError(f"--overfit {overfit}은 전체 예제 {len(rows)}개보다 큽니다.")
        sample = list(rows[:overfit])
        return sample, sample, f"overfit:{overfit}"

    persona_ids = sorted({str(row["persona_id"]) for row in rows})
    if len(persona_ids) < 2:
        raise TrainError("persona 단위 train/eval 분리를 하려면 인물이 2명 이상 필요합니다.")
    rng = random.Random(seed)
    rng.shuffle(persona_ids)
    eval_count = max(1, round(len(persona_ids) * eval_ratio))
    eval_ids = set(persona_ids[:eval_count])
    train_rows = [row for row in rows if row["persona_id"] not in eval_ids]
    eval_rows = [row for row in rows if row["persona_id"] in eval_ids]
    if not train_rows or not eval_rows:
        raise TrainError("train/eval 중 하나가 비었습니다.")
    return train_rows, eval_rows, f"persona_holdout:{eval_ratio:.3f}"


class BioDataset:
    def __init__(self, rows: Sequence[dict[str, Any]]) -> None:
        self.rows = list(rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        item = {
            "input_ids": row["input_ids"],
            "attention_mask": row["attention_mask"],
            "labels": row["labels"],
            "example_index": index,
        }
        if "token_type_ids" in row:
            item["token_type_ids"] = row["token_type_ids"]
        return item


def make_collator(tokenizer: Any):
    from transformers import DataCollatorForTokenClassification

    base = DataCollatorForTokenClassification(tokenizer=tokenizer, padding=True, return_tensors="pt")

    def collate(features: list[dict[str, Any]]) -> dict[str, Any]:
        indexes = [int(feature.pop("example_index")) for feature in features]
        batch = base(features)
        batch["example_index"] = indexes
        return batch

    return collate


def decode_token_spans(
    offsets: Sequence[Sequence[int]], label_ids: Sequence[int], id2label: dict[int, str]
) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    current: list[Any] | None = None
    for (raw_start, raw_end), label_id in zip(offsets, label_ids):
        start, end = int(raw_start), int(raw_end)
        if start == end or int(label_id) == -100:
            continue
        tag = id2label[int(label_id)]
        if tag == "O":
            if current is not None:
                spans.append((current[0], current[1], current[2]))
                current = None
            continue
        prefix, span_type = tag.split("-", 1)
        if prefix == "B" or current is None or current[2] != span_type:
            if current is not None:
                spans.append((current[0], current[1], current[2]))
            current = [start, end, span_type]
        else:
            current[1] = end
    if current is not None:
        spans.append((current[0], current[1], current[2]))
    return spans


def span_iou(left: tuple[int, int, str], right: tuple[int, int, str]) -> float:
    intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return intersection / union if union else 0.0


def score_span_sets(
    gold_by_text: dict[tuple[str, str], set[tuple[int, int, str]]],
    pred_by_text: dict[tuple[str, str], set[tuple[int, int, str]]],
) -> dict[str, Any]:
    totals = {"tp": 0, "fp": 0, "fn": 0}
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for key in gold_by_text.keys() | pred_by_text.keys():
        gold = sorted(gold_by_text.get(key, set()))
        pred = sorted(pred_by_text.get(key, set()))
        candidates = sorted(
            (
                (span_iou(gold_span, pred_span), gold_index, pred_index)
                for gold_index, gold_span in enumerate(gold)
                for pred_index, pred_span in enumerate(pred)
                if gold_span[2] == pred_span[2] and span_iou(gold_span, pred_span) >= 0.5
            ),
            reverse=True,
        )
        used_gold: set[int] = set()
        used_pred: set[int] = set()
        for _, gold_index, pred_index in candidates:
            if gold_index in used_gold or pred_index in used_pred:
                continue
            used_gold.add(gold_index)
            used_pred.add(pred_index)
            totals["tp"] += 1
            by_type[gold[gold_index][2]]["tp"] += 1
        for index, span in enumerate(gold):
            if index not in used_gold:
                totals["fn"] += 1
                by_type[span[2]]["fn"] += 1
        for index, span in enumerate(pred):
            if index not in used_pred:
                totals["fp"] += 1
                by_type[span[2]]["fp"] += 1

    def finish(counts: dict[str, int]) -> dict[str, float | int]:
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {**counts, "precision": precision, "recall": recall, "f1": f1}

    return {
        "partial_iou_threshold": 0.5,
        "overall": finish(totals),
        "by_type": {span_type: finish(counts) for span_type, counts in sorted(by_type.items())},
    }


def evaluate(model: Any, loader: Any, rows: Sequence[dict[str, Any]], device: Any, id2label: dict[int, str]) -> dict[str, Any]:
    import torch

    model.eval()
    losses: list[float] = []
    gold_by_text: dict[tuple[str, str], set[tuple[int, int, str]]] = defaultdict(set)
    pred_by_text: dict[tuple[str, str], set[tuple[int, int, str]]] = defaultdict(set)
    with torch.no_grad():
        for batch in loader:
            indexes = batch.pop("example_index")
            model_batch = {key: value.to(device) for key, value in batch.items()}
            output = model(**model_batch)
            losses.append(float(output.loss.detach().cpu()))
            predictions = output.logits.argmax(dim=-1).detach().cpu().tolist()
            gold_labels = batch["labels"].tolist()
            for batch_index, row_index in enumerate(indexes):
                row = rows[row_index]
                key = (str(row["post_id"]), str(row["text_id"]))
                for span in row.get("spans", []):
                    gold_by_text[key].add((int(span["start"]), int(span["end"]), str(span["type"])))
                valid_predictions = [
                    -100 if gold_id == -100 else pred_id
                    for pred_id, gold_id in zip(predictions[batch_index], gold_labels[batch_index])
                ]
                pred_by_text[key].update(
                    decode_token_spans(row["offset_mapping"], valid_predictions, id2label)
                )
    metrics = score_span_sets(gold_by_text, pred_by_text)
    metrics["loss"] = sum(losses) / len(losses) if losses else 0.0
    metrics["texts"] = len(gold_by_text | pred_by_text)
    return metrics


def latest_checkpoint(output_dir: Path) -> Path:
    candidates: list[tuple[int, Path]] = []
    for path in output_dir.glob("checkpoint-epoch-*"):
        try:
            candidates.append((int(path.name.rsplit("-", 1)[1]), path))
        except ValueError:
            continue
    if not candidates:
        raise TrainError(f"재개할 체크포인트가 없습니다: {output_dir}")
    return max(candidates)[1]


def save_checkpoint(
    *, model: Any, tokenizer: Any, optimizer: Any, output_dir: Path, epoch: int, global_step: int, metrics: dict[str, Any]
) -> Path:
    import torch

    checkpoint = output_dir / f"checkpoint-epoch-{epoch}"
    checkpoint.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(checkpoint)
    tokenizer.save_pretrained(checkpoint)
    torch.save(optimizer.state_dict(), checkpoint / "optimizer.pt")
    state = {"completed_epochs": epoch, "global_step": global_step, "eval": metrics}
    (checkpoint / "trainer_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return checkpoint


def set_seed(seed: int) -> None:
    import torch

    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=3e-5)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument(
        "--o-weight",
        type=float,
        default=1.0,
        help="CrossEntropyLoss에서 O 라벨의 가중치 (과도한 O 쏠림 진단 시 0.01 등으로 낮춤)",
    )
    parser.add_argument("--eval-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=20260911)
    parser.add_argument("--overfit", type=int, default=0, metavar="N")
    parser.add_argument("--resume-from-checkpoint", nargs="?", const="latest")
    parser.add_argument("--fp16", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.epochs < 1 or args.batch_size < 1 or args.overfit < 0:
        raise TrainError("epochs와 batch-size는 1 이상, overfit은 0 이상이어야 합니다.")
    if not 0 < args.eval_ratio < 1:
        raise TrainError("--eval-ratio는 0과 1 사이여야 합니다.")
    if not 0 < args.o_weight <= 1:
        raise TrainError("--o-weight는 0보다 크고 1 이하여야 합니다.")

    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    labels, label2id = load_labels(args.labels)
    id2label = {index: label for index, label in enumerate(labels)}
    rows = read_jsonl(args.data)
    validate_examples(rows, len(labels))
    train_rows, eval_rows, split_name = split_examples(
        rows, eval_ratio=args.eval_ratio, seed=args.seed, overfit=args.overfit
    )
    set_seed(args.seed)

    checkpoint: Path | None = None
    if args.resume_from_checkpoint:
        checkpoint = (
            latest_checkpoint(args.output_dir)
            if args.resume_from_checkpoint == "latest"
            else Path(args.resume_from_checkpoint)
        )
        if not checkpoint.is_dir():
            raise TrainError(f"체크포인트 디렉터리가 없습니다: {checkpoint}")
    model_source = str(checkpoint) if checkpoint else args.model
    tokenizer = AutoTokenizer.from_pretrained(model_source, use_fast=True)
    model = AutoModelForTokenClassification.from_pretrained(
        model_source,
        num_labels=len(labels),
        label2id=label2id,
        id2label=id2label,
        ignore_mismatched_sizes=checkpoint is None,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if args.fp16 and device.type != "cuda":
        raise TrainError("--fp16은 CUDA에서만 사용할 수 있습니다.")
    model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    class_weights = torch.ones(len(labels), dtype=torch.float32, device=device)
    class_weights[label2id["O"]] = args.o_weight
    start_epoch = 0
    global_step = 0
    if checkpoint:
        optimizer_path = checkpoint / "optimizer.pt"
        state_path = checkpoint / "trainer_state.json"
        if not optimizer_path.is_file() or not state_path.is_file():
            raise TrainError(f"재개 상태 파일이 불완전합니다: {checkpoint}")
        optimizer.load_state_dict(torch.load(optimizer_path, map_location=device, weights_only=True))
        state = json.loads(state_path.read_text(encoding="utf-8"))
        start_epoch = int(state.get("completed_epochs", 0))
        global_step = int(state.get("global_step", 0))

    collator = make_collator(tokenizer)
    generator = torch.Generator().manual_seed(args.seed)
    train_loader = DataLoader(
        BioDataset(train_rows), batch_size=args.batch_size, shuffle=True, collate_fn=collator,
        num_workers=0, generator=generator,
    )
    eval_loader = DataLoader(
        BioDataset(eval_rows), batch_size=args.batch_size, shuffle=False, collate_fn=collator,
        num_workers=0,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_started = time.time()
    print(
        f"device={device} · split={split_name} · train={len(train_rows)} · eval={len(eval_rows)} · "
        f"batch={args.batch_size} · epochs={args.epochs} · start_epoch={start_epoch} · "
        f"o_weight={args.o_weight}"
    )
    if device.type == "cuda":
        print(f"gpu={torch.cuda.get_device_name(0)}")

    scaler = torch.amp.GradScaler("cuda", enabled=args.fp16)
    final_metrics: dict[str, Any] = {}
    for epoch in range(start_epoch + 1, start_epoch + args.epochs + 1):
        model.train()
        loss_sum = 0.0
        for step, batch in enumerate(train_loader, 1):
            batch.pop("example_index")
            model_batch = {key: value.to(device) for key, value in batch.items()}
            target_labels = model_batch.pop("labels")
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=args.fp16):
                output = model(**model_batch)
                # BIO 데이터는 O가 99% 안팎이라 기본 손실만 쓰면 모든 토큰을
                # O로 예측해도 loss가 빠르게 내려간다. O 가중치만 낮춰 양성
                # 토큰의 학습 신호가 묻히지 않게 한다.
                loss = torch.nn.functional.cross_entropy(
                    output.logits.float().reshape(-1, len(labels)),
                    target_labels.reshape(-1),
                    weight=class_weights,
                    ignore_index=-100,
                )
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            global_step += 1
            loss_sum += float(loss.detach().cpu())
            if step == 1 or step % 10 == 0 or step == len(train_loader):
                print(f"epoch {epoch} step {step}/{len(train_loader)} loss={loss_sum / step:.6f}")

        final_metrics = evaluate(model, eval_loader, eval_rows, device, id2label)
        final_metrics.update(
            {
                "epoch": epoch,
                "train_loss": loss_sum / len(train_loader),
                "elapsed_seconds": round(time.time() - run_started, 2),
                "device": str(device),
                "model": args.model,
                "split": split_name,
                "seed": args.seed,
                "o_weight": args.o_weight,
            }
        )
        overall = final_metrics["overall"]
        print(
            f"eval partial span F1={overall['f1']:.4f} "
            f"(P={overall['precision']:.4f}, R={overall['recall']:.4f}, "
            f"TP={overall['tp']}, FP={overall['fp']}, FN={overall['fn']})"
        )
        # 과적합 진단은 중간 epoch 19개를 보관할 이유가 없고 체크포인트 하나가
        # 수백 MB라 마지막 결과만 저장한다. 실제 학습은 매 epoch 저장한다.
        if not args.overfit or epoch == start_epoch + args.epochs:
            checkpoint_path = save_checkpoint(
                model=model,
                tokenizer=tokenizer,
                optimizer=optimizer,
                output_dir=args.output_dir,
                epoch=epoch,
                global_step=global_step,
                metrics=final_metrics,
            )
            print(f"checkpoint={checkpoint_path}")

    summary = {
        "completed": True,
        "train_examples": len(train_rows),
        "eval_examples": len(eval_rows),
        "requested_epochs": args.epochs,
        "resumed_from": str(checkpoint) if checkpoint else None,
        "metrics": final_metrics,
    }
    (args.output_dir / "run_metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TrainError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
