"""결정 단서 확인(「내 얘기 아님」) — /api/recompute 가 뺀 단서 없이 k · 위험도를 다시 센다 (합성 문장만).

- 처음 점검 응답에 결정 단서(decisive_clues)와 근거 스팬이 실린다
- 단서를 빼면 그 축의 다음 후보(「교수님」 → 「병원에서 일한다」)가 올라오고 k 가 커진다 · 2단 출력은 다시 만들지 않는다
- 같은 값의 스팬은 여러 글에 있어도 한 단서로 묶인다 · 위치 태그도 뺄 수 있다
- 해외 거주로 보이면 다시 셀 때도 위치 단서를 넣지 않는다 · 형식이 어긋난 입력은 400
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from apps.analyzer import server  # noqa: E402
from apps.analyzer.engines import c23  # noqa: E402
from kopl.c4_stage2.infer import analyze  # noqa: E402

USER = "u_0000aaaa"


def _post(pid: str, body: str, geo_tag: str | None = None) -> dict:
    return {"post_id": pid, "title": None, "body": body, "photos": [],
            "activity_meta": {"nickname": None, "geo_tag": geo_tag, "post_time": None}}


def _span(pid: str, n: int, body: str, text: str, stype: str, level: str = "explicit") -> dict:
    start = body.index(text)
    return {"span_id": f"{pid}_s{n:02d}", "text_id": "body", "start": start, "end": start + len(text), "text": text,
            "type": stype, "level": level, "subject": "self"}


# 「교수님 주관」은 남의 직업인데 1단이 본인 직업으로 잡았다고 친다 — k 엔진은 직업 축에서 후보가 더 적은 「교수님」을 고른다
ROWS = [
    ("p1", "망원동에 산 지 4년. 교수님 주관 파티에 다녀왔다."),
    ("p2", "서른여덟 살 엄마의 가계부."),
    ("p3", "병원에서 일한다. 오늘도 교수님 회진이 길었다."),
]
SPANS = {
    "p1": [("망원동", "LOC_ADMIN", "explicit"), ("교수님", "JOB", "explicit")],
    "p2": [("서른여덟 살", "AGE", "explicit"), ("엄마", "SEX", "implicit")],
    "p3": [("병원에서 일한다", "JOB", "implicit"), ("교수님", "JOB", "explicit")],
}
US = [
    ("p1", "미국에서 지내다 보니 예산 짜는 게 제일 어렵다. 서른여덟 살 엄마의 가계부."),
    ("p2", "미국생활 4년 차, 간호사 면허 공부를 다시 시작했다."),
    ("p3", "주말에는 시카고 호숫가를 걸었다."),
]
US_SPANS = {"p1": [("예산", "LOC_ADMIN", "explicit"), ("서른여덟 살", "AGE", "explicit")],
            "p2": [("간호사", "JOB", "explicit")], "p3": [("시카고", "LOC_ADMIN", "explicit")]}


def _spans(rows, table) -> dict:
    return {pid: [_span(pid, i + 1, body, t, ty, lv) for i, (t, ty, lv) in enumerate(table[pid])] for pid, body in rows}


def _rules_stage2(user_ref, posts, risk_current=0.0, risk_target=40.0, *, spans_by_post=None, detect_inputs=None):
    entries = [{"post_id": p["post_id"], "texts": {"body": p["body"]}, "spans": spans_by_post[p["post_id"]]["spans"],
                "geo_tag": (p.get("activity_meta") or {}).get("geo_tag")} for p in posts]
    return {"input": {}, "output": analyze(user_ref, entries, mode="rules")}


@pytest.fixture
def real_k(monkeypatch):
    """1단은 정해진 스팬 · C2 · C3 는 실제 엔진 · 2단은 규칙. 2단을 다시 부르면 실패하게 둔다(다시 계산은 2단을 안 부른다)."""
    calls = {"stage2": 0}

    def stage2(*a, **kw):
        calls["stage2"] += 1
        return _rules_stage2(*a, **kw)

    for name, fn in (("conditions", c23.conditions), ("specificity", c23.specificity), ("contribution", c23.contribution),
                     ("per_post_k", c23.per_post_k), ("projected_k", c23.projected_k),
                     ("decisive_clues", c23.decisive_clues), ("stage2", stage2)):
        monkeypatch.setattr(server.engine, name, fn)
    return calls


def _scan(monkeypatch, rows, table, geo_tag=None) -> dict:
    spans = _spans(rows, table)
    monkeypatch.setattr(server.engine, "detect_spans", lambda r: {"spans": spans[r["post_id"]]})
    posts = [_post(pid, body, geo_tag if i == 0 else None) for i, (pid, body) in enumerate(rows)]
    return server._run_pipeline(USER, posts)


def _body(out: dict, exclude: list[dict]) -> dict:
    """화면(diagnosis.html)이 보내는 모양 그대로 — sessionStorage 의 처음 결과 + 뺄 단서."""
    return {"user_ref": out["user_ref"], "posts": out["posts"], "spans": out["spans"],
            "stage2_output": out["stage2"]["output"], "exclude": exclude}


def _clue(out: dict, axis: str) -> dict:
    return next(c for c in out["decisive_clues"] if c["axis"] == axis)


def _refs(clue: dict) -> list[dict]:
    return [{"post_id": s["post_id"], "span_id": s["span_id"]} if "span_id" in s
            else {"post_id": s["post_id"], "geo_tag": True} for s in clue["sources"]]


def test_scan_lists_decisive_clues_with_sources(monkeypatch, real_k):
    out = _scan(monkeypatch, ROWS, SPANS)
    axes = [c["axis"] for c in out["decisive_clues"]]
    assert {"location", "age", "sex", "occupation"} <= set(axes)
    job = _clue(out, "occupation")
    # 직업 축은 「교수님」이 정했다 — 같은 말이 두 글에 있어 근거 스팬 둘을 한 단서로 묶는다
    assert job["value"] == "교수님"
    assert sorted((s["post_id"], s["text"]) for s in job["sources"]) == [("p1", "교수님"), ("p3", "교수님")]


def test_excluding_a_clue_raises_k_and_promotes_next_candidate(monkeypatch, real_k):
    out = _scan(monkeypatch, ROWS, SPANS)
    assert real_k["stage2"] == 1
    client = TestClient(server.app)
    r = client.post("/api/recompute", json=_body(out, _refs(_clue(out, "occupation"))))
    assert r.status_code == 200, r.text
    new = r.json()
    assert real_k["stage2"] == 1   # 2단은 다시 돌리지 않는다
    assert new["clue_exclusions"] == {"n_spans": 2, "n_geo_tags": 0}
    assert new["specificity"]["output"]["k"] > out["specificity"]["output"]["k"]
    # 직업 축의 다음 후보(돌려 쓴 표현이라 덜 좁힌다)가 올라온다 — 반복 확인할 수 있게 결정 단서 목록도 새로
    assert _clue(new, "occupation")["value"] == "병원에서 일한다"
    assert "교수님" not in json.dumps(new["specificity"]["input"]["conditions"], ensure_ascii=False)
    # 위험도도 다시 센다 (직업 단서가 하나 줄어도 남은 직업 단서가 있어 같거나 낮다)
    assert new["contribution"]["output"]["baseline_risk"] <= out["contribution"]["output"]["baseline_risk"]
    # 빼는 것이 없으면 처음 점검과 같은 값
    same = client.post("/api/recompute", json=_body(out, [])).json()
    assert same["specificity"]["output"]["k"] == out["specificity"]["output"]["k"]
    assert same["decisive_clues"] == out["decisive_clues"]
    assert same["contribution"]["output"]["baseline_risk"] == out["contribution"]["output"]["baseline_risk"]


def test_recompute_output_matches_contracts(monkeypatch, real_k):
    jsonschema = pytest.importorskip("jsonschema")
    out = _scan(monkeypatch, ROWS, SPANS)
    new = TestClient(server.app).post("/api/recompute", json=_body(out, _refs(_clue(out, "location")))).json()
    for name in ("specificity", "contribution"):
        schema = json.loads((ROOT / "docs" / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(new[name])


def test_geo_tag_can_be_excluded(monkeypatch, real_k):
    rows = [("p1", "서른여덟 살 엄마의 가계부.")]
    out = _scan(monkeypatch, rows, {"p1": [("서른여덟 살", "AGE", "explicit")]}, geo_tag="서울특별시 마포구 망원동")
    loc = _clue(out, "location")
    assert loc["sources"] == [{"post_id": "p1", "geo_tag": "서울특별시 마포구 망원동"}]
    new = TestClient(server.app).post("/api/recompute", json=_body(out, _refs(loc))).json()
    assert new["clue_exclusions"] == {"n_spans": 0, "n_geo_tags": 1}
    assert all(c["axis"] != "location" for c in new["specificity"]["input"]["conditions"])
    assert new["specificity"]["output"]["k"] > out["specificity"]["output"]["k"]


def test_overseas_recompute_keeps_location_out(monkeypatch, real_k):
    out = _scan(monkeypatch, US, US_SPANS)
    assert out["residence"]["overseas"]
    assert all(c["axis"] != "location" for c in out["decisive_clues"])
    new = TestClient(server.app).post("/api/recompute", json=_body(out, _refs(_clue(out, "age")))).json()
    assert new["residence"]["overseas"] and new["residence"]["location_excluded"]
    axes = {c["axis"] for c in new["specificity"]["input"]["conditions"]}
    assert "location" not in axes and "age" not in axes and "occupation" in axes


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(user_ref="nobody"),
    lambda b: b.update(posts="x"),
    lambda b: b.update(spans={"p1": {"spans": [{"span_id": "a"}]}}),
    lambda b: b.update(exclude=[{"post_id": "p1"}]),
    lambda b: b.update(exclude="all"),
    lambda b: b.update(stage2_output={"recommendation": {"actions": 1}}),
    lambda b: b.update(stage2_output={"rewrites": 1}),
    lambda b: b["spans"]["p1"]["spans"][0].update(level="sure"),
    lambda b: b["spans"]["p1"]["spans"][0].update(start=-1),
])
def test_malformed_input_is_400(monkeypatch, real_k, mutate):
    out = _scan(monkeypatch, ROWS, SPANS)
    body = _body(out, [])
    mutate(body)
    r = TestClient(server.app).post("/api/recompute", json=body)
    assert r.status_code == 400 and "형식" in r.json()["detail"]


def test_not_json_is_400():
    r = TestClient(server.app).post("/api/recompute", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_cross_origin_recompute_is_rejected():
    r = TestClient(server.app).post("/api/recompute", json={}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
