"""검수된 교사 LLM 판정표로 위험도 상관 지표를 계산한다."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr


HERE = Path(__file__).resolve().parent
DEFAULT_RESULTS = HERE / "results"
ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")
TUNE = {"B08", "D03", "E14", "B15", "D21"}
REPORT = {"A14", "E03", "B06", "B07", "A10"}


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"불리언 값이 아닙니다: {value!r}")


def load_details(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    required = {
        "persona_id",
        "split",
        "window_size",
        "our_risk",
        "attribute",
        "correct",
        "correct_e03_current_location",
    }
    missing = required - set(rows[0] if rows else ())
    if missing:
        raise ValueError(f"판정표 필수 열이 없습니다: {sorted(missing)}")

    parsed: list[dict[str, Any]] = []
    for row in rows:
        parsed.append(
            {
                **row,
                "window_size": int(row["window_size"]),
                "our_risk": float(row["our_risk"]),
                "correct": parse_bool(row["correct"]),
                "correct_e03_current_location": parse_bool(
                    row["correct_e03_current_location"]
                ),
            }
        )
    return parsed


def aggregate_windows(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in details:
        grouped[(row["persona_id"], row["window_size"])].append(row)

    windows: list[dict[str, Any]] = []
    for (persona_id, window_size), rows in sorted(grouped.items()):
        attributes = {row["attribute"] for row in rows}
        if attributes != set(ATTRS) or len(rows) != len(ATTRS):
            raise ValueError(
                f"{persona_id} w={window_size}: 속성 구성이 잘못됐습니다: "
                f"{sorted(attributes)}"
            )

        risks = {row["our_risk"] for row in rows}
        splits = {row["split"] for row in rows}
        if len(risks) != 1 or len(splits) != 1:
            raise ValueError(
                f"{persona_id} w={window_size}: "
                "risk/split이 일관되지 않습니다"
            )

        # 주 분석: 현 거주지 기준.
        # 해외 인물 E01~E05는 ground_truth.location의 국내 연고지가 아니라
        # ground_truth의 다른 항목에서 확인되는 현 거주 도시로 채점한다.
        success = sum(
            bool(row["correct_e03_current_location"]) for row in rows
        )

        # 민감도 분석: 기존 ground_truth.location을 그대로 적용한 결과.
        ground_truth_location = sum(
            bool(row["correct"]) for row in rows
        )
        windows.append(
            {
                "persona_id": persona_id,
                "split": splits.pop(),
                "window_size": window_size,
                "our_risk": risks.pop(),
                "success_count": success,
                "success_rate": round(success / len(ATTRS), 6),
                "success_count_e03_ground_truth_location": ground_truth_location,
            }
        )
    return windows


def correlation(
    rows: list[dict[str, Any]],
    score_key: str = "success_count",
) -> dict[str, Any]:
    result = spearmanr(
        [row["our_risk"] for row in rows],
        [row[score_key] for row in rows],
    )
    return {
        "n": len(rows),
        "rho": float(result.statistic),
        "p": float(result.pvalue),
    }


def persona_permutation_p(
    rows: list[dict[str, Any]],
    *,
    repetitions: int = 10_000,
    seed: int = 20_261_002,
) -> dict[str, Any]:
    observed = correlation(rows)["rho"]
    risks = np.asarray([row["our_risk"] for row in rows], dtype=float)
    scores = np.asarray([row["success_count"] for row in rows], dtype=float)
    indices: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        indices[row["persona_id"]].append(index)

    rng = np.random.default_rng(seed)
    extreme = 0
    for _ in range(repetitions):
        shuffled = scores.copy()
        for person_indices in indices.values():
            shuffled[person_indices] = rng.permutation(shuffled[person_indices])
        rho = float(spearmanr(risks, shuffled).statistic)
        extreme += abs(rho) >= abs(observed)

    return {
        "repetitions": repetitions,
        "seed": seed,
        "p_two_sided": (extreme + 1) / (repetitions + 1),
    }


def baseline_checks(
    rows: list[dict[str, Any]],
    *,
    n_perm: int = 10_000,
    seed: int = 20_261_002,
) -> dict[str, Any]:
    """글 수 효과를 분리해 위험도의 추가 설명력을 측정한다."""
    window_sizes = np.asarray(
        [float(row["window_size"]) for row in rows],
        dtype=float,
    )
    risks = np.asarray(
        [float(row["our_risk"]) for row in rows],
        dtype=float,
    )
    scores = np.asarray(
        [float(row["success_count"]) for row in rows],
        dtype=float,
    )

    rho_risk_score = float(spearmanr(risks, scores).statistic)
    rho_window_score = float(spearmanr(window_sizes, scores).statistic)
    rho_window_risk = float(spearmanr(window_sizes, risks).statistic)
    denominator = np.sqrt(
        (1 - rho_window_risk**2) * (1 - rho_window_score**2)
    )
    partial_rho = (
        rho_risk_score - rho_window_risk * rho_window_score
    ) / denominator

    groups = {
        int(value): np.flatnonzero(window_sizes == value)
        for value in np.unique(window_sizes)
    }
    within_window_rho = {
        window_size: (
            float(spearmanr(risks[indices], scores[indices]).statistic)
            if len(set(risks[indices])) > 1
            and len(set(scores[indices])) > 1
            else None
        )
        for window_size, indices in groups.items()
    }

    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(n_perm):
        permuted_risks = risks.copy()
        for indices in groups.values():
            permuted_risks[indices] = rng.permutation(risks[indices])
        hits += (
            float(spearmanr(permuted_risks, scores).statistic)
            >= rho_risk_score
        )

    return {
        "rho_window_size_baseline": rho_window_score,
        "partial_rho_given_window_size": float(partial_rho),
        "within_window_rho": within_window_rho,
        "within_window_shuffle": {
            "repetitions": n_perm,
            "seed": seed,
            "p_one_sided": (hits + 1) / (n_perm + 1),
        },
    }


def build_metrics(windows: list[dict[str, Any]]) -> dict[str, Any]:
    persona_ids = sorted({row["persona_id"] for row in windows})
    per_person = {
        persona_id: correlation(
            [row for row in windows if row["persona_id"] == persona_id]
        )
        for persona_id in persona_ids
    }
    rhos = [item["rho"] for item in per_person.values()]
    leave_one_out = {
        persona_id: correlation(
            [row for row in windows if row["persona_id"] != persona_id]
        )
        for persona_id in persona_ids
    }

    return {
        "scoring": {
            "primary": (
                "현 거주지와 의미 비교; 해외 인물 E01~E05는 "
                "ground_truth의 다른 항목에서 확인되는 현 거주 도시 기준"
            ),
            "alternative": (
                "E03 location만 persona ground_truth.location의 강릉 기준"
            ),
        },
        "primary": {
            "pooled": correlation(windows),
            "tune": correlation(
                [row for row in windows if row["persona_id"] in TUNE]
            ),
            "report": correlation(
                [row for row in windows if row["persona_id"] in REPORT]
            ),
            "per_person": per_person,
            "per_person_rho_summary": {
                "median": float(np.median(rhos)),
                "min": float(np.min(rhos)),
                "max": float(np.max(rhos)),
            },
            "leave_one_persona_out": leave_one_out,
            "persona_stratified_permutation": persona_permutation_p(windows),
        },
        "window_size_baseline": baseline_checks(windows),
        "e03_ground_truth_location_sensitivity": {
            "pooled": correlation(
                windows, "success_count_e03_ground_truth_location"
            ),
            "report": correlation(
                [row for row in windows if row["persona_id"] in REPORT],
                "success_count_e03_ground_truth_location",
            ),
        },
    }


def write_windows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scored",
        type=Path,
        default=DEFAULT_RESULTS / "teacher_all_scored.csv",
    )
    parser.add_argument(
        "--windows-out",
        type=Path,
        default=DEFAULT_RESULTS / "teacher_window_scores.csv",
    )
    parser.add_argument(
        "--metrics-out",
        type=Path,
        default=DEFAULT_RESULTS / "teacher_metrics.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    details = load_details(args.scored)
    windows = aggregate_windows(details)
    if len(details) != 490 or len(windows) != 70:
        raise ValueError(
            "예상 행 수와 다릅니다: "
            f"details={len(details)}, windows={len(windows)}"
        )

    metrics = build_metrics(windows)
    write_windows(args.windows_out, windows)
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    primary = metrics["primary"]
    print(f"전체  rho={primary['pooled']['rho']:.3f} p={primary['pooled']['p']:.3g}")
    print(f"튜닝  rho={primary['tune']['rho']:.3f} p={primary['tune']['p']:.3g}")
    print(f"보고  rho={primary['report']['rho']:.3f} p={primary['report']['p']:.3g}")
    baseline = metrics["window_size_baseline"]
    print(
        "글 수 기준선 "
        f"rho={baseline['rho_window_size_baseline']:.3f}"
    )
    print(
        "글 수 통제 부분상관 "
        f"rho={baseline['partial_rho_given_window_size']:.3f}"
    )
    print(
        "같은 글 수 층화 순열검정 "
        f"p={baseline['within_window_shuffle']['p_one_sided']:.4g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
