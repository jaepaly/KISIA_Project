"""분석 앱 파이프라인 끝까지 — 1단만 정해진 스팬으로 바꾸고 C2·C3 는 실제 엔진(apps/analyzer/engines/c23.py).

데모 피드백 「여러 글을 엮지 못하고 k 가 다 똑같다」가 다시 생기지 않게 고정한다.
- 사람마다 k 가 다르다 · 글이 쌓이면 k 가 내려간다 · 타인 단서(subject=other)는 k 를 좁히지 않는다
- 위치태그가 조건이 된다 · 응답이 계약 스키마(specificity · contribution)를 통과한다
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from apps.analyzer.engines import c23  # noqa: E402


def _span(pid: str, n: int, text: str, stype: str, level: str = "explicit", subject: str = "self") -> dict:
    return {"span_id": f"{pid}_s{n:02d}", "text_id": "body", "start": 0, "end": len(text), "text": text,
            "type": stype, "level": level, "subject": subject}


def _post(pid: str, body: str = "", geo_tag: str | None = None) -> dict:
    return {"post_id": pid, "title": None, "body": body, "photos": [],
            "activity_meta": {"nickname": None, "geo_tag": geo_tag, "post_time": None}}


def _run(user_ref: str, posts: list[dict], spans: dict[str, list[dict]]) -> dict:
    spans_by_post = {p["post_id"]: {"spans": spans.get(p["post_id"], [])} for p in posts}
    conds = c23.conditions(posts, spans_by_post)
    return {"spec": c23.specificity({"user_ref": user_ref, "conditions": conds}),
            "contrib": c23.contribution(user_ref, posts, spans_by_post=spans_by_post),
            "k_by_post": c23.per_post_k(posts, spans_by_post)}


def _k(out: dict) -> float | None:
    return out["spec"]["output"]["k"]


# 사용자 한 명이 글을 하나씩 더 쓴다 — 동네 · 나이 · 성별 · 직업
POSTS = [_post("p1"), _post("p2"), _post("p3"), _post("p4")]
SPANS = {
    "p1": [_span("p1", 1, "역삼동에서", "LOC_ADMIN")],
    "p2": [_span("p2", 1, "마흔여덟", "AGE")],
    "p3": [_span("p3", 1, "남편이", "SEX", level="implicit")],
    "p4": [_span("p4", 1, "간호사", "JOB")],
}


def test_k_drops_as_posts_accumulate():
    ks = [_k(_run("u_0000aaaa", POSTS[:n], SPANS)) for n in range(1, 5)]
    assert all(k is not None for k in ks), ks
    assert ks == sorted(ks, reverse=True) and ks[-1] < ks[0], ks


def test_different_people_get_different_k():
    a = _k(_run("u_0000aaaa", POSTS, SPANS))
    other = {"p1": [_span("p1", 1, "해운대구", "LOC_ADMIN")], "p2": [_span("p2", 1, "스물셋", "AGE")]}
    b = _k(_run("u_0000bbbb", POSTS[:2], other))
    assert a != b


def test_other_subject_clue_does_not_narrow():
    """「친구가 [화정에서] 공방 한다」 — 타인 단서는 내 k 를 좁히지 않는다."""
    mine = {"p1": [_span("p1", 1, "마흔여덟", "AGE")]}
    with_friend = {"p1": mine["p1"] + [_span("p1", 2, "화정에서", "LOC_ADMIN", subject="other")]}
    assert _k(_run("u_0000aaaa", POSTS[:1], mine)) == _k(_run("u_0000aaaa", POSTS[:1], with_friend))


def test_geo_tag_becomes_condition():
    no_tag = _k(_run("u_0000aaaa", [_post("p1")], {"p1": [_span("p1", 1, "마흔여덟", "AGE")]}))
    tagged = _k(_run("u_0000aaaa", [_post("p1", geo_tag="강남구 역삼동")], {"p1": [_span("p1", 1, "마흔여덟", "AGE")]}))
    assert tagged is not None and (no_tag is None or tagged < no_tag)


def test_no_clue_keeps_contract_and_unknown_k():
    out = _run("u_0000aaaa", POSTS[:2], {})
    assert out["spec"]["input"]["conditions"]                    # minItems 1
    assert out["spec"]["output"]["k_level"] == "UNKNOWN"


def test_per_post_k_ranks_identifying_post_first():
    kp = _run("u_0000aaaa", POSTS, SPANS)["k_by_post"]
    assert kp["per_post"][0]["post_id"] == "p1"                 # 동네를 짚는 글
    assert all(r["k_without"] >= kp["k"] for r in kp["per_post"])


def test_contracts_validate():
    jsonschema = pytest.importorskip("jsonschema")
    out = _run("u_0000aaaa", POSTS, SPANS)
    for name, doc in (("specificity", out["spec"]), ("contribution", out["contrib"])):
        schema = json.loads((ROOT / "docs" / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(doc)
    assert out["contrib"]["output"]["contributions"][0]["post_id"] in {"p1", "p2", "p3", "p4"}


def test_server_pipeline_end_to_end(monkeypatch):
    """서버 _run_pipeline — 제목·캡션이 1단에 넘어가고, k·기여도·글별 k 가 실제 엔진에서 나온다."""
    pytest.importorskip("fastapi")
    from apps.analyzer import server
    from apps.analyzer.engines import mock

    seen = []

    def fake_detect(record: dict) -> dict:
        seen.append(record)
        return {"spans": SPANS.get(record["post_id"], [])}

    for name, fn in (("detect_spans", fake_detect), ("conditions", c23.conditions), ("specificity", c23.specificity),
                     ("contribution", c23.contribution), ("per_post_k", c23.per_post_k), ("stage2", mock.stage2)):
        monkeypatch.setattr(server.engine, name, fn)
    posts = [dict(p) for p in POSTS]
    posts[0] = {**posts[0], "title": "제목", "photos": [{"caption": "캡션"}]}
    out = server._run_pipeline("u_0000aaaa", posts)
    assert seen[0]["title"] == "제목" and seen[0]["photo_captions"] == ["캡션"]
    assert out["specificity"]["output"]["k"] is not None
    assert out["k_by_post"]["per_post"][0]["post_id"] == "p1"


def test_upload_user_ref_matches_contract():
    from apps.analyzer.adapters import file_adapter
    import re
    data = file_adapter.load_from_bytes("첫 글\n둘째 글".encode("utf-8"), "a.txt")
    assert re.fullmatch(r"u_[0-9a-f]{8,}", data["user_ref"])
    assert {p["user_ref"] for p in data["posts"]} == {data["user_ref"]}


# ── Codex 검토 반례
def test_zero_posts_render_without_error():
    """e-integration §4 「글 0편인 작성자 — 화면이 에러 없이」."""
    jsonschema = pytest.importorskip("jsonschema")
    out = _run("u_0000aaaa", [], {})
    for name, doc in (("specificity", out["spec"]), ("contribution", out["contrib"])):
        schema = json.loads((ROOT / "docs" / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(doc)
    assert out["spec"]["output"]["k"] is None


def test_server_rejects_duplicate_post_ids_and_keeps_caption_index():
    pytest.importorskip("fastapi")
    from fastapi import HTTPException
    from apps.analyzer import server
    with pytest.raises(HTTPException) as e:
        server._check_posts([_post("p1"), _post("p1")])
    assert e.value.status_code == 400
    rec = server._detect_input({"post_id": "p1", "body": "", "photos": [{"caption": ""}, {"caption": "역삼동"}]})
    assert rec["photo_captions"] == ["", "역삼동"]                # 빈 캡션도 자리 유지 → photo_caption:1


def test_upload_limits_keep_file_in_memory():
    """1MB 초과는 413 — 멀티파트 해석기가 디스크 임시 파일로 넘기기 전에 막는다. 빈 업로드는 에러 없이."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from apps.analyzer import server
    c = TestClient(server.app)
    big = c.post("/upload", files={"file": ("a.txt", b"a" * 1_048_577)})
    assert big.status_code == 413
    ok = c.post("/upload", files={"file": ("a.txt", "첫 글\n둘째 글".encode("utf-8"))})
    assert ok.status_code == 200 and len(ok.json()["posts"]) == 2

    def chunks():  # 길이를 미리 밝히지 않는 전송(chunked) — 헤더가 아니라 받은 바이트로 막는다
        boundary = b"--b0"
        yield boundary + b'\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n\r\n'
        for _ in range(11):
            yield b"a" * 100_000
        yield b"\r\n" + boundary + b"--\r\n"
    streamed = c.post("/upload", content=chunks(), headers={"content-type": "multipart/form-data; boundary=b0"})
    assert streamed.status_code == 413
    empty = c.post("/upload", files={"file": ("a.txt", b"")})
    assert empty.status_code == 200 and empty.json()["posts"] == []
