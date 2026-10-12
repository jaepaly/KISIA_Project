"""#293 B 모델 예측 2종으로 exp11 위험도 민감도를 재계산한다.

원본 ``teacher_all_scored.csv``는 수정하지 않는다. 예측 후보에 #306
``resolve()``로 level/subject를 붙인 뒤 C2 위험도를 계산하고, 모델별
판정표·윈도우·지표를 별도 파일로 저장한다.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

from kopl.c1_span.attributes import resolve  # noqa: E402
from kopl.c2_specificity import build_conditions, risk_total  # noqa: E402

WINDOWS = (1, 2, 3, 5, 8, 12, 19)
PERSONAS = (
    "B08", "D03", "E14", "B15", "D21",
    "A14", "E03", "B06", "B07", "A10",
)
POSTS = ROOT / "data" / "corpus" / "v0" / "posts"
DEFAULT_INPUTS = HERE / "inputs"
DEFAULT_RESULTS = HERE / "results"
DEFAULT_SCORED = DEFAULT_RESULTS / "teacher_all_scored.csv"
PREDICTIONS = {
    "v1": "pred293_v1.jsonl",
    "v1_rules": "pred293_v1_rules.jsonl",
}


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"모듈을 불러올 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def load_posts() -> dict[str, dict[str, Any]]:
    posts: dict[str, dict[str, Any]] = {}
    for persona_id in PERSONAS:
        path = POSTS / f"{persona_id}.jsonl"
        for row in read_jsonl(path):
            post_id = row.get("post_id")
            if isinstance(post_id, str):
                posts[post_id] = row
    return posts


def expected_post_ids(posts: dict[str, dict[str, Any]]) -> list[str]:
    expected: list[str] = []
    for persona_id in PERSONAS:
        selected = sorted(
            (
                post for post in posts.values()
                if post["post_id"].startswith(f"{persona_id}_")
            ),
            key=lambda post: (post.get("created_at", ""), post["post_id"]),
        )[: max(WINDOWS)]
        if len(selected) != max(WINDOWS):
            raise ValueError(
                f"{persona_id}: {max(WINDOWS)}편이 필요하지만 "
                f"{len(selected)}편입니다"
            )
        expected.extend(post["post_id"] for post in selected)
    return expected


def load_predictions(
    path: Path,
    expected_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    rows = read_jsonl(path)
    predictions: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        post_id = row.get("post_id")
        candidates = row.get("candidates")
        if not isinstance(post_id, str) or not isinstance(candidates, list):
            raise ValueError(f"{path}: post_id/candidates 형식 오류")
        if post_id in predictions:
            raise ValueError(f"{path}: 중복 post_id: {post_id}")
        predictions[post_id] = candidates

    expected = set(expected_ids)
    actual = set(predictions)
    if actual != expected:
        raise ValueError(
            f"{path}: 예측 글 집합 불일치 "
            f"(누락={sorted(expected - actual)[:5]}, "
            f"초과={sorted(actual - expected)[:5]})"
        )
    return predictions


def candidates_to_spans(
    post_id: str,
    post: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    resolver: Callable[[dict[str, str], dict[str, Any]], dict[str, str]] = resolve,
) -> list[dict[str, Any]]:
    texts = post.get("texts")
    if not isinstance(texts, dict):
        raise ValueError(f"{post_id}: texts가 객체가 아닙니다")

    spans: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        text_id = candidate.get("text_id")
        start = candidate.get("start")
        end = candidate.get("end")
        span_type = candidate.get("type")
        if (
            not isinstance(text_id, str)
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or not isinstance(span_type, str)
        ):
            raise ValueError(f"{post_id}: 후보 {index} 필드 형식 오류")
        channel_text = texts.get(text_id)
        if not isinstance(channel_text, str):
            raise ValueError(f"{post_id}: 없는 텍스트 채널 {text_id!r}")
        if start < 0 or end <= start or end > len(channel_text):
            raise ValueError(
                f"{post_id}: 후보 {index} 오프셋 범위 오류 "
                f"({text_id} {start}:{end}/{len(channel_text)})"
            )

        text = channel_text[start:end]
        enriched = {
            "text_id": text_id,
            "start": start,
            "end": end,
            "type": span_type,
            "text": text,
        }
        attrs = resolver(texts, enriched)
        spans.append(
            {
                **enriched,
                "span_id": f"{post_id}_pred_{index:03d}",
                "level": attrs["level"],
                "subject": attrs["subject"],
            }
        )
    return spans


def build_window_risks(
    posts: dict[str, dict[str, Any]],
    predictions: dict[str, list[dict[str, Any]]],
) -> dict[tuple[str, int], float]:
    spans_by_post = {
        post_id: candidates_to_spans(post_id, posts[post_id], candidates)
        for post_id, candidates in predictions.items()
    }
    risks: dict[tuple[str, int], float] = {}
    for persona_id in PERSONAS:
        ordered = sorted(
            (
                post for post in posts.values()
                if post["post_id"].startswith(f"{persona_id}_")
            ),
            key=lambda post: (post.get("created_at", ""), post["post_id"]),
        )[: max(WINDOWS)]
        for window_size in WINDOWS:
            conditions = [
                condition
                for post in ordered[:window_size]
                for condition in build_conditions(
                    spans_by_post[post["post_id"]], post["post_id"]
                )
            ]
            risks[(persona_id, window_size)] = round(risk_total(conditions), 2)
    return risks


def replace_risks(
    source: Path,
    destination: Path,
    risks: dict[tuple[str, int], float],
) -> None:
    with source.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if not fieldnames:
        raise ValueError(f"{source}: CSV 헤더가 없습니다")

    seen: set[tuple[str, int]] = set()
    for row in rows:
        key = (row["persona_id"], int(row["window_size"]))
        if key not in risks:
            raise ValueError(f"{source}: 위험도가 없는 윈도우: {key}")
        row["our_risk"] = str(risks[key])
        seen.add(key)
    if seen != set(risks):
        raise ValueError("판정표가 일부 예측 윈도우를 포함하지 않습니다")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_metrics(
    scored_path: Path,
    windows_path: Path,
    metrics_path: Path,
    score: ModuleType,
) -> dict[str, Any]:
    details = score.load_details(scored_path)
    windows = score.aggregate_windows(details)
    if len(details) != 490 or len(windows) != 70:
        raise ValueError(
            f"예상 행 수와 다릅니다: details={len(details)}, "
            f"windows={len(windows)}"
        )
    metrics = score.build_metrics(windows)
    score.write_windows(windows_path, windows)
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metrics


def person_block_permutation(
    windows: list[dict[str, Any]],
    *,
    repetitions: int = 10_000,
    seed: int = 20_261_002,
) -> dict[str, Any]:
    """인물 단위 순열 검정 — 한 인물의 7개 윈도우 위험도를 **통째로** 다른 인물에게 옮긴다.

    기존 층화 검정(score.py ``baseline_checks``)은 윈도우마다 인물을 따로 섞어,
    같은 인물의 누적 이력(w1 ⊂ w2 ⊂ … ⊂ w19)이 서로 독립인 것처럼 다룬다.
    여기서는 인물 하나의 위험도 궤적을 한 단위로 두고, 성공 점수는 그대로 둔 채
    인물 사이에서만 궤적을 바꾼다. 귀무가설: 위험도 궤적이 어느 인물 것이든
    추론 성공과의 상관이 같다. 단측(관측 rho 이상).
    """
    personas = sorted({row["persona_id"] for row in windows})
    sizes = sorted({int(row["window_size"]) for row in windows})
    risk = {(row["persona_id"], int(row["window_size"])): float(row["our_risk"]) for row in windows}
    score = {(row["persona_id"], int(row["window_size"])): float(row["success_count"]) for row in windows}
    keys = [(p, w) for p in personas for w in sizes]
    if len(keys) != len(windows):
        raise ValueError("인물 × 윈도우 칸이 비어 있거나 중복입니다")
    scores = np.asarray([score[k] for k in keys])
    observed = float(spearmanr([risk[k] for k in keys], scores).statistic)
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(repetitions):
        order = rng.permutation(len(personas))
        permuted = [risk[(personas[order[i]], w)] for i in range(len(personas)) for w in sizes]
        hits += float(spearmanr(permuted, scores).statistic) >= observed
    return {
        "rho": observed,
        "personas": len(personas),
        "repetitions": repetitions,
        "seed": seed,
        "p_one_sided": (hits + 1) / (repetitions + 1),
    }


def read_window_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--scored", type=Path, default=DEFAULT_SCORED)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    posts = load_posts()
    expected_ids = expected_post_ids(posts)
    listed_ids = [
        line.strip()
        for line in (args.inputs / "post_ids_293.txt").read_text(
            encoding="utf-8-sig"
        ).splitlines()
        if line.strip()
    ]
    if listed_ids != expected_ids:
        raise ValueError(
            "post_ids_293.txt가 exp11의 created_at, post_id 정렬 "
            "190편과 일치하지 않습니다"
        )

    score = _load_module("exp11_score_for_sensitivity", HERE / "score.py")
    # 인물 단위 순열 — 교사 라벨 결과(원본 teacher_window_scores.csv)도 같은 검정으로 비교한다. 원본 파일은 읽기만 한다
    block = {"teacher": person_block_permutation(read_window_csv(args.results / "teacher_window_scores.csv"))}
    for label, filename in PREDICTIONS.items():
        predictions = load_predictions(args.inputs / filename, expected_ids)
        risks = build_window_risks(posts, predictions)
        scored_path = args.results / f"sensitivity_{label}_scored.csv"
        windows_path = args.results / f"sensitivity_{label}_window_scores.csv"
        metrics_path = args.results / f"sensitivity_{label}_metrics.json"
        replace_risks(args.scored, scored_path, risks)
        metrics = write_metrics(
            scored_path, windows_path, metrics_path, score
        )
        block[label] = person_block_permutation(read_window_csv(windows_path))
        primary = metrics["primary"]
        baseline = metrics["window_size_baseline"]
        print(
            f"{label}: 전체 rho={primary['pooled']['rho']:.3f} · "
            f"튜닝={primary['tune']['rho']:.3f} · "
            f"보고={primary['report']['rho']:.3f}"
        )
        print(
            f"  글 수 기준선={baseline['rho_window_size_baseline']:.3f} · "
            "글 수 통제 부분상관="
            f"{baseline['partial_rho_given_window_size']:.3f} · "
            "층화 p="
            f"{baseline['within_window_shuffle']['p_one_sided']:.4g} · "
            f"인물 단위 p={block[label]['p_one_sided']:.4g}"
        )
    (args.results / "sensitivity_person_block_permutation.json").write_text(
        json.dumps(block, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"teacher: 인물 단위 p={block['teacher']['p_one_sided']:.4g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
