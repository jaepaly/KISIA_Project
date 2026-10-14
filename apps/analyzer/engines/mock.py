"""실제 모델(B·C·D)이 오기 전까지 쓰는 가짜 엔진.

숫자는 의미 없다. docs/contracts/*.schema.json 을 통과하는 형식만 보장한다.
계약대로 만들어 뒀으니 real.py 로 교체해도 서버·화면은 그대로 돈다
(docs/roles/howto/e-integration.md §2).

일부러 심어둔 비정상 케이스 (howto §2 표):
  - stage2 findings 중 6개는 abstain — "판단 보류" 표시가 되는지 확인용
  - specificity 는 location 조건이 없으면 k=null/UNKNOWN — "산출 불가"가
    "0명"으로 잘못 뜨지 않는지 확인용
  - detect_spans 는 키워드가 하나도 없으면 spans: [] — "탐지된 단서 없음"
    확인용 (네거티브 컨트롤)
"""

from __future__ import annotations

from datetime import datetime, timezone

MODEL_VERSION = "mock-0.1.0"
DICT_VERSION = "mock-dict-0.1.0"
SCHEMA_VERSION_SPAN = "1.0"
SCHEMA_VERSION_SPEC = "1.0"
SCHEMA_VERSION_CONTRIB = "1.0"
SCHEMA_VERSION_STAGE2 = "0.1.0"

