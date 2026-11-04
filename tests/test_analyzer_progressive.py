"""빠른 결과 먼저 · 2단 모델 판정 뒤따라 — 계정 점검의 체감 대기 시간 줄이기.

?progressive=1 로 부르면 모델을 쓸 수 있는 서버만 2단을 규칙으로 먼저 내고(stage2_followup), 같은 점검의 모델 판정은
/api/stage2-followup 으로 받는다. 모델을 못 쓰는 서버(STAGE2_MODE=rules · GPU 없음 · 목 기본)는 지금과 똑같은 한 번 응답.
GPU 는 쓰지 않는다 — 모델은 가짜 지연 함수로 바꾼다.

    python -m pytest -q --import-mode=importlib tests/test_analyzer_progressive.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from apps.analyzer import server  # noqa: E402
from apps.analyzer.engines import mock  # noqa: E402

BODY = "저수지 산책하고 퇴근길에 첫째 아이 데리러 감\n역 앞 카페에서 출근 전 커피"


def _txt(text: str = BODY):
    return {"file": ("a.txt", text.encode("utf-8"))}


@pytest.fixture
def fresh(monkeypatch):
    """테스트마다 새 입장 제한 · 새 뒤따름 작업 표"""
    monkeypatch.setattr(server, "_admission", server._Admission(1, 3, 5.0))
    fol = server._Followups(4, 600.0, 1.0)
    monkeypatch.setattr(server, "_followups", fol)
    return fol


def _fake_model(monkeypatch, delay=0.4, result="model", gate: threading.Event | None = None):
    """가짜 지연 모델 — 목 엔진의 stage2_followup 을 그대로 쓰되 지연 · 결과를 정한다"""
    monkeypatch.setenv("MOCK_STAGE2_DELAY", str(delay))
    monkeypatch.setenv("MOCK_STAGE2_RESULT", result)
    calls = []

    def fake(*a, **k):
        calls.append(time.monotonic())
        if gate is not None:
            assert gate.wait(10)
        return mock.stage2_followup(*a, **k)
    monkeypatch.setattr(server.engine, "stage2_followup_available", lambda: True)
    monkeypatch.setattr(server.engine, "stage2_followup", fake)
    return calls


def _wait(c, job, until=("done", "fallback", "failed", "unknown"), timeout=10.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        q = c.get(f"/api/stage2-followup?job={job}").json()
        if q["status"] in until:
            return q
        time.sleep(0.05)
    raise AssertionError("뒤따르는 판정이 끝나지 않았다")


def _validate_output(output: dict) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "docs" / "contracts" / "stage2-io.schema.json").read_text(encoding="utf-8"))
    sub = {"$defs": schema["$defs"], "$ref": "#/$defs/Stage2Output"}
    jsonschema.Draft202012Validator(sub).validate(output)


# ── 모델을 못 쓰는 서버 — 지금과 똑같다
def test_without_model_progressive_is_plain_single_response(fresh, monkeypatch):
    monkeypatch.delenv("MOCK_STAGE2_DELAY", raising=False)
    assert server.engine.stage2_followup_available() is False   # 목 기본값 = 꺼짐
    c = TestClient(server.app)
    plain = c.post("/upload", files=_txt()).json()
    prog = c.post("/upload?progressive=1", files=_txt()).json()
    assert "stage2_followup" not in plain and "stage2_followup" not in prog
    assert prog["stage2"]["output"]["findings"] == plain["stage2"]["output"]["findings"]
    assert set(prog) == set(plain)


def test_real_engine_followup_off_when_rules_or_no_model(monkeypatch, tmp_path):
    real = _load_real(monkeypatch, tmp_path, "rules")
    assert real.stage2_followup_available() is False
    real = _load_real(monkeypatch, tmp_path, "auto", model=None)       # GPU · 어댑터 없음 = 로드 실패
    assert real.stage2_followup_available() is False
    real = _load_real(monkeypatch, tmp_path, "model", model=object())  # 모델만 — 지금처럼 한 번에
    assert real.stage2_followup_available() is False
    real = _load_real(monkeypatch, tmp_path, "auto", model=object())
    assert real.stage2_followup_available() is True


# ── 빠른 결과 먼저 → 모델 판정 뒤따라
def test_fast_result_first_then_model_findings(fresh, monkeypatch):
    calls = _fake_model(monkeypatch, delay=0.6)
    seen_modes = []
    orig = server.engine.stage2

    def spy(*a, **k):
        seen_modes.append(k.get("mode"))
        return orig(*a, **k)
    monkeypatch.setattr(server.engine, "stage2", spy)
    c = TestClient(server.app)
    t0 = time.monotonic()
    r = c.post("/upload?progressive=1", files=_txt())
    took = time.monotonic() - t0
    assert r.status_code == 200
    d = r.json()
    assert seen_modes == ["rules"]                              # 빠른 결과는 규칙으로
    assert took < 0.6                                           # 가짜 모델(0.6초)을 기다리지 않았다
    fol = d["stage2_followup"]
    assert fol["status"] == "pending" and len(fol["job"]) >= 16 and fol["est_seconds"] > 0
    q = _wait(c, fol["job"])
    assert q["status"] == "done" and q["model_version"] == "mock-model-0.1.0" and len(calls) == 1
    # 모델 판정은 규칙과 다르다(가짜 모델) · 계약 Finding 모양 그대로
    assert q["findings"]["location"]["verdict"] == "specified" != d["stage2"]["output"]["findings"]["location"]["verdict"]
    assert q["findings"]["family"]["verdict"] == "narrowed"
    _validate_output({**d["stage2"]["output"], "findings": q["findings"]})
    # 응답 계약 칸은 그대로 — stage2_followup 은 최상위 화면 전용 칸
    _validate_output(d["stage2"]["output"])
    assert c.get(f"/api/stage2-followup?job={fol['job']}").headers["cache-control"] == "no-store"


def test_scan_route_passes_progressive(fresh, monkeypatch):
    _fake_model(monkeypatch, delay=0.05)
    monkeypatch.setattr(server.sns_adapter, "load", lambda user_ref, base, session_id=None:
                        {"posts": [{"post_id": "p1", "body": BODY}]})
    c = TestClient(server.app)
    assert "stage2_followup" not in c.post("/scan/u_0000aaaa").json()   # 묻지 않으면 지금과 같다
    d = c.post("/scan/u_0000aaaa?progressive=1").json()
    assert _wait(c, d["stage2_followup"]["job"])["status"] == "done"


def test_fallback_and_failure_are_reported(fresh, monkeypatch):
    _fake_model(monkeypatch, delay=0.01, result="fallback")
    c = TestClient(server.app)
    q = _wait(c, c.post("/upload?progressive=1", files=_txt()).json()["stage2_followup"]["job"])
    assert q == {"status": "fallback", "reason": "CUDA GPU 없음"}
    monkeypatch.setenv("MOCK_STAGE2_RESULT", "error")
    q = _wait(c, c.post("/upload?progressive=1", files=_txt()).json()["stage2_followup"]["job"])
    assert q == {"status": "failed"}                                # 예외 원문은 내지 않는다


def test_unknown_and_bad_job_ids(fresh):
    c = TestClient(server.app)
    assert c.get("/api/stage2-followup?job=" + "a" * 24).json() == {"status": "unknown"}
    assert c.get("/api/stage2-followup?job=short").status_code == 422
    assert c.get("/api/stage2-followup?job=" + "a" * 20 + "%2F..").status_code == 422


def test_results_expire_after_ttl(monkeypatch):
    fol = server._Followups(4, 0.2, 1.0)
    out = fol.submit(lambda: {"used_model": True, "findings": {}, "model_version": "m"})
    for _ in range(100):
        if fol.poll(out["job"])["status"] == "done":
            break
        time.sleep(0.02)
    assert fol.poll(out["job"])["status"] == "done"
    time.sleep(0.3)
    assert fol.poll(out["job"]) == {"status": "unknown"}


def test_queue_cap_skips_and_reports_ahead(fresh, monkeypatch):
    gate = threading.Event()
    _fake_model(monkeypatch, delay=0.0, gate=gate)
    fresh.max_jobs = 2
    c = TestClient(server.app)
    a = c.post("/upload?progressive=1", files=_txt()).json()["stage2_followup"]
    b = c.post("/upload?progressive=1", files=_txt()).json()["stage2_followup"]
    s = c.post("/upload?progressive=1", files=_txt()).json()["stage2_followup"]
    assert s == {"status": "skipped"}                                # 꽉 차면 빠른 결과만 — 기다리지 않는다
    assert b["ahead"] == 1 and b["est_seconds"] >= a["est_seconds"]
    assert c.get(f"/api/stage2-followup?job={b['job']}").json()["ahead"] == 1
    gate.set()
    assert _wait(c, a["job"])["status"] == "done" and _wait(c, b["job"])["status"] == "done"


def test_model_work_never_overlaps_on_gpu(fresh, monkeypatch):
    """뒤따르는 판정과 한 번에 응답하는 점검(progressive 없음 · Veilo)의 2단이 GPU 에서 겹치지 않는다"""
    running, peak, lock = [0], [0], threading.Lock()

    def busy(sleep):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(sleep)
        with lock:
            running[0] -= 1
    orig_stage2 = server.engine.stage2

    def slow_stage2(*a, **k):
        if k.get("mode") != "rules":
            busy(0.3)
        return orig_stage2(*a, **k)
    monkeypatch.setattr(server.engine, "stage2", slow_stage2)
    monkeypatch.setattr(server.engine, "stage2_followup_available", lambda: True)
    monkeypatch.setattr(server.engine, "stage2_followup", lambda *a, **k: busy(0.3) or mock.stage2_followup(*a, **k))
    monkeypatch.setenv("MOCK_STAGE2_DELAY", "0")
    with TestClient(server.app) as c:
        job = c.post("/upload?progressive=1", files=_txt()).json()["stage2_followup"]["job"]
        assert c.post("/upload", files=_txt()).status_code == 200    # GPU 자리를 기다렸다가 돈다
        assert _wait(c, job)["status"] == "done"
    assert peak[0] == 1


def test_followup_keeps_overseas_location_abstained(fresh, monkeypatch):
    _fake_model(monkeypatch, delay=0.0)
    monkeypatch.setattr(server, "find_residence", lambda *a, **k: {"overseas": True, "country": "US", "rule": "x",
                                                                   "posts": {}, "evidence": []})
    c = TestClient(server.app)
    d = c.post("/upload?progressive=1", files=_txt()).json()
    q = _wait(c, d["stage2_followup"]["job"])
    assert q["findings"]["location"]["verdict"] == "abstain" and q["findings"]["location"]["evidence"] == []


def test_fast_and_full_scan_rates_are_learned_separately(monkeypatch):
    monkeypatch.setattr(server, "_scan_rate", {"ms_per_char": 1.0, "samples": 0})
    monkeypatch.setattr(server, "_fast_rate", {"ms_per_char": 1.0, "samples": 0})
    server._learn_rate(10_000, 11.0, fast=True)
    server._learn_rate(10_000, 69.0)
    assert server._estimate(10_000, fast=True)["seconds"] == pytest.approx(11.0)
    assert server._estimate(10_000)["seconds"] == pytest.approx(69.0)


# ── 실제 엔진(real.py) — 가짜 1단 · 가짜 2단 모델로
def _load_real(monkeypatch, tmp_path, stage2_mode, model=None):
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir(exist_ok=True)
    (ckpt / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("C1_CHECKPOINT_DIR", str(ckpt))
    monkeypatch.setenv("STAGE2_MODE", stage2_mode)
    monkeypatch.setenv("TORCH_THREADS", "0")
    from kopl.c1_span import infer
    from kopl.c4_stage2 import infer as s2
    monkeypatch.setattr(infer, "SpanDetector", lambda *a, **k: object())
    monkeypatch.setattr(s2, "_get_model", lambda: model)              # GPU 를 쓰지 않는다
    spec = importlib.util.spec_from_file_location("apps.analyzer.engines._real_progressive",
                                                  ROOT / "apps" / "analyzer" / "engines" / "real.py")
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    return real


def test_real_stage2_mode_override_and_followup(monkeypatch, tmp_path):
    from kopl.c4_stage2.infer import MODEL_VERSION, RULES_VERSION
    real = _load_real(monkeypatch, tmp_path, "auto", model=object())
    seen = []

    def fake_analyze(user_ref, entries, target_risk, mode):
        seen.append(mode)
        version = MODEL_VERSION if mode == "auto" else RULES_VERSION
        return {"findings": {"age": {"verdict": "abstain"}}, "recommendation": {"projected": {"current_risk": 0.0}},
                "provenance": {"model_version": version}}
    monkeypatch.setattr(real, "_stage2_analyze", fake_analyze)
    spans = {"p1": {"spans": []}}
    real.stage2("u_0000aaaa", [{"post_id": "p1", "body": "글"}], spans_by_post=spans, mode="rules")
    real.stage2("u_0000aaaa", [{"post_id": "p1", "body": "글"}], spans_by_post=spans)       # 지정 없으면 STAGE2_MODE
    out = real.stage2_followup("u_0000aaaa", [{"post_id": "p1", "body": "글"}], spans_by_post=spans)
    assert seen == ["rules", "auto", "auto"]
    assert out["used_model"] is True and out["model_version"] == MODEL_VERSION
    # 모델이 출력을 못 냈으면(규칙 폴백) used_model False + 고정 이유
    monkeypatch.setattr(real, "_stage2_analyze", lambda *a, **k: {
        "findings": {}, "recommendation": {"projected": {"current_risk": 0.0}},
        "provenance": {"model_version": f"{RULES_VERSION} (fallback: model output truncated)"}})
    out = real.stage2_followup("u_0000aaaa", [{"post_id": "p1", "body": "글"}], spans_by_post=spans)
    assert out["used_model"] is False and out["reason"] == "model output truncated"


# ── 화면
def test_screens_opt_in_and_follow():
    static = ROOT / "apps" / "analyzer" / "static"
    scan = (static / "scan.html").read_text(encoding="utf-8")
    action = (static / "action.html").read_text(encoding="utf-8")
    diag = (static / "diagnosis.html").read_text(encoding="utf-8")
    common = (static / "common.js").read_text(encoding="utf-8")
    assert "../scan/${encodeURIComponent(user_ref)}${PROGRESSIVE_Q}" in scan and "fetch(\"../upload\" + PROGRESSIVE_Q" in scan
    assert "${PROGRESSIVE_Q}" in action and "followStage2(" in action
    assert "followStage2(refreshStage2)" in diag and 'id="s2Note"' in diag
    for words in ("빠른 결과(규칙)", "정밀 판정이 끝났습니다", "정밀 판정을 받지 못해", "정밀 판정을 기다리는 점검이 많아"):
        assert words in common, words
    # 외부 요청 0건 — 새 주소는 같은 서버의 상대 경로뿐
    assert "http://" not in common.split("PROGRESSIVE_Q")[1].split("// 서버가 만든 설명 문장")[0]
