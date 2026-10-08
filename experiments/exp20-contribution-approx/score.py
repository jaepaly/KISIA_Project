"""근사기 글별 기여도를 LOO 정답과 비교한다."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any

from scipy.stats import spearmanr


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(payload: Any, *, path: Path) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("predictions"), list):
        rows = payload["predictions"]
    else:
        raise ValueError(f"{path}: 예측은 목록 또는 predictions 목록이어야 합니다")
    if not rows:
        raise ValueError(f"{path}: 예측이 비었습니다")

    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not {"post_id", "delta", "rank"} <= row.keys():
            raise ValueError(f"{path}: 각 예측에는 post_id, delta, rank가 필요합니다")
        post_id, delta, rank = row["post_id"], row["delta"], row["rank"]
        if not isinstance(post_id, str) or not post_id:
            raise ValueError(f"{path}: post_id는 빈 문자열이 아닌 문자열이어야 합니다")
        if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not math.isfinite(float(delta)):
            raise ValueError(f"{path}: delta는 유한한 숫자여야 합니다")
        if isinstance(rank, bool) or not isinstance(rank, int):
            raise ValueError(f"{path}: rank는 정수여야 합니다")
        normalized.append({**row, "delta": float(delta), "rank": rank})

    ids = [row["post_id"] for row in normalized]
    ranks = [row["rank"] for row in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: post_id가 중복됩니다")
    if sorted(ranks) != list(range(1, len(normalized) + 1)):
        raise ValueError(f"{path}: rank는 1부터 끊김 없이 한 번씩 있어야 합니다")

    expected = sorted(normalized, key=lambda row: (-abs(row["delta"]), row["post_id"]))
    if any(row["rank"] != rank for rank, row in enumerate(expected, 1)):
        raise ValueError(f"{path}: rank가 abs(delta) 내림차순·동률 post_id 순서와 일치하지 않습니다")
    return normalized


def load_gold(path: Path) -> tuple[float, list[dict[str, Any]]]:
    payload = _read_json(path)
    try:
        method = payload["input"]["method"]
        post_ids = payload["input"]["post_ids"]
        baseline = payload["output"]["baseline_risk"]
        raw_rows = payload["output"]["contributions"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{path}: LOO 정답 형식이 아닙니다") from exc
    if method != "loo":
        raise ValueError(f"{path}: input.method는 loo여야 합니다")
    if isinstance(baseline, bool) or not isinstance(baseline, (int, float)) or not math.isfinite(float(baseline)):
        raise ValueError(f"{path}: baseline_risk는 유한한 숫자여야 합니다")
    rows = _rows(raw_rows, path=path)
    if not isinstance(post_ids, list) or any(not isinstance(value, str) or not value for value in post_ids):
        raise ValueError(f"{path}: input.post_ids는 문자열 목록이어야 합니다")
    if len(post_ids) != len(set(post_ids)) or set(post_ids) != {row["post_id"] for row in rows}:
        raise ValueError(f"{path}: input.post_ids와 contributions가 일치하지 않습니다")
    return float(baseline), rows


def load_prediction(path: Path) -> list[dict[str, Any]]:
    return _rows(_read_json(path), path=path)


def _top_ids(rows: list[dict[str, Any]], k: int = 3) -> set[str]:
    return {row["post_id"] for row in sorted(rows, key=lambda row: row["rank"])[:k]}


def _gold_top_ids_with_ties(rows: list[dict[str, Any]], k: int = 3) -> set[str]:
    # 기여 0 인 글은 후보에서 뺀다 — 0 끼리 동률로 묶으면 0 아닌 글이 3편 미만인 인물은 글 전체가 정답이 돼
    # 어떤 예측도 만점을 받는다 (실측: 평가 대상 66명 중 63명이 0 아닌 글 3편 미만)
    ordered = sorted((abs(row["delta"]) for row in rows if row["delta"] != 0), reverse=True)
    if not ordered:
        return set()
    threshold = ordered[min(k, len(ordered)) - 1]
    return {row["post_id"] for row in rows if row["delta"] != 0 and abs(row["delta"]) >= threshold}


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def evaluate(gold_dir: Path, prediction_dir: Path) -> dict[str, Any]:
    """인물별 abs(delta) 순위 상관과 상위 글 일치도를 계산한다."""
    people: list[dict[str, Any]] = []
    excluded_zero_baseline: list[str] = []

    for gold_path in sorted(gold_dir.glob("*.json")):
        persona_id = gold_path.stem
        baseline, gold_rows = load_gold(gold_path)
        if baseline == 0:
            excluded_zero_baseline.append(persona_id)
            continue

        prediction_path = prediction_dir / gold_path.name
        if not prediction_path.exists():
            raise FileNotFoundError(f"{persona_id}: 근사기 예측 파일이 없습니다: {prediction_path}")
        predicted_rows = load_prediction(prediction_path)
        gold_by_id = {row["post_id"]: row for row in gold_rows}
        pred_by_id = {row["post_id"]: row for row in predicted_rows}
        if set(gold_by_id) != set(pred_by_id):
            missing = sorted(set(gold_by_id) - set(pred_by_id))
            extra = sorted(set(pred_by_id) - set(gold_by_id))
            raise ValueError(f"{persona_id}: post_id 불일치 missing={missing} extra={extra}")

        post_ids = sorted(gold_by_id)
        gold_values = [abs(gold_by_id[pid]["delta"]) for pid in post_ids]
        pred_values = [abs(pred_by_id[pid]["delta"]) for pid in post_ids]
        rho: float | None = None
        rho_status = "insufficient_posts"
        if len(post_ids) >= 2 and len(set(gold_values)) == 1:
            rho_status = "gold_constant"
        elif len(post_ids) >= 2 and len(set(pred_values)) == 1:
            rho, rho_status = 0.0, "prediction_constant_failure"
        elif len(post_ids) >= 2:
            rho = float(spearmanr(gold_values, pred_values).statistic)
            if not math.isfinite(rho):
                raise ValueError(f"{persona_id}: 유한한 Spearman rho를 계산하지 못했습니다")
            rho_status = "ok"

        # 글이 3편 이하면 「상위 3편」이 곧 전체라 누구나 만점 — top-3 는 4편 이상인 인물만 잰다
        top3_rank: float | None = None
        top3_tie_aware: float | None = None
        if len(post_ids) > 3:
            predicted_top = _top_ids(predicted_rows)
            top3_rank = len(_top_ids(gold_rows) & predicted_top) / 3
            gold_top = _gold_top_ids_with_ties(gold_rows)
            if gold_top:
                top3_tie_aware = len(gold_top & predicted_top) / min(3, len(gold_top))
        signed_errors = [pred_by_id[pid]["delta"] - gold_by_id[pid]["delta"] for pid in post_ids]
        people.append({
            "persona_id": persona_id,
            "n_posts": len(post_ids),
            "spearman_rho_abs_delta": rho,
            "spearman_status": rho_status,
            "top3_rank_agreement": top3_rank,
            "top3_tie_aware_recall": top3_tie_aware,
            "sign_accuracy": mean(
                _sign(pred_by_id[pid]["delta"]) == _sign(gold_by_id[pid]["delta"])
                for pid in post_ids
            ),
            "signed_delta_mae": mean(abs(value) for value in signed_errors),
        })

    if not people:
        raise ValueError("평가할 인물이 없습니다")
    rhos = [row["spearman_rho_abs_delta"] for row in people if row["spearman_rho_abs_delta"] is not None]
    if not rhos:
        raise ValueError("순위 상관을 계산할 수 있는 비상수 정답 인물이 없습니다")
    macro_rho = mean(rhos)
    top3_ranks = [row["top3_rank_agreement"] for row in people if row["top3_rank_agreement"] is not None]
    top3_ties = [row["top3_tie_aware_recall"] for row in people if row["top3_tie_aware_recall"] is not None]
    return {
        "n_personas": len(people),
        "n_personas_for_spearman": len(rhos),
        "n_personas_gold_constant": sum(row["spearman_status"] == "gold_constant" for row in people),
        "n_personas_prediction_constant_failure": sum(
            row["spearman_status"] == "prediction_constant_failure" for row in people
        ),
        "excluded_zero_baseline": excluded_zero_baseline,
        "macro_spearman_rho_abs_delta": macro_rho,
        "n_personas_for_top3": len(top3_ranks),
        "n_personas_for_top3_tie_aware": len(top3_ties),
        "macro_top3_rank_agreement": mean(top3_ranks) if top3_ranks else None,
        "macro_top3_tie_aware_recall": mean(top3_ties) if top3_ties else None,
        "macro_sign_accuracy": mean(row["sign_accuracy"] for row in people),
        "macro_signed_delta_mae": mean(row["signed_delta_mae"] for row in people),
        "target_spearman_ge_0_8": macro_rho + 1e-12 >= 0.8,
        "people": people,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="근사기 기여도와 LOO 정답 평가")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = evaluate(args.gold, args.predictions)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