_KEYWORDS = [
    ("저수지", "LOC_FACILITY"), ("호수", "LOC_FACILITY"), ("역", "LOC_FACILITY"),
    ("퇴근", "COMMUTE"), ("출근", "COMMUTE"),
    ("첫째", "FAM"), ("아이", "FAM"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def detect_spans(post: dict) -> dict:
    """B(c1) 자리. span.schema.json 준수."""
    body = post.get("body", "")
    spans = []
    for i, (kw, typ) in enumerate(_KEYWORDS):
        pos = body.find(kw)
        if pos >= 0:
            spans.append({
                "span_id": f"{post['post_id']}_s{len(spans) + 1:02d}",
                "text_id": "body",
                "start": pos,
                "end": pos + len(kw),
                "text": kw,
                "type": typ,
                "level": "inferential",
                "subject": "self",
                "score": 0.5,
            })
    return {
        "schema_version": SCHEMA_VERSION_SPAN,
        "model_version": MODEL_VERSION,
        "record_type": "post",
        "post_id": post["post_id"],
        "spans": spans,
    }


_AXIS_BY_TYPE = {
    "LOC_FACILITY": "location", "LOC_ADMIN": "location",
    "REL_HOME": "location", "REL_WORK": "location",
    "AGE": "age", "SEX": "sex", "JOB": "occupation",
    "FAM": "family", "COMMUTE": "commute", "INCOME": "income",
}


def conditions(posts: list[dict], spans_by_post: dict[str, dict]) -> list[dict]:
    """목 조건 — 계약(conditions minItems 1) 최소 형태만. 값은 의미 없다."""
    all_post_ids = [p["post_id"] for p in posts]
    by_axis: dict[str, list[str]] = {}
    for post_id, result in spans_by_post.items():
        for span in result["spans"]:
            axis = _AXIS_BY_TYPE.get(span["type"])
            if axis:
                by_axis.setdefault(axis, []).append(post_id)

    if not by_axis:
        # 네거티브 컨트롤 — 탐지된 단서가 하나도 없다. axis를 location이 아닌
        # 값으로 둬 specificity가 UNKNOWN(산출 불가)을 내도록 한다.
        return [{
            "axis": "occupation", "kind": "none_detected", "value": "MOCK_NONE",
            "resolution": 0, "confidence": 0.0,
            "source_post_ids": all_post_ids or ["mock_post"],
        }]

    out = []
    for axis, post_ids in by_axis.items():
        cond = {
            "axis": axis, "kind": "mock_detected", "value": "MOCK",
            "resolution": 1, "confidence": 0.5,
            "source_post_ids": sorted(set(post_ids)),
        }
        if axis == "location":
            cond["geo_code"] = "4146351000"
        out.append(cond)
    return out


def per_post_k(posts: list[dict], spans_by_post: dict[str, dict]) -> None:
    """목에는 글별 k 가 없다 — 화면은 이 칸이 비면 표시하지 않는다."""
    return None


def specificity(payload: dict) -> dict:
    """C(c2) 자리. specificity.schema.json 준수.

    payload: {"user_ref": "u_...", "conditions": [...]}
    조건 중 axis=location 이 하나라도 있으면 산출, 없으면 UNKNOWN.
    """
    conditions = payload.get("conditions", [])
    location = next((c for c in conditions if c.get("axis") == "location"), None)

    if location is not None:
        k = 5.0
        k_level = "ACCEPTABLE"
        basis = {"source": "MOCK-population-table", "as_of": "2026-07", "method": "direct"}
        steps = [{
            "axis": "location", "condition": location.get("kind", "mock"),
            "n_after": k, "method": "population_lookup",
        }]
    else:
        k = None
        k_level = "UNKNOWN"
        basis = {"source": "MOCK", "as_of": "2026-07"}
        steps = []

    return {
        "schema_version": SCHEMA_VERSION_SPEC,
        "engine_version": "c2-mock-0.1.0",
        "dict_version": DICT_VERSION,
        "input": payload,
        "output": {
            "k": k,
            "k_level": k_level,
            "basis": basis,
            "risk": 20.0 if k_level == "ACCEPTABLE" else 0.0,
            "risk_by_axis": {},
            "floor_applied": False,
            "steps": steps,
            "assumptions": ["MOCK 값 — 계약 검증용"],
        },
    }


def contribution(user_ref: str, posts: list[dict], removed_post_ids: list[str] | None = None, *,
                 spans_by_post: dict | None = None) -> dict:
    """C(c3) 자리. contribution.schema.json 준수.

    글이 많을수록 baseline_risk 가 오르는 형태만 흉내낸다.
    """
    post_ids = [p["post_id"] for p in posts]
    n = max(len(post_ids), 1)
    baseline = round(min(20 + 4.0 * len(post_ids), 95.0), 1)
    share = round(baseline / n, 1)

    items = [{
        "post_id": pid,
        "risk_without": round(baseline - share, 1),
        "delta": -share,
        "rank": 0,
        "clue_ids": [f"{pid}#0"],
        "top_spans": [{"span_id": f"{pid}_s01", "text_id": "body"}],
    } for pid in post_ids]
    items.sort(key=lambda it: (-abs(it["delta"]), it["post_id"]))
    for rank, it in enumerate(items, start=1):
        it["rank"] = rank

    risk_after = None
    if removed_post_ids:
        remaining = [pid for pid in post_ids if pid not in removed_post_ids]
        risk_after = round(min(20 + 4.0 * len(remaining), 95.0), 1)

    greedy_path = []
    remaining_n = len(post_ids)
    for it in items:
        remaining_n -= 1
        greedy_path.append({
            "remove": it["post_id"],
            "risk_after": round(min(20 + 4.0 * remaining_n, 95.0), 1),
        })

    return {
        "schema_version": SCHEMA_VERSION_CONTRIB,
        "engine_version": "c3-mock-0.1.0",
        "input": {
            "user_ref": user_ref,
            "post_ids": post_ids or ["mock_post"],
            "method": "loo",
            **({"removed_post_ids": removed_post_ids} if removed_post_ids else {}),
        },
        "output": {
            "baseline_risk": baseline,
            "residual_risk": 0.0,
            **({"risk_after": risk_after} if removed_post_ids else {}),
            "contributions": items or [{
                "post_id": "mock_post", "risk_without": baseline, "delta": 0.0,
                "rank": 1, "clue_ids": [], "top_spans": [],
            }],
            "user_scoped": [],
            "greedy_path": greedy_path,
            "approx_error": None,
            "note": "MOCK 값 — delta 는 균등 배분이며 실제 근거가 아니다",
        },
    }


def _abstain_finding() -> dict:
    return {"verdict": "abstain", "granularity": None, "evidence": [], "confidence": 0.1}


def _default_input_post(post_id: str = "mock_post") -> dict:
    return {
        "post_id": post_id,
        "texts": [{"text_id": "body", "pseudonymized": "[MOCK 본문]"}],
        "spans": [],
        "pseudonym_map": [],
    }


def stage2(user_ref: str, posts: list[dict], risk_current: float = 79.7, risk_target: float = 40.0, *,
           spans_by_post: dict | None = None, detect_inputs: dict | None = None) -> dict:
    """D(c4) 자리. stage2-io.schema.json 준수 (input+output 둘 다 담아 반환).

    findings 7속성 중 location 만 narrowed, 나머지 6개는 abstain으로 심어
    화면이 "판단 보류"를 표시할 수 있는지 확인한다 (howto §2 표).
    spans_by_post · detect_inputs 는 real 과 같은 자리(서버가 이번 요청에서 탐지한 스팬 · 1단 입력) — 목은 쓰지 않는다.
    """
    now = _now()
    input_posts = [_default_input_post(p["post_id"]) for p in posts] or [_default_input_post()]
    first_id = input_posts[0]["post_id"]

    stage2_input = {
        "schema_version": SCHEMA_VERSION_STAGE2,
        "user_ref": user_ref,
        "posts": input_posts,
        "risk": {"current": risk_current, "target": risk_target},
        "provenance": {
            "measured_at": now, "model_version": MODEL_VERSION, "dict_version": DICT_VERSION,
        },
    }

    findings = {
        "age": _abstain_finding(),
        "sex": _abstain_finding(),
        "location": {
            "verdict": "narrowed",
            "granularity": "sigungu",
            "evidence": [{
                "post_id": first_id, "span_id": f"{first_id}_s01",
                "label": "[시설A]", "relation": "residence_proximity",
            }],
            "confidence": 0.5,
            "cross_post": False,
        },
        "occupation": _abstain_finding(),
        "family": _abstain_finding(),
        "commute": _abstain_finding(),
        "income": _abstain_finding(),
    }

    reduction = round(max(risk_current - risk_target, 0.0), 1)
    output = {
        "schema_version": SCHEMA_VERSION_STAGE2,
        "findings": findings,
        "recommendation": {
            "actions": [{
                "action_type": "unpublish",
                "burden": "low",
                "certainty": "medium",
                "targets": [{"kind": "post", "ref": first_id}],
                "projected_delta": -reduction,
                "rationale": "MOCK 권고 — 근거 부족 속성은 판단을 보류했다",
            }],
            "projected": {
                "current_risk": risk_current,
                "projected_risk": risk_target,
                "reduction_pct": reduction,
                "target_met": True,
            },
            "optimality_gap_pct": None,
        },
        "provenance": {
            "measured_at": now, "model_version": MODEL_VERSION, "dict_version": DICT_VERSION,
        },
    }

    return {"input": stage2_input, "output": output}


def c1_checkpoint() -> None:
    """목 엔진은 체크포인트를 쓰지 않는다."""
    return None
