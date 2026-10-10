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


def test_c1_rules_merge_catches_explicit_age_and_place(monkeypatch):
    """C1_RULES=1 — 모델이 놓친 「마흔여덟이고 · 수원 · 영통구에」를 명시 규칙이 잡는다 (인스턴스 테스트 문장)."""
    sys.path.insert(0, str(ROOT / "experiments" / "exp06-finetune"))
    pytest.importorskip("torch")      # rules → train 이 torch 를 import 한다 (CI 에는 없다)
    pytest.importorskip("jsonschema")
    from apps.analyzer.engines import c1_rules

    def resolve(texts, candidate):  # level·subject 판정은 #306 — 여기서는 병합 경로만 본다
        return {"level": "explicit", "subject": "self"}

    text = "올해 마흔여덟이고 수원 영통구에 삽니다"

    class Empty:  # 모델이 아무것도 못 찾은 경우
        def predict_raw(self, record):
            return {"output_kind": "raw_bio_candidates_not_contract", "model_version": "v1", "record_type": "post",
                    "post_id": record["post_id"], "texts": {"body": record["body"]}, "candidates": []}

        def detect(self, record, resolver):
            raise AssertionError("규칙이 켜져 있으면 predict_raw 경로를 써야 한다")

    monkeypatch.setattr(c1_rules, "_ENABLED", True)
    out = c1_rules.detect(Empty(), {"post_id": "p1", "body": text}, resolve)
    got = {(s["text"], s["type"]) for s in out["spans"]}
    assert ("마흔여덟이고", "AGE") in got and ("영통구에", "LOC_ADMIN") in got
    assert out["model_version"] == "v1+rules"

    monkeypatch.setattr(c1_rules, "_ENABLED", False)

    class Plain(Empty):
        def detect(self, record, resolver):
            return {"spans": []}
    assert c1_rules.detect(Plain(), {"post_id": "p1", "body": text}, resolve) == {"spans": []}


def test_contribution_clue_ids_are_real_span_ids():
    """기여도 항목의 clue_ids · top_spans 가 실제 본인 span_id 를 가리킨다 — 타인 단서는 빠진다 (#303 리뷰)."""
    spans = {"p1": [_span("p1", 1, "마흔여덟", "AGE"), _span("p1", 2, "화정에서", "LOC_ADMIN", subject="other")],
             "p2": [_span("p2", 1, "해운대구", "LOC_ADMIN")]}
    contrib = _run("u_0000aaaa", POSTS[:2], spans)["contrib"]
    by_post = {c["post_id"]: c for c in contrib["output"]["contributions"]}
    assert by_post["p1"]["clue_ids"] == ["p1_s01"]
    assert by_post["p2"]["clue_ids"] == ["p2_s01"]
    for c in contrib["output"]["contributions"]:
        assert set(c["clue_ids"]) >= {s["span_id"] for s in c["top_spans"]}



def test_contribution_tolerates_duplicate_spans():
    """같은 스팬이 두 번 와도(1단·규칙 병합 중복 등) 기여도가 깨지지 않는다 (Codex 10/6)."""
    s = _span("p1", 1, "마흔여덟", "AGE")
    contrib = _run("u_0000aaaa", POSTS[:2], {"p1": [s, dict(s)]})["contrib"]
    row = next(c for c in contrib["output"]["contributions"] if c["post_id"] == "p1")
    assert row["clue_ids"] == ["p1_s01"] and row["top_spans"] == [{"span_id": "p1_s01", "text_id": "body"}]


def test_contribution_recompute_removed_posts():
    """비공개 조합 재계산 — 단서 글을 내리면 risk_after 가 0 이 된다 (#316 에서 옮김 · C 작성)."""
    spans = {"p1": [_span("p1", 1, "신갈동", "LOC_ADMIN")], "p2": []}
    posts = [_post("p1"), _post("p2")]
    spans_by_post = {p["post_id"]: {"spans": spans.get(p["post_id"], [])} for p in posts}
    out = c23.contribution("u_deadbeef", posts, spans_by_post=spans_by_post, removed_post_ids=["p1"])["output"]
    assert out["baseline_risk"] > 0
    assert out["risk_after"] == 0.0


def test_server_reports_direct_identifiers_per_channel(monkeypatch):
    """계정 링크 · 연락처는 스팬과 별개로 글마다 · 채널 이름(photo_caption:N)까지 화면과 같게 나온다."""
    pytest.importorskip("fastapi")
    from apps.analyzer import server
    from apps.analyzer.engines import mock

    for name, fn in (("detect_spans", lambda r: {"spans": []}), ("conditions", c23.conditions),
                     ("specificity", c23.specificity), ("contribution", c23.contribution),
                     ("per_post_k", c23.per_post_k), ("stage2", mock.stage2)):
        monkeypatch.setattr(server.engine, name, fn)
    posts = [{**_post("p1", "지난 글 https://blog.naver.com/abc_123 참고"), "photos": [{"caption": ""}, {"caption": "문의 010-1234-5678"}]},
             _post("p2", "링크 없는 글")]
    out = server._run_pipeline("u_0000aaaa", posts)
    p1 = out["direct_identifiers"]["p1"]
    assert [(f["text_id"], f["kind"]) for f in p1] == [("body", "account_url"), ("photo_caption:1", "phone")]
    assert out["direct_identifiers"]["p2"] == []


def test_server_reports_timeline_with_post_date(monkeypatch):
    """시점 역산(#331) — 본문 날짜가 없으면 export 의 post_date(#334)를 기준점으로 써서 여러 글의 같은 시작을 묶는다."""
    pytest.importorskip("fastapi")
    from apps.analyzer import server
    from apps.analyzer.engines import mock

    for name, fn in (("detect_spans", lambda r: {"spans": []}), ("conditions", c23.conditions),
                     ("specificity", c23.specificity), ("contribution", c23.contribution),
                     ("per_post_k", c23.per_post_k), ("stage2", mock.stage2)):
        monkeypatch.setattr(server.engine, name, fn)
    posts = [{**_post("p1", "워홀 3주차, 오늘은 바다"), "post_date": "2026-03-16"},
             {**_post("p2", "워홀 5주차 근황"), "post_date": "2026-03-30"},
             _post("p3", "워홀 9주차")]   # 작성일 없음(파일 업로드) → 기준점이 없어 빠진다
    out = server._run_pipeline("u_0000aaaa", posts)
    assert len(out["timeline"]) == 1
    g = out["timeline"][0]
    assert g["posts"] == ["p1", "p2"] and g["anchor"] == "post_date"
    assert g["start_range"][0] <= "2026-03-02" <= g["start_range"][1]
    assert server._run_pipeline("u_0000aaaa", [_post("p9", "차수 없는 글")])["timeline"] == []


def test_c1_defaults_are_baseline_v2():
    """앱 기본 = 기준선 v2(재학습 체크포인트 + 명시 규칙 켬) — exp17c 를 잰 구성과 같아야 한다 (#310 · #322).
    모듈을 reload 하지 않고 해석 함수만 본다 — 다른 테스트에 상태가 새지 않게 (Codex 10/9)"""
    from apps.analyzer.engines import c1_rules

    assert all(c1_rules.parse(v) for v in (None, "", "1", "on", "yes"))
    assert not any(c1_rules.parse(v) for v in ("0", "false", "OFF", " no "))
    src = (ROOT / "apps" / "analyzer" / "engines" / "real.py").read_text(encoding="utf-8")
    assert '"variant_base_20261008" / "checkpoint-epoch-10"' in src
