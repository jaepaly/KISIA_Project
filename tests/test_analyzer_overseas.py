"""해외 거주로 보이면 사는 곳은 국내 인구 기준으로 추정하지 않는다 — 서버 파이프라인 끝까지 (합성 문장만).

- 위치 단서(LOC_ADMIN · LOC_FACILITY · 위치 태그)가 k · 위험도 · 2단 location 에서 빠지고 location 은 abstain
- 나이 · 직업 등 나머지는 그대로 · 화면용 residence 키 · 원래 스팬은 하이라이트용으로 그대로
- 여행만 다녀온 국내 거주자는 그대로
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

from apps.analyzer import server  # noqa: E402
from apps.analyzer.engines import c23  # noqa: E402
from kopl.c4_stage2.infer import analyze  # noqa: E402


def _post(pid: str, body: str, geo_tag: str | None = None) -> dict:
    return {"post_id": pid, "title": None, "body": body, "photos": [],
            "activity_meta": {"nickname": None, "geo_tag": geo_tag, "post_time": None}}


def _span(pid: str, n: int, body: str, text: str, stype: str, level: str = "explicit") -> dict:
    start = body.index(text)
    return {"span_id": f"{pid}_s{n:02d}", "text_id": "body", "start": start, "end": start + len(text), "text": text,
            "type": stype, "level": level, "subject": "self"}


# 미국 거주자 — 「예산」은 지명과 글자가 같은 일반 낱말인데 1단이 LOC_ADMIN 으로 잡았다고 친다
US = [
    ("p1", "미국에서 지내다 보니 예산 짜는 게 제일 어렵다. 마흔두 살 아빠의 가계부."),
    ("p2", "미국생활 4년 차, 간호사 면허 공부를 다시 시작했다."),
    ("p3", "주말에는 시애틀 해안가를 걸었다."),
]
KR = [
    ("p1", "뉴욕 여행 다녀왔다. 예산 짜는 게 제일 어렵다. 마흔두 살 아빠의 가계부."),
    ("p2", "망원동에 산 지 4년, 간호사 면허 공부를 다시 시작했다."),
    ("p3", "주말에는 한강을 걸었다."),
]


def _spans(rows) -> dict:
    out = {}
    for pid, body in rows:
        s = []
        for text, stype in (("예산", "LOC_ADMIN"), ("마흔두 살", "AGE"), ("간호사", "JOB"), ("망원동", "LOC_ADMIN"),
                            ("시애틀", "LOC_ADMIN")):
            if text in body:
                s.append(_span(pid, len(s) + 1, body, text, stype))
        out[pid] = s
    return out


def _rules_stage2(user_ref, posts, risk_current=0.0, risk_target=40.0, *, spans_by_post=None, detect_inputs=None):
    entries = [{"post_id": p["post_id"], "texts": {"body": p["body"]}, "spans": spans_by_post[p["post_id"]]["spans"],
                "geo_tag": (p.get("activity_meta") or {}).get("geo_tag")} for p in posts]
    return {"input": {}, "output": analyze(user_ref, entries, mode="rules")}


def _run(monkeypatch, rows, geo_tag=None):
    spans = _spans(rows)
    for name, fn in (("detect_spans", lambda r: {"spans": spans[r["post_id"]]}), ("conditions", c23.conditions),
                     ("specificity", c23.specificity), ("contribution", c23.contribution),
                     ("per_post_k", c23.per_post_k), ("projected_k", c23.projected_k), ("stage2", _rules_stage2)):
        monkeypatch.setattr(server.engine, name, fn)
    posts = [_post(pid, body, geo_tag if i == 0 else None) for i, (pid, body) in enumerate(rows)]
    return server._run_pipeline("u_0000aaaa", posts)


def _axes(out) -> set[str]:
    return {c["axis"] for c in out["specificity"]["input"]["conditions"]}


def test_overseas_drops_location_but_keeps_other_clues(monkeypatch):
    out = _run(monkeypatch, US, geo_tag="충청남도 예산군")
    res = out["residence"]
    assert res["overseas"] and res["country"] == "미국" and res["location_excluded"]
    assert [e["value"] for e in res["evidence"]] == ["미국에서 지내다 보", "미국생활"]
    # 위치 조건(「예산」 · 위치 태그)이 k 에서 빠지고 나이 · 직업은 남는다
    assert "location" not in _axes(out)
    assert {"age", "occupation"} <= _axes(out)
    findings = out["stage2"]["output"]["findings"]
    assert findings["location"]["verdict"] == "abstain" and findings["location"]["evidence"] == []
    assert findings["age"]["verdict"] == "specified" and findings["occupation"]["verdict"] == "specified"
    # 위치 태그 지우기 같은 위치 조치를 추천하지 않는다
    assert all(a["action_type"] != "activity_meta" for a in out["stage2"]["output"]["recommendation"]["actions"])
    # 화면 하이라이트용 원래 스팬은 그대로
    assert any(s["type"] == "LOC_ADMIN" for s in out["spans"]["p1"]["spans"])


def test_overseas_output_still_matches_contracts(monkeypatch):
    jsonschema = pytest.importorskip("jsonschema")
    out = _run(monkeypatch, US)
    for name, doc in (("specificity", out["specificity"]), ("contribution", out["contribution"])):
        schema = json.loads((ROOT / "docs" / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(doc)
    schema = json.loads((ROOT / "docs" / "contracts" / "stage2-io.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(out["stage2"]["output"], {"$defs": schema["$defs"], "$ref": "#/$defs/Stage2Output"})


def test_korean_traveller_keeps_location(monkeypatch):
    out = _run(monkeypatch, KR, geo_tag="서울특별시 마포구 망원동")
    assert not out["residence"]["overseas"] and out["residence"]["evidence"] == []
    assert "location" in _axes(out)
    assert out["stage2"]["output"]["findings"]["location"]["verdict"] == "specified"


def test_mock_stage2_location_is_abstained_when_overseas(monkeypatch):
    """목 엔진은 location 을 늘 narrowed 로 심는다 — 해외면 서버가 abstain 으로 덮는다."""
    from apps.analyzer.engines import mock

    spans = _spans(US)
    for name, fn in (("detect_spans", lambda r: {"spans": spans[r["post_id"]]}), ("stage2", mock.stage2)):
        monkeypatch.setattr(server.engine, name, fn)
    out = server._run_pipeline("u_0000aaaa", [_post(pid, body) for pid, body in US])
    assert out["residence"]["overseas"]
    assert out["stage2"]["output"]["findings"]["location"]["verdict"] == "abstain"
