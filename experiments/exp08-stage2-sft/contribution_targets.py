"""C 증류 타깃(gold/contribution/<pid>.json) → 2단 학습 입력·출력 조각.

C 의 gen_contribution_targets.py 가 만드는 파일은 contribution.schema.json 형식이다
(loo.leave_one_out() 반환값 그대로). 이 모듈은 그 파일을 읽어 2단 SFT 가 쓰는 세 가지로 바꾼다.

  post_deltas()                     post_id → delta        (stage2 InputPost.contribution)
  recommendation_from_contribution  greedy_path → Stage2Output.recommendation
  approximator_targets()            근사기 학습 타깃 — post 별 (delta, rank)

계약 검증은 jsonschema 로 한다. contribution.schema.json 의 $comment 에 적힌 런타임 불변식
(3)(5)(6) 도 여기서 같이 검사한다 — JSON Schema 만으로는 못 잡는 것들이다.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "docs" / "contracts"


@lru_cache(maxsize=None)
def _schema(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _contribution_validator() -> Draft202012Validator:
    return Draft202012Validator(_schema("contribution.schema.json"))


@lru_cache(maxsize=None)
def _recommendation_validator() -> Draft202012Validator:
    full = Draft202012Validator(_schema("stage2-io.schema.json"))
    sub = full.schema["$defs"]["Stage2Output"]["properties"]["recommendation"]
    # evolve 로 $defs 참조(Action 등)를 유지한 채 하위 스키마만 검증한다
    return full.evolve(schema={**sub, "$defs": full.schema["$defs"]})


def validate_contribution(doc: dict) -> None:
    """계약 + 런타임 불변식. 어긋나면 ValueError."""
    errors = sorted(_contribution_validator().iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        raise ValueError(f"contribution 계약 위반 {list(first.path)}: {first.message}")

    out = doc["output"]
    base = out["baseline_risk"]
    rows = out["contributions"]

    ids = sorted(doc["input"]["post_ids"])
    if sorted(r["post_id"] for r in rows) != ids:
        raise ValueError("불변식 (5): contributions 는 input.post_ids 와 1:1 이어야 한다")
    for r in rows:
        if abs(r["risk_without"] - (base + r["delta"])) > 0.011:
            raise ValueError(f"불변식 (3): {r['post_id']} risk_without != baseline + delta")
    expected = sorted(rows, key=lambda r: (-abs(r["delta"]), r["post_id"]))
    if [r["post_id"] for r in expected] != [r["post_id"] for r in rows] or \
            [r["rank"] for r in rows] != list(range(1, len(rows) + 1)):
        raise ValueError("불변식 (6): rank 는 |delta| 내림차순 · 동률은 post_id 오름차순")


def load_contribution(path: Path | str) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_contribution(doc)
    return doc


def post_deltas(doc: dict) -> dict[str, float]:
    """post_id → delta. stage2 InputPost.contribution 은 «≤ 0» 이라 양수 delta 는 0 으로 막는다."""
    return {r["post_id"]: min(0.0, float(r["delta"])) for r in doc["output"]["contributions"]}


def approximator_targets(doc: dict) -> list[dict[str, Any]]:
    """근사기(#124 ①) 타깃 — 글 하나당 (delta, rank). 순서는 rank."""
    return [
        {"post_id": r["post_id"], "delta": r["delta"], "rank": r["rank"]}
        for r in doc["output"]["contributions"]
    ]


_USER_SCOPED_TARGET = {
    "profile_bio": ("profile", "profile_bio"),
    "nickname": ("meta_field", "nickname"),
    "activity_pattern": ("meta_field", "post_time"),
}
_BURDEN_ORDER = {"low": 0, "medium": 1, "high": 2}


def recommendation_from_contribution(doc: dict, *, max_actions: int = 3) -> dict:
    """greedy_path 를 기본 추천으로. 조치는 unpublish(글) + user_scoped(프로필·메타).

    - unpublish 한 건 = greedy 한 걸음. **projected_delta 는 계약대로 «이 조치 단독» 의 변화** =
      contributions[].delta (전체 글에서 그 글 하나만 뺐을 때). greedy 직전-직후 차이(누적 한계효과)는
      조치끼리 상호작용하면 이것과 달라지는데, 그 누적값은 projected.projected_risk 가 들고 간다
      (apps/demo recommend.py 의 projected_delta / _k_cum 구분과 같다).
    - user_scoped 는 글을 다 내려도 남는 몫(residual_risk) 을 해소하는 조치라 뒤에 붙이고,
      그 효과도 projected_risk 에 순차 반영한다.
    - actions 는 burden 오름차순(계약) — 여기서는 전부 low 라 순서 유지.
    """
    out = doc["output"]
    base = float(out["baseline_risk"])
    residual = float(out["residual_risk"])
    delta_by_post = {r["post_id"]: float(r["delta"]) for r in out["contributions"]}

    actions: list[dict] = []
    risk = base
    for step in out["greedy_path"][:max_actions]:
        risk = float(step["risk_after"])
        actions.append({
            "action_type": "unpublish",
            "burden": "low",
            "certainty": "highest",
            "targets": [{"kind": "post", "ref": step["remove"]}],
            "projected_delta": round(min(0.0, delta_by_post[step["remove"]]), 2),
            "rationale": f"내린 뒤 누적 {risk:.1f}",
        })

    floor = residual
    for item in out["user_scoped"]:
        kind, ref = _USER_SCOPED_TARGET[item["source"]]
        d = -abs(float(item["delta"]))
        actions.append({
            "action_type": "activity_meta",
            "burden": "low",
            "certainty": "high",
            "targets": [{"kind": kind, "ref": ref}],
            "projected_delta": round(min(0.0, d), 2),
            "rationale": None,
        })
        risk = max(0.0, risk + d)
        floor = max(0.0, floor + d)

    actions.sort(key=lambda a: _BURDEN_ORDER[a["burden"]])
    projected_risk = risk if actions else base
    rec = {
        "actions": actions,
        "projected": {
            "current_risk": round(base, 2),
            "projected_risk": round(projected_risk, 2),
            "reduction_pct": round((base - projected_risk) / base * 100, 1) if base > 0 else 0.0,
            # 남은 몫(residual 에서 user_scoped 로 덜어낸 것) 까지 내려왔으면 목표 도달
            "target_met": projected_risk <= floor + 1e-9,
        },
        "optimality_gap_pct": None,
    }
    errors = list(_recommendation_validator().iter_errors(rec))
    if errors:
        raise ValueError(f"recommendation 계약 위반: {errors[0].message}")
    return rec
