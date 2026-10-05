#!/usr/bin/env python3
"""검수 골드의 문자 스팬을 KoELECTRA용 BIO 데이터로 변환한다.

텍스트 채널을 토큰 창으로 나누고 BIO 정렬·왕복 검증 결과를 저장한다.
정본 입력은 ``data/corpus/v0/gold/*_spans.jsonl`` 이다. ``detect/``의
교사 원본과 ``blind/``의 최종 평가는 읽지 않는다. blind·IAA 배정 글은
``scripts/split_train_test.py``가 만든 split을 기준으로 학습에서 제외한다.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence


TYPES = [
    "AGE",
    "SEX",
    "LOC_ADMIN",
    "LOC_FACILITY",
    "REL_HOME",
    "REL_WORK",
    "JOB",
    "FAM",
    "COMMUTE",
    "INCOME",
]
LABELS = ["O"] + [f"{prefix}-{span_type}" for span_type in TYPES for prefix in ("B", "I")]
LABEL2ID = {label: index for index, label in enumerate(LABELS)}
ID2LABEL = {index: label for label, index in LABEL2ID.items()}

DEFAULT_GOLD_DIR = Path("data/corpus/v0/gold")
DEFAULT_SPLIT_DIR = Path("data/corpus/v0/splits")
DEFAULT_OUT_DIR = Path("experiments/exp06-finetune/runs/bio")
DEFAULT_TOKENIZER = "monologg/koelectra-base-v3-discriminator"


class DataError(ValueError):
    """학습을 중단해야 하는 입력 데이터 오류."""


def read_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DataError(f"JSON 오류: {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise DataError(f"객체가 아닌 JSON: {path}:{line_number}")
            yield line_number, value


def load_split_ids(split_dir: Path) -> tuple[set[str], set[str]]:
    paths = {name: split_dir / f"{name}.jsonl" for name in ("train", "test")}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise DataError(
            "분할 파일이 없다: "
            + ", ".join(missing)
            + "\n먼저 `python scripts/split_train_test.py`를 실행한다."
        )

    result: dict[str, set[str]] = {}
    for split, path in paths.items():
        ids: set[str] = set()
        for line_number, record in read_jsonl(path):
            post_id = record.get("post_id")
            if not isinstance(post_id, str) or not post_id:
                raise DataError(f"post_id가 없다: {path}:{line_number}")
            if post_id in ids:
                raise DataError(f"중복 post_id: {path}:{line_number}: {post_id}")
            ids.add(post_id)
        result[split] = ids

    overlap = result["train"] & result["test"]
    if overlap:
        raise DataError(f"train/test 누수 {len(overlap)}건: {sorted(overlap)[:5]}")
    return result["train"], result["test"]


def channel_sort_key(text_id: str) -> tuple[int, int | str]:
    if text_id == "title":
        return (0, 0)
    if text_id == "body":
        return (1, 0)
    if text_id.startswith("photo_caption:"):
        suffix = text_id.split(":", 1)[1]
        if suffix.isdigit():
            return (2, int(suffix))
        return (2, suffix)
    if text_id == "profile_bio":
        return (3, 0)
    return (4, text_id)


def validate_channel(
    *, source: str, text_id: str, text: str, spans: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    checked: list[dict[str, Any]] = []
    for span in spans:
        required = {"span_id", "text_id", "start", "end", "text", "type", "level", "subject"}
        missing = required - span.keys()
        if missing:
            raise DataError(f"{source}: 스팬 필드 누락 {sorted(missing)}: {span}")
        if span["text_id"] != text_id:
            raise DataError(f"{source}: 잘못 묶인 text_id: {span['span_id']}")
        start, end = span["start"], span["end"]
        if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(text)):
            raise DataError(f"{source}: 범위 오류: {span}")
        if text[start:end] != span["text"]:
            raise DataError(
                f"{source}: offset 불일치 {span['span_id']}: "
                f"{text[start:end]!r} != {span['text']!r}"
            )
        if span["type"] not in TYPES:
            raise DataError(f"{source}: 알 수 없는 type {span['type']}: {span['span_id']}")
        if span["level"] not in {"explicit", "implicit", "inferential"}:
            raise DataError(f"{source}: 알 수 없는 level {span['level']}: {span['span_id']}")
        if span["subject"] not in {"self", "other", "unknown"}:
            raise DataError(f"{source}: 알 수 없는 subject {span['subject']}: {span['span_id']}")
        checked.append(dict(span))

    checked.sort(key=lambda span: (span["start"], span["end"], span["span_id"]))
    for left, right in zip(checked, checked[1:]):
        if right["start"] < left["end"]:
            raise DataError(
                f"{source}: 겹치는 스팬: {left['span_id']} {left['start']}:{left['end']} / "
                f"{right['span_id']} {right['start']}:{right['end']}"
            )
    return checked


def load_training_channels(
    gold_dir: Path,
    train_ids: set[str],
    test_ids: set[str],
    *,
    include_unreviewed: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    files = sorted(gold_dir.glob("*_spans.jsonl"))
    if not files:
        raise DataError(f"검수 정본 파일이 없다: {gold_dir}/*_spans.jsonl")

    channels: list[dict[str, Any]] = []
    seen_posts: set[str] = set()
    stats: collections.Counter[str] = collections.Counter({
        "reviewed_records_accepted": 0,
        "teacher_records_accepted": 0,
        "teacher_records_invalid": 0,
    })

    for path in files:
        for line_number, record in read_jsonl(path):
            if "schema_version" in record and "post_id" not in record:
                continue
            stats["records_total"] += 1
            reviewed = record.get("reviewed") is True
            if not reviewed:
                stats["records_unreviewed"] += 1
                if not include_unreviewed:
                    continue

            post_id = record.get("post_id")
            persona_id = record.get("persona_id")
            texts = record.get("texts")
            spans = record.get("spans")
            source = f"{path}:{line_number}"
            if not isinstance(post_id, str) or not isinstance(persona_id, str):
                if not reviewed:
                    stats["teacher_records_invalid"] += 1
                    continue
                raise DataError(f"{source}: post_id/persona_id가 없다")
            if post_id in seen_posts:
                raise DataError(f"검수 정본의 중복 post_id: {post_id}")
            seen_posts.add(post_id)
            if not isinstance(texts, dict) or not isinstance(spans, list):
                if not reviewed:
                    stats["teacher_records_invalid"] += 1
                    continue
                raise DataError(f"{source}: texts 또는 spans 형식 오류")

            if post_id in test_ids:
                stats["test_records_excluded"] += 1
                stats["test_spans_excluded"] += len(spans)
                continue
            if post_id not in train_ids:
                # 향후 profile 레코드는 글 단위 split에 없으므로 별도 합의 전 학습하지 않는다.
                raise DataError(f"{source}: train/test 어디에도 없는 post_id: {post_id}")

            record_channels: list[dict[str, Any]] = []
            try:
                grouped: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
                for span in spans:
                    if not isinstance(span, dict) or not isinstance(span.get("text_id"), str):
                        raise DataError(f"{source}: 스팬 또는 text_id 형식 오류: {span}")
                    grouped[span["text_id"]].append(span)
                unknown_channels = set(grouped) - set(texts)
                if unknown_channels:
                    raise DataError(f"{source}: texts에 없는 채널: {sorted(unknown_channels)}")

                for text_id in sorted(texts, key=channel_sort_key):
                    text = texts[text_id]
                    if not isinstance(text_id, str) or not isinstance(text, str):
                        raise DataError(f"{source}: 텍스트 채널 형식 오류: {text_id!r}")
                    channel_spans = validate_channel(
                        source=source, text_id=text_id, text=text, spans=grouped.get(text_id, [])
                    )
                    record_channels.append(
                        {
                            "post_id": post_id,
                            "persona_id": persona_id,
                            "reviewed": reviewed,
                            "text_id": text_id,
                            "text": text,
                            "spans": channel_spans,
                        }
                    )
            except DataError:
                if reviewed:
                    raise
                stats["teacher_records_invalid"] += 1
                continue
            channels.extend(record_channels)
            stats["channels"] += len(record_channels)
            stats["spans"] += sum(len(channel["spans"]) for channel in record_channels)
            stats["train_records"] += 1
            stats["reviewed_records_accepted" if reviewed else "teacher_records_accepted"] += 1

    return channels, dict(stats)


def load_extra_channels(
    extra_dirs: Sequence[Path],
    train_ids: set[str],
    test_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """학습 전용 추가 데이터(예: exp19 변이 글 · #310) — 분할 파일에 없는 글을 학습에만 더한다.

    코퍼스 v0 의 분할(train/test)은 그대로 두고, 추가 글은 test 와 섞이지 않게 **post_id 가 기존 분할에 없어야** 한다.
    형식이 깨진 레코드는 교사 라벨처럼 건너뛰고 센다.
    """
    channels: list[dict[str, Any]] = []
    stats: collections.Counter[str] = collections.Counter()
    seen: set[str] = set()
    for directory in extra_dirs:
        files = sorted(Path(directory).glob("*_spans.jsonl"))
        if not files:
            raise DataError(f"추가 데이터가 없다: {directory}/*_spans.jsonl")
        for path in files:
            for line_number, record in read_jsonl(path):
                if "schema_version" in record and "post_id" not in record:
                    continue
                source = f"{path}:{line_number}"
                post_id, persona_id = record.get("post_id"), record.get("persona_id")
                texts, spans = record.get("texts"), record.get("spans")
                if post_id in train_ids or post_id in test_ids:
                    raise DataError(f"{source}: 추가 데이터의 post_id 가 기존 분할과 겹친다: {post_id}")
                if post_id in seen:
                    raise DataError(f"{source}: 추가 데이터의 중복 post_id: {post_id}")
                seen.add(post_id)
                if not isinstance(post_id, str) or not isinstance(persona_id, str) \
                        or not isinstance(texts, dict) or not isinstance(spans, list):
                    stats["augment_records_invalid"] += 1
                    continue
                try:
                    grouped: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
                    for span in spans:
                        grouped[span["text_id"]].append(span)
                    if set(grouped) - set(texts):
                        raise DataError(f"{source}: texts에 없는 채널")
                    record_channels = [
                        {"post_id": post_id, "persona_id": persona_id, "reviewed": False, "text_id": text_id,
                         "text": texts[text_id],
                         "spans": validate_channel(source=source, text_id=text_id, text=texts[text_id],
                                                   spans=grouped.get(text_id, []))}
                        for text_id in sorted(texts, key=channel_sort_key)
                    ]
                except (DataError, KeyError, TypeError):
                    stats["augment_records_invalid"] += 1
                    continue
                channels.extend(record_channels)
                stats["augment_records_accepted"] += 1
                stats["augment_spans"] += sum(len(c["spans"]) for c in record_channels)
    return channels, dict(stats)


def align_bio(
    offsets: Sequence[Sequence[int]], spans: Sequence[dict[str, Any]]
) -> tuple[list[int], set[str]]:
    """한 토큰 창의 offset에 BIO id를 붙이고 완전히 포함된 스팬 id를 돌려준다."""
    labels = [-100 if int(start) == int(end) else LABEL2ID["O"] for start, end in offsets]
    covered: set[str] = set()

    content_offsets = [(int(start), int(end)) for start, end in offsets if int(start) != int(end)]
    if not content_offsets:
        return labels, covered
    window_start = min(start for start, _ in content_offsets)
    window_end = max(end for _, end in content_offsets)

    for span in spans:
        # 창 경계에 잘린 스팬을 불완전한 BIO 정답으로 만들지 않는다.
        if span["start"] < window_start or span["end"] > window_end:
            continue
        token_indexes = [
            index
            for index, (start, end) in enumerate(offsets)
            if int(start) != int(end) and int(start) < span["end"] and int(end) > span["start"]
        ]
        if not token_indexes:
            continue
        for position, index in enumerate(token_indexes):
            if labels[index] != LABEL2ID["O"]:
                raise DataError(f"한 토큰에 스팬이 겹친다: {span['span_id']}")
            prefix = "B" if position == 0 else "I"
            labels[index] = LABEL2ID[f"{prefix}-{span['type']}"]
        covered.add(span["span_id"])
    return labels, covered


def decode_bio(
    text: str, offsets: Sequence[Sequence[int]], labels: Sequence[int]
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for (raw_start, raw_end), label_id in zip(offsets, labels):
        start, end = int(raw_start), int(raw_end)
        if start == end or label_id == -100:
            continue
        tag = ID2LABEL[int(label_id)]
        prefix, _, span_type = tag.partition("-")
        if tag == "O":
            prefix = "O"
        if prefix == "B" or (
            prefix == "I" and (current is None or current["type"] != span_type)
        ):
            if current is not None:
                spans.append(current)
            current = {"start": start, "end": end, "type": span_type}
        elif prefix == "I" and current is not None and current["type"] == span_type:
            current["end"] = end
        else:
            if current is not None:
                spans.append(current)
            current = None
    if current is not None:
        spans.append(current)
    for span in spans:
        span["text"] = text[span["start"] : span["end"]]
    return spans


def _batch_windows(encoded: Any) -> list[dict[str, Any]]:
    data = dict(encoded)
    input_ids = data.get("input_ids")
    if not isinstance(input_ids, list) or not input_ids:
        raise DataError("토크나이저가 input_ids를 반환하지 않았다")
    if isinstance(input_ids[0], int):
        return [data]
    count = len(input_ids)
    windows: list[dict[str, Any]] = []
    for index in range(count):
        window = {}
        for key, value in data.items():
            if key == "overflow_to_sample_mapping":
                continue
            if isinstance(value, list) and len(value) == count:
                window[key] = value[index]
        windows.append(window)
    return windows


def encode_channels(
    channels: Sequence[dict[str, Any]], tokenizer: Any, *, max_length: int, stride: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    all_span_ids = {span["span_id"] for channel in channels for span in channel["spans"]}
    covered_span_ids: set[str] = set()
    roundtrip: dict[str, str] = {}
    boundary_deltas: dict[str, int] = {}

    for channel in channels:
        encoded = tokenizer(
            channel["text"],
            truncation=True,
            max_length=max_length,
            stride=stride,
            return_offsets_mapping=True,
            return_overflowing_tokens=True,
            padding=False,
        )
        windows = _batch_windows(encoded)
        for window_index, window in enumerate(windows):
            offsets = window.get("offset_mapping")
            if offsets is None:
                raise DataError("fast tokenizer의 offset_mapping이 필요하다")
            labels, covered = align_bio(offsets, channel["spans"])
            covered_span_ids.update(covered)
            decoded = decode_bio(channel["text"], offsets, labels)

            for gold in channel["spans"]:
                if gold["span_id"] not in covered:
                    continue
                matches = [
                    pred
                    for pred in decoded
                    if pred["type"] == gold["type"]
                    and pred["start"] < gold["end"]
                    and pred["end"] > gold["start"]
                ]
                if not matches:
                    roundtrip.setdefault(gold["span_id"], "bad")
                    continue
                pred = max(
                    matches,
                    key=lambda item: min(item["end"], gold["end"]) - max(item["start"], gold["start"]),
                )
                if pred["start"] == gold["start"] and pred["end"] == gold["end"]:
                    roundtrip[gold["span_id"]] = "exact"
                    boundary_deltas.pop(gold["span_id"], None)
                elif roundtrip.get(gold["span_id"]) != "exact":
                    roundtrip[gold["span_id"]] = "near"
                    delta = abs(pred["start"] - gold["start"]) + abs(
                        pred["end"] - gold["end"]
                    )
                    old_delta = boundary_deltas.get(gold["span_id"])
                    boundary_deltas[gold["span_id"]] = (
                        delta if old_delta is None else min(delta, old_delta)
                    )

            example = {
                "example_id": f"{channel['post_id']}:{channel['text_id']}:{window_index}",
                "post_id": channel["post_id"],
                "persona_id": channel["persona_id"],
                "reviewed": channel.get("reviewed", True),
                "text_id": channel["text_id"],
                "window_index": window_index,
                "text": channel["text"],
                "spans": channel["spans"],
                "offset_mapping": [[int(start), int(end)] for start, end in offsets],
                "labels": labels,
            }
            for key in ("input_ids", "attention_mask", "token_type_ids"):
                if key in window:
                    example[key] = [int(value) for value in window[key]]
            examples.append(example)

    lost = all_span_ids - covered_span_ids
    for span_id in lost:
        roundtrip[span_id] = "bad"
    counts = collections.Counter(roundtrip.values())
    total = len(all_span_ids)
    metrics = {
        "channels": len(channels),
        "examples": len(examples),
        "spans": total,
        "roundtrip": {
            "exact": counts["exact"],
            "near": counts["near"],
            "bad": counts["bad"],
            "bad_rate": counts["bad"] / total if total else 0.0,
            "mean_near_boundary_delta": (
                sum(boundary_deltas.values()) / len(boundary_deltas)
                if boundary_deltas
                else 0.0
            ),
        },
        "lost_span_ids": sorted(lost),
    }
    return examples, metrics


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD_DIR)
    parser.add_argument("--split-dir", type=Path, default=DEFAULT_SPLIT_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--tokenizer", default=DEFAULT_TOKENIZER)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--stride", type=int, default=64)
    parser.add_argument("--validate-only", action="store_true", help="토크나이저 없이 정본·분할·offset만 검사")
    parser.add_argument("--include-unreviewed", action="store_true",
                        help="train split의 미검수 교사 라벨도 학습에 포함한다")
    parser.add_argument("--extra-gold-dir", type=Path, action="append", default=[],
                        help="학습 전용 추가 데이터 폴더(*_spans.jsonl) — 분할에 없는 글을 학습에만 더한다 (여러 번 가능)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.max_length < 8:
        raise DataError("--max-length는 8 이상이어야 한다")
    if not 0 <= args.stride < args.max_length:
        raise DataError("--stride는 0 이상 max-length 미만이어야 한다")

    train_ids, test_ids = load_split_ids(args.split_dir)
    channels, source_metrics = load_training_channels(
        args.gold_dir, train_ids, test_ids, include_unreviewed=args.include_unreviewed
    )
    if args.extra_gold_dir:
        extra_channels, extra_metrics = load_extra_channels(args.extra_gold_dir, train_ids, test_ids)
        channels.extend(extra_channels)
        source_metrics = {**source_metrics, **extra_metrics}
        print(f"추가 데이터: {extra_metrics.get('augment_records_accepted', 0)}편 / "
              f"{extra_metrics.get('augment_spans', 0)}스팬 · 형식 오류 제외 {extra_metrics.get('augment_records_invalid', 0)}편")
    print(
        "학습 원본: "
        f"학습 {source_metrics.get('train_records', 0)}편 / {source_metrics.get('spans', 0)}스팬 / "
        f"{source_metrics.get('channels', 0)}채널 · "
        f"test 격리 {source_metrics.get('test_records_excluded', 0)}편 / "
        f"{source_metrics.get('test_spans_excluded', 0)}스팬"
    )
    print(
        f"검수 {source_metrics.get('reviewed_records_accepted', 0)}편 · "
        f"교사 {source_metrics.get('teacher_records_accepted', 0)}편 · "
        f"교사 형식 오류 제외 {source_metrics.get('teacher_records_invalid', 0)}편"
    )
    if args.validate_only:
        print("정본·분할·offset 검증 통과 (--validate-only)")
        return 0

    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise DataError("transformers가 없다. `pip install -r requirements.txt`로 설치한다.") from exc

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, use_fast=True)
    if not tokenizer.is_fast:
        raise DataError(f"fast tokenizer가 아니다: {args.tokenizer}")
    examples, bio_metrics = encode_channels(
        channels, tokenizer, max_length=args.max_length, stride=args.stride
    )
    metrics = {
        "source": {
            "gold_glob": str(args.gold_dir / "*_spans.jsonl"),
            "teacher_detect_used": False,
            "blind_or_iaa_used_for_training": False,
            "include_unreviewed": args.include_unreviewed,
            "extra_gold_dirs": [str(d) for d in args.extra_gold_dir],
            **source_metrics,
            "reviewed_fraction": (
                source_metrics["reviewed_records_accepted"] / source_metrics["train_records"]
                if source_metrics["train_records"] else 0.0
            ),
            "teacher_fraction": (
                source_metrics["teacher_records_accepted"] / source_metrics["train_records"]
                if source_metrics["train_records"] else 0.0
            ),
        },
        "tokenizer": {
            "id": args.tokenizer,
            "max_length": args.max_length,
            "stride": args.stride,
            "labels": LABELS,
        },
        **bio_metrics,
    }
    bad_rate = metrics["roundtrip"]["bad_rate"]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "train.jsonl", examples)
    metrics["source"]["bio_sha256"] = hashlib.sha256(
        (args.out_dir / "train.jsonl").read_bytes()
    ).hexdigest()
    write_json(args.out_dir / "labels.json", {"labels": LABELS, "label2id": LABEL2ID})
    write_json(args.out_dir / "metrics.json", metrics)
    print(
        f"BIO 저장: {args.out_dir / 'train.jsonl'} ({len(examples)}개 창) · "
        f"왕복 exact {metrics['roundtrip']['exact']} / near {metrics['roundtrip']['near']} / "
        f"bad {metrics['roundtrip']['bad']} ({bad_rate:.1%})"
    )
    if bad_rate >= 0.10:
        print("ERROR: 왕복 bad가 10% 이상이라 학습으로 넘어가지 않는다.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DataError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
