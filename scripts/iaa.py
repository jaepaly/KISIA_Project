#!/usr/bin/env python3
"""두 라벨러의 JSONL 골드셋으로 스팬 IAA를 계산한다.

사용:
    python scripts/iaa.py <annotator-a 경로> <annotator-c 경로>

경로에는 *_spans.jsonl 파일 또는 그 파일들이 든 디렉터리를 지정한다.
두 입력에 공통으로 존재하며 reviewed=true인 글만 비교한다.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


LEVELS = ("explicit", "implicit", "inferential")


@dataclass(frozen=True)
class Span:
    text_id: str
    start: int
    end: int
    type: str
    level: str
    subject: str


def jsonl_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.rglob("*_spans.jsonl"))
    raise FileNotFoundError(path)


def load_records(path: Path) -> dict[str, list[Span]]:
    records: dict[str, list[Span]] = {}
    for file in jsonl_files(path):
        lines = [line for line in file.read_text(encoding="utf-8-sig").splitlines()
                 if line.strip()]
        for line_number, line in enumerate(lines[1:], 2):
            record = json.loads(line)
            if not record.get("reviewed", False):
                continue
            post_id = record.get("post_id")
            if not post_id:  # profile 레코드는 20편 IAA에서 제외한다.
                continue
            if post_id in records:
                raise ValueError(f"{post_id} 중복: {file}:{line_number}")
            records[post_id] = [
                Span(
                    text_id=span["text_id"],
                    start=span["start"],
                    end=span["end"],
                    type=span["type"],
                    level=span["level"],
                    subject=span["subject"],
                )
                for span in record.get("spans", [])
            ]
    return records


def iou(left: Span, right: Span) -> float:
    if left.text_id != right.text_id:
        return 0.0
    intersection = max(0, min(left.end, right.end) - max(left.start, right.start))
    if not intersection:
        return 0.0
    union = max(left.end, right.end) - min(left.start, right.start)
    return intersection / union


def maximum_matching(
    left: list[Span],
    right: list[Span],
    compatible: Callable[[Span, Span], bool],
) -> list[tuple[int, int]]:
    """호환 간선에서 최대 cardinality 1:1 매칭을 구한다."""
    adjacency = [
        sorted(
            (j for j, candidate in enumerate(right) if compatible(span, candidate)),
            key=lambda j: iou(span, right[j]),
            reverse=True,
        )
        for span in left
    ]
    right_owner: dict[int, int] = {}

    def augment(i: int, seen: set[int]) -> bool:
        for j in adjacency[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in right_owner or augment(right_owner[j], seen):
                right_owner[j] = i
                return True
        return False

    for i in range(len(left)):
        augment(i, set())
    return sorted((i, j) for j, i in right_owner.items())


def f1_counts(left: list[Span], right: list[Span], exact: bool) -> tuple[int, int, int]:
    def compatible(a: Span, b: Span) -> bool:
        if a.type != b.type or a.text_id != b.text_id:
            return False
        if exact:
            return a.start == b.start and a.end == b.end
        return iou(a, b) >= 0.5

    tp = len(maximum_matching(left, right, compatible))
    return tp, len(left) - tp, len(right) - tp


def score(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else (1.0 if not fn else 0.0)
    recall = tp / (tp + fn) if tp + fn else (1.0 if not fp else 0.0)
    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall else 0.0)
    return precision, recall, f1


def flatten(records: dict[str, list[Span]], post_ids: list[str], level: str | None) -> list[Span]:
    result: list[Span] = []
    for post_id in post_ids:
        for span in records[post_id]:
            if level is None or span.level == level:
                # 서로 다른 글의 같은 offset이 매칭되지 않도록 text_id에 글 ID를 붙인다.
                result.append(Span(
                    text_id=f"{post_id}:{span.text_id}",
                    start=span.start,
                    end=span.end,
                    type=span.type,
                    level=span.level,
                    subject=span.subject,
                ))
    return result


def agreement(left: list[Span], right: list[Span]) -> tuple[int, int, int]:
    pairs = maximum_matching(
        left,
        right,
        lambda a, b: a.type == b.type and a.text_id == b.text_id and iou(a, b) >= 0.5,
    )
    level_same = sum(left[i].level == right[j].level for i, j in pairs)
    subject_same = sum(left[i].subject == right[j].subject for i, j in pairs)
    return level_same, subject_same, len(pairs)


def pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotator_a", type=Path)
    parser.add_argument("annotator_c", type=Path)
    parser.add_argument("--expect-posts", type=int, default=20)
    args = parser.parse_args()

    a_records = load_records(args.annotator_a)
    c_records = load_records(args.annotator_c)
    a_only = sorted(set(a_records) - set(c_records))
    c_only = sorted(set(c_records) - set(a_records))
    common = sorted(set(a_records) & set(c_records))

    if a_only or c_only:
        if a_only:
            print("A에만 있는 글:", ", ".join(a_only))
        if c_only:
            print("C에만 있는 글:", ", ".join(c_only))
        print()
    if len(common) != args.expect_posts:
        print(f"오류: 공통 reviewed 글 {len(common)}편 (기대 {args.expect_posts}편)")
        return 2

    print(f"IAA — 공통 reviewed 글 {len(common)}편")
    print("기준: partial=type 일치 + 문자 IoU>=0.5, 1:1 최대 매칭")
    print()
    print(f"{'level':<13} {'A':>4} {'C':>4} {'TP':>4} {'P':>8} {'R':>8} {'partial F1':>11} {'exact F1':>10}")

    for level in (*LEVELS, None):
        left = flatten(a_records, common, level)
        right = flatten(c_records, common, level)
        tp, fp, fn = f1_counts(left, right, exact=False)
        precision, recall, partial_f1 = score(tp, fp, fn)
        etp, efp, efn = f1_counts(left, right, exact=True)
        exact_f1 = score(etp, efp, efn)[2]
        label = level or "overall"
        print(f"{label:<13} {len(left):>4} {len(right):>4} {tp:>4} "
              f"{pct(precision):>8} {pct(recall):>8} {pct(partial_f1):>11} {pct(exact_f1):>10}")

    left = flatten(a_records, common, None)
    right = flatten(c_records, common, None)
    level_same, subject_same, matched = agreement(left, right)
    print()
    if matched:
        print(f"matched span level 일치:   {level_same}/{matched} ({pct(level_same / matched)})")
        print(f"matched span subject 일치: {subject_same}/{matched} ({pct(subject_same / matched)})")
    else:
        print("matched span이 없어 level·subject 일치율을 계산할 수 없다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
