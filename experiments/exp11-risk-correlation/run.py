"""위험도 상관 측정 — 누적 윈도우와 C2 위험도 입력 준비."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from kopl.c2_specificity import build_conditions, risk_total  # noqa: E402

WINDOWS = (1, 2, 3, 5, 8, 12, 19)

# 파일럿 결과를 확인하기 전에 고정한 표본.
# 결과를 보고 인물을 교체하지 않는다.
PERSONAS = (
    "B08",
    "D03",
    "E14",
    "B15",
    "D21",
    "A14",
    "E03",
    "B06",
    "B07",
    "A10",
)

POSTS = ROOT / "data" / "corpus" / "v0" / "posts"
GOLD = ROOT / "data" / "corpus" / "v0" / "gold"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """JSONL의 비어 있지 않은 모든 객체 행을 읽는다."""
    rows: list[dict[str, Any]] = []

    for line in path.read_text(
        encoding="utf-8-sig",
    ).splitlines():
        if line.strip():
            rows.append(json.loads(line))

    return rows


def load_posts(persona_id: str) -> list[dict[str, Any]]:
    """게시글을 created_at, post_id 순으로 정렬한다."""
    path = POSTS / f"{persona_id}.jsonl"
    if not path.exists():
        return []

    posts = [
        row
        for row in read_jsonl(path)
        if isinstance(row.get("post_id"), str)
    ]

    return sorted(
        posts,
        key=lambda row: (
            row.get("created_at", ""),
            row["post_id"],
        ),
    )


def load_gold_spans(
    persona_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """최상위 골드의 검수·교사 라벨 스팬을 모두 읽는다.

    상관 측정에서는 교사 LLM이 전체 게시글을 읽으므로 C2도 같은
    글 집합을 보도록 reviewed 여부와 관계없이 최상위 골드를 사용한다.

    blind·IAA·detect 하위 폴더는 포함하지 않는다.
    """
    path = GOLD / f"{persona_id}_spans.jsonl"
    if not path.exists():
        return {}

    spans_by_post: dict[str, list[dict[str, Any]]] = {}

    for row in read_jsonl(path):
        post_id = row.get("post_id")
        if not isinstance(post_id, str):
            continue

        spans = row.get("spans", [])
        if not isinstance(spans, list):
            raise TypeError(
                f"{path}: {post_id} spans가 배열이 아닙니다."
            )

        spans_by_post[post_id] = spans

    return spans_by_post


def select_personas() -> list[str]:
    """파일럿 전에 고정한 인물 10명을 검증해 반환한다."""
    for persona_id in PERSONAS:
        posts = load_posts(persona_id)

        if len(posts) < max(WINDOWS):
            raise ValueError(
                f"{persona_id}: 게시글이 {len(posts)}편이라 "
                f"{max(WINDOWS)}편 윈도우를 만들 수 없습니다."
            )

        spans_by_post = load_gold_spans(persona_id)
        if not spans_by_post:
            raise ValueError(
                f"{persona_id}: 최상위 골드가 없습니다."
            )

        post_ids = {
            post["post_id"]
            for post in posts
        }
        missing = post_ids - set(spans_by_post)

        if missing:
            raise ValueError(
                f"{persona_id}: 최상위 골드가 덮지 않는 글 "
                f"{len(missing)}편: {sorted(missing)[:5]}"
            )

    return list(PERSONAS)


def risk_for_posts(
    post_ids: list[str],
    spans_by_post: dict[str, list[dict[str, Any]]],
) -> float:
    """선택한 게시글 집합의 골드 스팬을 C2 위험도로 변환한다."""
    conditions = [
        condition
        for post_id in post_ids
        for condition in build_conditions(
            spans_by_post.get(post_id, []),
            post_id,
        )
    ]

    return round(risk_total(conditions), 2)


def build_windows(
    persona_id: str,
) -> list[dict[str, Any]]:
    """인물 한 명의 7개 누적 윈도우를 생성한다."""
    posts = load_posts(persona_id)
    spans_by_post = load_gold_spans(persona_id)
    rows: list[dict[str, Any]] = []

    for size in WINDOWS:
        selected = posts[:size]
        post_ids = [
            post["post_id"]
            for post in selected
        ]

        rows.append(
            {
                "persona_id": persona_id,
                "window_size": size,
                "post_ids": post_ids,
                "our_risk": risk_for_posts(
                    post_ids,
                    spans_by_post,
                ),
                "llm_correct": None,
            }
        )

    return rows


def main() -> int:
    personas = select_personas()

    windows = [
        row
        for persona_id in personas
        for row in build_windows(persona_id)
    ]

    print("선정 인물:", " ".join(personas))
    print(
        "튜닝 5명:",
        " ".join(personas[:5]),
    )
    print(
        "보고 5명:",
        " ".join(personas[5:]),
    )

    for persona_id in personas:
        risks = [
            row["our_risk"]
            for row in windows
            if row["persona_id"] == persona_id
        ]

        marker = (
            " ⚠ 변화 없음"
            if len(set(risks)) == 1
            else ""
        )

        print(
            f"{persona_id}: {risks}{marker}"
        )

    zero_count = sum(
        row["our_risk"] == 0
        for row in windows
    )
    risks = [
        row["our_risk"]
        for row in windows
    ]

    print(f"누적 윈도우: {len(windows)}개")
    print(
        f"위험도 0: {zero_count}/{len(windows)} "
        f"({zero_count / len(windows):.1%})"
    )
    print(
        "위험도 범위:",
        min(risks),
        "~",
        max(risks),
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())