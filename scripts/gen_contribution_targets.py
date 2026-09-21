"""인물별 LOO 기여도 증류 타깃을 생성한다.

실행:
    python scripts/gen_contribution_targets.py \
      --gold data/corpus/v0/gold \
      --personas data/corpus/v0/personas \
      --out data/corpus/v0/gold/contribution
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from kopl.c2_specificity import build_conditions, risk_total
from kopl.c3_contribution.loo import leave_one_out


def user_ref_for(persona_id: str) -> str:
    """seed_sns.py와 같은 결정적 비식별 사용자 참조값을 만든다."""
    digest = hashlib.sha256(persona_id.encode("utf-8")).hexdigest()[:12]
    return f"u_{digest}"


def _read_gold_file(
    path: Path,
    by_post: dict[str, list[dict[str, Any]]],
) -> None:
    if not path.exists():
        return

    lines = path.read_text(encoding="utf-8-sig").splitlines()
    for line_number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        record = json.loads(line)
        if "reviewed" in record and not record["reviewed"]:
            continue

        post_id = record.get("post_id")
        spans = record.get("spans", [])
        if not isinstance(post_id, str) or not post_id:
            raise ValueError(f"{path}:{line_number}: post_id가 올바르지 않습니다.")
        if not isinstance(spans, list):
            raise TypeError(f"{path}:{line_number}: spans는 배열이어야 합니다.")
        by_post.setdefault(post_id, []).extend(spans)


def load_spans(
    gold: Path,
    persona_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """최상위 reviewed 골드와 blind 골드를 게시글별로 합친다."""
    by_post: dict[str, list[dict[str, Any]]] = {}
    paths = (
        gold / f"{persona_id}_spans.jsonl",
        gold / "blind" / f"{persona_id}_spans.jsonl",
    )
    for path in paths:
        _read_gold_file(path, by_post)
    return by_post


def build_evidence_indexes(
    spans_by_post: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, list[str]], dict[str, list[dict[str, str]]]]:
    """LOO 계약의 clue_index와 span_index를 골드 스팬에서 만든다."""
    clue_index: dict[str, list[str]] = {}
    span_index: dict[str, list[dict[str, str]]] = {}

    for post_id in sorted(spans_by_post):
        clue_ids: list[str] = []
        refs: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for span in spans_by_post[post_id]:
            span_id = span.get("span_id")
            text_id = span.get("text_id")
            if not isinstance(span_id, str) or not span_id:
                raise ValueError(f"{post_id}: span_id가 올바르지 않습니다.")
            if not isinstance(text_id, str) or not text_id:
                raise ValueError(f"{post_id}: text_id가 올바르지 않습니다.")
            if span_id in seen_ids:
                raise ValueError(f"{post_id}: span_id가 중복됩니다: {span_id}")
            seen_ids.add(span_id)
            clue_ids.append(span_id)
            refs.append({"span_id": span_id, "text_id": text_id})
        clue_index[post_id] = clue_ids
        span_index[post_id] = refs

    return clue_index, span_index


def generate_target(
    persona_id: str,
    spans_by_post: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """인물 한 명의 골드 스팬으로 contribution 계약 객체를 만든다."""
    post_ids = tuple(sorted(spans_by_post))
    if not post_ids:
        raise ValueError(f"{persona_id}: reviewed 골드 게시글이 없습니다.")

    def risk_fn(selected: tuple[str, ...]) -> float:
        selected_spans = {
            post_id: spans_by_post[post_id]
            for post_id in selected
        }
        return risk_total(build_conditions(selected_spans))

    clue_index, span_index = build_evidence_indexes(spans_by_post)
    return leave_one_out(
        user_ref=user_ref_for(persona_id),
        post_ids=post_ids,
        risk_fn=risk_fn,
        clue_index=clue_index,
        span_index=span_index,
    )


def generate_targets(
    gold: Path,
    personas: Path,
    out: Path,
) -> tuple[int, list[str]]:
    """골드가 있는 모든 인물의 타깃 파일을 쓰고 생성 수와 제외 목록을 반환한다."""
    out.mkdir(parents=True, exist_ok=True)
    generated = 0
    skipped: list[str] = []

    for persona_path in sorted(personas.glob("*.json")):
        persona_id = persona_path.stem
        spans_by_post = load_spans(gold, persona_id)
        if not spans_by_post:
            skipped.append(persona_id)
            continue

        result = generate_target(persona_id, spans_by_post)
        destination = out / f"{persona_id}.json"
        destination.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        generated += 1

    return generated, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="인물별 LOO 기여도 타깃 생성")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--personas", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated, skipped = generate_targets(
        args.gold,
        args.personas,
        args.out,
    )
    print(f"생성 {generated}명 · 골드 없음 {len(skipped)}명")
    if skipped:
        print("건너뜀: " + " ".join(skipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
