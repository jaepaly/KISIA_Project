"""근사기 글별 기여도를 LOO 정답과 비교한다."""
from __future__ import annotations

import argparse
import json
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
    required = {"post_id", "delta", "rank"}
    for row in rows:
        if not isinstance(row, dict) or not required <= row.keys():
            raise ValueError(f"{path}: 각 예측에는 post_id, delta, rank가 필요합니다")
    ids = [str(row["post_id"]) for row in rows]
    ranks = [int(row["rank"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: post_id가 중복됩니다")
    if sorted(ranks) != list(range(1, len(rows) + 1)):
        raise ValueError(f"{path}: rank는 1부터 끊김 없이 한 번씩 있어야 합니다")
    return rows


def load_gold(path: Path) -> tuple[float, list[dict[str, Any]]]:
    payload = _read_json(path)
    try:
        baseline = float(payload["output"]["baseline_risk"])
        rows = payload["output"]["contributions"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{path}: LOO 정답 형식이 아닙니다") from exc
    return baseline, _rows(rows, path=path)


def load_prediction(path: Path) -> list[dict[str, Any]]:
    return _rows(_read_json(path), path=path)


def _top_ids(rows: list[dict[str, Any]], k: int = 3) -> set[str]:
    return {
        str(row["post_id"])
        for row in sorted(rows, key=lambda row: (int(row["rank"]), str(row["post_id"])))[:k]
    }


def evaluate(gold_dir: Path, prediction_dir: Path) -> dict[str, Any]:
    """인물별 순위 상관과 top-3 일치율을 계산한다."""
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
        gold_by_id = {str(row["post_id"]): row for row in gold_rows}
        pred_by_id = {str(row["post_id"]): row for row in predicted_rows}
        if set(gold_by_id) != set(pred_by_id):
            missing = sorted(set(gold_by_id) - set(pred_by_id))
            extra = sorted(set(pred_by_id) - set(gold_by_id))
            raise ValueError(f"{persona_id}: post_id 불일치 missing={missing} extra={extra}")

        post_ids = sorted(gold_by_id)
        rho = None
        if len(post_ids) >= 2:
            rho = float(spearmanr(
                [int(gold_by_id[post_id]["rank"]) for post_id in post_ids],
                [int(pred_by_id[post_id]["rank"]) for post_id in post_ids],
            ).statistic)
        denominator = min(3, len(post_ids))
        top3 = len(_top_ids(gold_rows) & _top_ids(predicted_rows)) / denominator
        people.append({
            "persona_id": persona_id,
            "n_posts": len(post_ids),
            "spearman_rho": rho,
            "top3_agreement": top3,
        })

    if not people:
        raise ValueError("평가할 인물이 없습니다")
    rhos = [row["spearman_rho"] for row in people if row["spearman_rho"] is not None]
    if not rhos:
        raise ValueError("순위 상관을 계산할 수 있는 2편 이상 인물이 없습니다")
    return {
        "n_personas": len(people),
        "n_personas_for_spearman": len(rhos),
        "excluded_zero_baseline": excluded_zero_baseline,
        "macro_spearman_rho": mean(rhos),
        "macro_top3_agreement": mean(row["top3_agreement"] for row in people),
        "target_spearman_ge_0_8": mean(rhos) + 1e-12 >= 0.8,
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
