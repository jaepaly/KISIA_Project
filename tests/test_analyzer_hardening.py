"""분석 앱 보안 · 성능 보강 (A1~A4 · A6) — 점검 입장 제한 · 업로드가 이벤트 루프를 막지 않음 · 동시 점검이 섞이지 않음 ·
업로드 입력 상한 · 다른 출처 POST 거부.

    python -m pytest -q --import-mode=importlib tests/test_analyzer_hardening.py
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
from apps.analyzer.adapters import file_adapter  # noqa: E402


def _txt(text: str = "첫 글\n둘째 글"):
    return {"file": ("a.txt", text.encode("utf-8"))}


def _json(obj) -> dict:
    return {"file": ("a.json", json.dumps(obj, ensure_ascii=False).encode("utf-8"))}


@pytest.fixture
def admission(monkeypatch):
    """테스트마다 새 입장 제한 — 자리 1 · 줄 1 · 기다림 0.5초"""
    adm = server._Admission(1, 1, 0.5)
    monkeypatch.setattr(server, "_admission", adm)
    return adm


# ── A1 입장 제한
def test_busy_returns_429_with_fixed_korean_detail(admission, monkeypatch):
    monkeypatch.setattr(server, "_pipeline", lambda user_ref, posts: {"ok": True})
    c = TestClient(server.app)
    assert admission.sem.acquire(blocking=False)          # 다른 점검이 자리를 잡고 있다
    try:
        t0 = time.monotonic()
        r = c.post("/upload", files=_txt())
        assert r.status_code == 429 and r.json()["detail"] == server.BUSY_DETAIL
        assert r.headers.get("retry-after") == "30"
        assert 0.4 <= time.monotonic() - t0 < 5             # SCAN_QUEUE_WAIT 만큼 기다린 뒤
        # 줄이 꽉 찼으면(queue_max) 기다리지 않고 바로 429
        admission.queue_max = 0
        t0 = time.monotonic()
        assert c.post("/upload", files=_txt()).status_code == 429
        assert time.monotonic() - t0 < 0.4
    finally:
        admission.sem.release()
    admission.queue_max = 1
    assert c.post("/upload", files=_txt()).status_code == 200   # 자리가 나면 다시 받는다
    assert admission.waiting == 0
    # 자리는 정확히 하나로 돌아왔다 — BoundedSemaphore 라 더 풀면 ValueError
    assert admission.sem.acquire(blocking=False)
    admission.sem.release()
    with pytest.raises(ValueError):
        admission.sem.release()


def test_waiting_scan_starts_when_slot_frees_and_rate_excludes_wait(admission, monkeypatch):
    """줄에서 기다린 시간은 예상 속도(_learn_rate)에 들어가지 않는다 — 점검 자체 시간만."""
    admission.wait_s = 5.0
    learned = []
    monkeypatch.setattr(server, "_learn_rate", lambda chars, seconds: learned.append(seconds))

    def slow(user_ref, posts):
        time.sleep(0.2)
        return {"ok": True}
    monkeypatch.setattr(server, "_pipeline", slow)
    assert admission.sem.acquire(blocking=False)
    threading.Timer(1.0, admission.sem.release).start()      # 1초 뒤 앞 점검이 끝난다
    t0 = time.monotonic()
    r = TestClient(server.app).post("/upload", files=_txt())
    assert r.status_code == 200 and time.monotonic() - t0 >= 1.0
    assert len(learned) == 1 and 0.15 <= learned[0] < 0.8, learned


def test_scan_queue_reports_people_ahead_by_ticket(admission, monkeypatch):
    """대기 순서 — 기다리는 점검의 대기표로 묻으면 앞사람 수(점검 중 1명), 차례가 와서 시작하면 줄에서 빠진다(E 리뷰 #368)."""
    admission.wait_s = 5.0
    gate = threading.Event()

    def slow(user_ref, posts):
        gate.wait(5)
        return {"ok": True}
    monkeypatch.setattr(server, "_pipeline", slow)
    c = TestClient(server.app)
    first = threading.Thread(target=lambda: c.post("/upload", files=_txt(), headers={"X-Scan-Ticket": "aaaaaaaa1111"}))
    first.start()
    for _ in range(50):
        if admission.running == 1:
            break
        time.sleep(0.05)
    assert admission.running == 1
    # 바로 자리를 잡은 점검은 줄에 없다
    assert c.get("/api/scan-queue", params={"ticket": "aaaaaaaa1111"}).json() == {"waiting": False, "ahead": 0}
    second = threading.Thread(target=lambda: c.post("/upload", files=_txt(), headers={"X-Scan-Ticket": "bbbbbbbb2222"}))
    second.start()
    for _ in range(50):
        if admission.waiting == 1:
            break
        time.sleep(0.05)
    assert c.get("/api/scan-queue", params={"ticket": "bbbbbbbb2222"}).json() == {"waiting": True, "ahead": 1}
    gate.set()
    first.join(5); second.join(5)
    assert c.get("/api/scan-queue", params={"ticket": "bbbbbbbb2222"}).json() == {"waiting": False, "ahead": 0}
    assert admission.running == 0 and admission.waiting == 0 and not admission._tickets
    # 대기표 모양이 아니면 받지 않는다(서버 줄에도 안 들어간다)
    assert c.get("/api/scan-queue", params={"ticket": "x"}).status_code == 422
    assert c.get("/api/scan-queue", params={"ticket": "<script>aa"}).status_code == 422


def test_failed_pipeline_releases_slot(admission, monkeypatch):
    def boom(user_ref, posts):
        raise RuntimeError("엔진 실패")
    monkeypatch.setattr(server, "_pipeline", boom)
    c = TestClient(server.app, raise_server_exceptions=False)
    assert c.post("/upload", files=_txt()).status_code == 500
    assert admission.sem.acquire(blocking=False)              # 실패해도 자리는 돌아온다
    admission.sem.release()


def test_only_one_pipeline_runs_at_a_time(admission, monkeypatch):
    admission.queue_max, admission.wait_s = 5, 10.0
    running, peak, lock = [0], [0], threading.Lock()

    def slow(user_ref, posts):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.15)
        with lock:
            running[0] -= 1
        return {"ok": True}
    monkeypatch.setattr(server, "_pipeline", slow)
    codes = []
    with TestClient(server.app) as c:
        ts = [threading.Thread(target=lambda: codes.append(c.post("/upload", files=_txt()).status_code)) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    assert codes == [200] * 4 and peak[0] == 1


# ── A2 업로드가 이벤트 루프를 막지 않는다
def test_upload_does_not_block_other_requests(admission, monkeypatch):
    started = threading.Event()

    def slow(user_ref, posts):
        started.set()
        time.sleep(1.5)
        return {"ok": True}
    monkeypatch.setattr(server, "_pipeline", slow)
    with TestClient(server.app) as c:   # 한 이벤트 루프를 같이 쓴다 — 막으면 아래 요청도 1.5초를 기다린다
        th = threading.Thread(target=lambda: c.post("/upload", files=_txt()))
        th.start()
        assert started.wait(5)
        t0 = time.monotonic()
        assert c.get("/api/engine-mode").status_code == 200
        assert time.monotonic() - t0 < 0.7
        th.join()


# ── A3 동시 점검이 섞이지 않는다 (실제 엔진 real.py 를 가짜 모델로 불러 확인)
def _load_real(monkeypatch, tmp_path):
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("C1_CHECKPOINT_DIR", str(ckpt))
    monkeypatch.setenv("STAGE2_MODE", "rules")
    monkeypatch.setenv("TORCH_THREADS", "0")
    from kopl.c1_span import infer
    monkeypatch.setattr(infer, "SpanDetector", lambda *a, **k: object())
    spec = importlib.util.spec_from_file_location("apps.analyzer.engines._real_under_test",
                                                  ROOT / "apps" / "analyzer" / "engines" / "real.py")
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    return real


def test_real_engine_has_no_global_span_cache_and_concurrent_scans_do_not_mix(monkeypatch, tmp_path):
    real = _load_real(monkeypatch, tmp_path)
    assert not hasattr(real, "_SPAN_CACHE")                    # 요청 밖에 원문을 두지 않는다

    class FakeRules:
        @staticmethod
        def detect(detector, record, resolver):
            body = record.get("body", "")
            return {"post_id": record["post_id"], "spans": [{"span_id": f"{record['post_id']}_s01", "text_id": "body",
                                                              "start": 0, "end": 2, "text": body[:2], "type": "LOC_ADMIN"}]}
    monkeypatch.setattr(real, "_c1_rules", FakeRules)
    barrier = threading.Barrier(2)

    def fake_analyze(user_ref, entries, target_risk, mode):
        barrier.wait(5)   # 두 점검의 1단이 모두 끝난 뒤 2단 — 전역 캐시가 있으면 여기서 나중 것이 앞의 것을 덮는다
        return {"recommendation": {"projected": {"current_risk": 0.0}}, "entries": entries}
    monkeypatch.setattr(real, "_stage2_analyze", fake_analyze)

    results = {}

    def pipeline(user_ref, body):
        posts = [{"post_id": "upload_000", "title": None, "body": body, "photos": [{"caption": None}, {"caption": "캡션"}]}]
        spans = {p["post_id"]: real.detect_spans(server._detect_input(p)) for p in posts}
        results[user_ref] = real.stage2(user_ref, posts, spans_by_post=spans)["output"]["entries"][0]

    ts = [threading.Thread(target=pipeline, args=(u, b)) for u, b in (("u_aaaaaaaa", "역삼동 이야기"), ("u_bbbbbbbb", "성수동 이야기"))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results["u_aaaaaaaa"]["texts"]["body"] == "역삼동 이야기" and results["u_aaaaaaaa"]["spans"][0]["text"] == "역삼"
    assert results["u_bbbbbbbb"]["texts"]["body"] == "성수동 이야기" and results["u_bbbbbbbb"]["spans"][0]["text"] == "성수"
    # 빈 캡션도 자리를 지킨다 — photo_caption:1 (서버 _detect_input 과 같은 번호)
    assert results["u_aaaaaaaa"]["texts"].get("photo_caption:1") == "캡션"
    # spans_by_post 가 없으면 그 글만 다시 탐지한다 (예전 단일 요청 동작과 같은 결과)
    monkeypatch.setattr(real, "_stage2_analyze", lambda user_ref, entries, target_risk, mode:
                        {"recommendation": {"projected": {"current_risk": 0.0}}, "entries": entries})
    out = real.stage2("u_cccccccc", [{"post_id": "p1", "body": "합정 카페"}])["output"]["entries"][0]
    assert out["spans"][0]["text"] == "합정"


def test_server_passes_request_spans_to_stage2(monkeypatch):
    seen = {}

    def fake_stage2(user_ref, posts, risk_current=0.0, risk_target=40.0, *, spans_by_post=None, detect_inputs=None):
        seen["spans"] = spans_by_post
        seen["inputs"] = detect_inputs
        from apps.analyzer.engines import mock
        return mock.stage2(user_ref, posts, risk_current, risk_target)
    monkeypatch.setattr(server.engine, "stage2", fake_stage2)
    out = server._run_pipeline("u_00000000", [{"post_id": "p1", "body": "저수지 산책"}])
    assert seen["spans"] is out["spans"] and "p1" in seen["spans"]
    assert seen["inputs"]["p1"]["body"] == "저수지 산책"


# ── A4 업로드 입력 상한 · 형식 검사
@pytest.mark.parametrize("payload, status, words", [
    (b"{not json", 400, "JSON 형식"),
    ([1, 2], 400, "export 형식"),
    ({"posts": "x"}, 400, "배열"),
    ({"posts": ["글"]}, 400, "객체"),
    ({"posts": [{"body": "x"}]}, 400, "post_id"),
    ({"posts": [{"post_id": 3, "body": "x"}]}, 400, "post_id"),
    ({"posts": [{"post_id": "a", "body": 3}]}, 400, "문자열"),
    ({"posts": [{"post_id": "a", "photos": {"caption": "x"}}]}, 400, "photos"),
    ({"posts": [{"post_id": "a", "photos": [3]}]}, 400, "caption"),
    ({"posts": [{"post_id": "a", "activity_meta": "x"}]}, 400, "activity_meta"),
    ({"user_ref": "u_upload00", "posts": []}, 400, "user_ref"),
    ({"posts": [{"post_id": f"p{i}"} for i in range(file_adapter.MAX_POSTS + 1)]}, 413, "글이 너무 많습니다"),
    ({"posts": [{"post_id": "a", "photos": [{"caption": "x"}] * (file_adapter.MAX_CAPTIONS + 1)}]}, 413, "캡션"),
    ({"posts": [{"post_id": "a", "body": "가" * (file_adapter.MAX_BODY_CHARS + 1)}]}, 413, "본문"),
    ({"posts": [{"post_id": f"p{i}", "body": "가" * 19_000} for i in range(8)]}, 413, "모두 합쳐"),
    ({"posts": [{"post_id": "a"}, {"post_id": "a"}]}, 400, "같은 post_id"),
])
def test_upload_validation_returns_4xx_with_fixed_message(admission, payload, status, words):
    c = TestClient(server.app)
    files = {"file": ("a.json", payload)} if isinstance(payload, bytes) else _json(payload)
    r = c.post("/upload", files=files)
    assert r.status_code == status, r.text
    assert words in r.json()["detail"]


def test_upload_txt_line_limit_and_bad_encoding(admission):
    c = TestClient(server.app)
    r = c.post("/upload", files=_txt("\n".join(f"글 {i}" for i in range(file_adapter.MAX_POSTS + 1))))
    assert r.status_code == 413
    r = c.post("/upload", files={"file": ("a.txt", "가".encode("cp949"))})
    assert r.status_code == 400 and "UTF-8" in r.json()["detail"]


def test_demo_sized_export_fits_limits(admission, monkeypatch):
    """가장 긴 시연 계정(30편 · 약 97,000자 · 글당 캡션 2개) + 쓰는 글 — 상한 안에 들어간다."""
    monkeypatch.setattr(server, "_pipeline", lambda user_ref, posts: {"n": len(posts)})
    posts = [{"post_id": f"E15_b{i:02d}", "user_ref": "u_0123456789ab", "title": "제목" * 10, "body": "가" * 3_300,
              "photos": [{"caption": "캡션" * 10}, {"caption": None}], "post_date": "2026-01-01",
              "activity_meta": {"nickname": "닉", "geo_tag": "성동구 성수동", "post_time": "10:00"}} for i in range(31)]
    r = TestClient(server.app).post("/upload", files=_json({"user_ref": "u_0123456789ab", "posts": posts}))
    assert r.status_code == 200 and r.json() == {"n": 31}
    ok = file_adapter.load_from_bytes(json.dumps({"posts": []}).encode(), "x.json")   # user_ref 가 없으면 새로 만든다
    assert ok["user_ref"].startswith("u_")


def test_duplicate_check_is_linear():
    from fastapi import HTTPException
    posts = [{"post_id": f"p{i}"} for i in range(50_000)] + [{"post_id": "p7"}]
    t0 = time.monotonic()
    with pytest.raises(HTTPException) as e:
        server._check_posts(posts)
    assert e.value.status_code == 400 and "p7" in e.value.detail and time.monotonic() - t0 < 1.0


# ── A6 다른 출처 POST 거부
def test_cross_origin_post_is_rejected(admission, monkeypatch):
    monkeypatch.setattr(server, "_pipeline", lambda user_ref, posts: {"ok": True})
    c = TestClient(server.app)
    assert c.post("/upload", files=_txt(), headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/upload", files=_txt(), headers={"Referer": "https://evil.example/x"}).status_code == 403
    assert c.post("/upload", files=_txt(), headers={"Origin": "null"}).status_code == 403
    assert c.post("/scan/u_00000000", headers={"Origin": "https://evil.example"}).status_code == 403
    # 같은 출처(이 화면) · Origin 없는 호출(curl) · Veilo 공개 주소(SNS_PUBLIC_URL · ALLOWED_ORIGINS)는 받는다
    assert c.post("/upload", files=_txt(), headers={"Origin": "http://testserver"}).status_code == 200
    assert c.post("/upload", files=_txt()).status_code == 200
    monkeypatch.setattr(server, "_ALLOWED_HOSTS", {"localhost:3040"})
    assert c.post("/upload", files=_txt(), headers={"Origin": "http://localhost:3040"}).status_code == 200
    # nginx 가 Host 를 바꿔 넘겨도 X-Forwarded-Host 가 공개 주소면 같은 출처
    assert c.post("/upload", files=_txt(), headers={"Origin": "https://veilo.site", "X-Forwarded-Host": "veilo.site"}).status_code == 200


def test_allowed_origins_env(monkeypatch):
    monkeypatch.setattr(server, "SNS_PUBLIC_URL", "http://localhost:3000")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://veilo.site, https://www.veilo.site")
    assert server._origin_hosts() == {"localhost:3000", "veilo.site", "www.veilo.site"}


# ── Codex 검토 반례
def test_cancel_before_thread_starts_releases_slot_exactly_once(monkeypatch):
    """스레드가 시작되기 전에 기다리던 쪽이 취소되면 — 자리는 기다리던 쪽이 한 번만 돌려주고, 늦게 도는 스레드는 점검하지 않는다."""
    import asyncio
    adm = server._Admission(1, 1, 0.5)
    ran, errors, done = [], [], threading.Event()

    async def fake_threadpool(work):  # 점검 스레드에 넘기는 자리
        def late():
            time.sleep(0.1)
            try:
                work()
            except Exception as e:   # noqa: BLE001 — 이중 반환(ValueError)을 잡아 확인
                errors.append(e)
            done.set()
        threading.Thread(target=late).start()
        raise asyncio.CancelledError
    monkeypatch.setattr(adm, "_in_thread", fake_threadpool)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adm.run(None, lambda: ran.append(1)))
    assert done.wait(5)
    assert ran == [] and errors == []
    assert adm.sem.acquire(blocking=False) and not adm.sem.acquire(blocking=False)   # 자리는 정확히 1
    adm.sem.release()


def test_cancel_after_thread_started_lets_thread_release(monkeypatch):
    import asyncio
    adm = server._Admission(1, 1, 0.5)
    ran, errors, done = [], [], threading.Event()

    async def fake_threadpool(work):  # 점검 스레드에 넘기는 자리
        def run():
            try:
                work()
            except Exception as e:   # noqa: BLE001
                errors.append(e)
            done.set()
        threading.Thread(target=run).start()
        await asyncio.sleep(0.05)     # 스레드가 시작을 적은 뒤 취소
        raise asyncio.CancelledError

    def slow():
        time.sleep(0.2)
        ran.append(1)
    monkeypatch.setattr(adm, "_in_thread", fake_threadpool)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adm.run(None, slow))
    assert not adm.sem.acquire(blocking=False)      # 점검이 아직 돈다 — 자리를 먼저 돌려주지 않았다
    assert done.wait(5) and ran == [1] and errors == []
    assert adm.sem.acquire(blocking=False) and not adm.sem.acquire(blocking=False)
    adm.sem.release()


def test_sec_fetch_site_same_origin_passes_behind_proxy(admission, monkeypatch):
    """nginx 가 Host 를 내부 주소로 바꿔 넘겨도 — 브라우저의 Sec-Fetch-Site: same-origin 이면 통과. 다른 사이트는 여전히 403."""
    monkeypatch.setattr(server, "_pipeline", lambda user_ref, posts: {"ok": True})
    c = TestClient(server.app)
    h = {"Origin": "https://veilo.site", "Host": "127.0.0.1:8020"}
    assert c.post("/upload", files=_txt(), headers=h).status_code == 403
    assert c.post("/upload", files=_txt(), headers={**h, "Sec-Fetch-Site": "same-origin"}).status_code == 200
    evil = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
    assert c.post("/upload", files=_txt(), headers=evil).status_code == 403


def test_deeply_nested_json_is_400(admission):
    r = TestClient(server.app).post("/upload", files={"file": ("a.json", b"[" * 5000 + b"]" * 5000)})
    assert r.status_code == 400 and "JSON" in r.json()["detail"]


# ── 2차 Codex 검토 반례
async def _call_asgi(path: str, receive_msgs: list[dict], headers=None, disconnect: bool = True):
    """ASGI 앱을 직접 부른다 — receive 가 정해 둔 메시지를 차례로 주고, 다 쓰면 끊김(http.disconnect) ·
    disconnect=False 면 연결이 살아 있는 브라우저처럼 다음 메시지를 기다린다."""
    import asyncio
    msgs = list(receive_msgs)
    sent = []

    async def receive():
        if msgs:
            return msgs.pop(0)
        if not disconnect:
            await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(m):
        sent.append(m)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "headers": headers or [], "client": ("127.0.0.1", 1), "server": ("testserver", 80)}
    await server.app(scope, receive, send)
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_real_disconnect_while_waiting_never_runs_scan(admission, monkeypatch):
    """줄에서 기다리는 동안 브라우저가 실제로 떠나면(ASGI http.disconnect) — 줄에서 빠지고 점검은 끝내 돌지 않는다."""
    import asyncio
    admission.wait_s = 10.0
    ran = []
    monkeypatch.setattr(server, "_pipeline", lambda user_ref, posts: ran.append(1) or {"ok": True})
    monkeypatch.setattr(server.sns_adapter, "load", lambda *a, **k: {"posts": [{"post_id": "p1", "body": "글"}]})
    assert admission.sem.acquire(blocking=False)
    try:
        t0 = time.monotonic()
        status = asyncio.run(_call_asgi("/scan/u_00000000", [{"type": "http.request", "body": b"", "more_body": False}]))
        assert status == 499 and time.monotonic() - t0 < 3 and admission.waiting == 0
    finally:
        admission.sem.release()
    time.sleep(0.3)
    assert ran == []
    assert admission.sem.acquire(blocking=False)
    admission.sem.release()


def test_scan_starts_even_when_shared_thread_pool_is_full(admission, monkeypatch):
    """공용 스레드 풀(AnyIO 기본)이 다 차 있어도 자리를 잡은 점검은 전용 스레드에서 바로 돈다."""
    import asyncio
    import anyio.to_thread
    monkeypatch.setattr(server, "_pipeline", lambda user_ref, posts: {"ok": True})
    boundary = b"b0"
    body = (b"--b0\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.txt\"\r\n\r\n"
            + "첫 글".encode() + b"\r\n--b0--\r\n")

    async def main():
        lim = anyio.to_thread.current_default_thread_limiter()
        old = lim.total_tokens
        lim.total_tokens = 1
        await lim.acquire()                      # 공용 풀의 자리를 다른 요청이 다 쓰고 있다
        try:
            return await asyncio.wait_for(_call_asgi(
                "/upload", [{"type": "http.request", "body": body, "more_body": False}],
                headers=[(b"content-type", b"multipart/form-data; boundary=" + boundary)], disconnect=False), 5)
        finally:
            lim.release()
            lim.total_tokens = old
    assert asyncio.run(main()) == 200


def test_upload_strips_non_contract_fields_and_stage2_sees_stage1_input(admission, monkeypatch):
    """photos 와 photo_captions 가 다르게 와도 1단 · 2단이 같은 캡션(계약 칸 photos)을 본다 · 정수 캡션은 400."""
    seen = {}
    from apps.analyzer.engines import mock

    def fake_detect(rec):
        seen.setdefault("detect", []).append(rec)
        return mock.detect_spans(rec)

    def fake_stage2(user_ref, posts, risk_current=0.0, risk_target=40.0, *, spans_by_post=None, detect_inputs=None):
        seen["posts"], seen["inputs"] = posts, detect_inputs
        return mock.stage2(user_ref, posts, risk_current, risk_target)
    monkeypatch.setattr(server.engine, "detect_spans", fake_detect)
    monkeypatch.setattr(server.engine, "stage2", fake_stage2)
    c = TestClient(server.app)
    post = {"post_id": "a", "body": "저수지", "photos": [{"caption": "성수동"}], "photo_captions": ["다른 곳", 3], "extra": "x"}
    r = c.post("/upload", files=_json({"posts": [post]}))
    assert r.status_code == 200, r.text
    assert "photo_captions" not in seen["posts"][0] and "extra" not in seen["posts"][0]
    assert seen["detect"][0]["photo_captions"] == ["성수동"] and seen["inputs"]["a"]["photo_captions"] == ["성수동"]
    assert "photo_captions" not in r.json()["posts"][0]
    bad = c.post("/upload", files=_json({"posts": [{"post_id": "a", "photos": [{"caption": 3}]}]}))
    assert bad.status_code == 400


def test_real_stage2_uses_stage1_input(monkeypatch, tmp_path):
    real = _load_real(monkeypatch, tmp_path)
    monkeypatch.setattr(real, "_stage2_analyze", lambda user_ref, entries, target_risk, mode:
                        {"recommendation": {"projected": {"current_risk": 0.0}}, "entries": entries})
    post = {"post_id": "p1", "body": "본문", "photos": [{"caption": "성수동"}], "photo_captions": ["다른 곳"]}
    rec = server._detect_input(post)
    out = real.stage2("u_00000000", [post], spans_by_post={"p1": {"spans": []}}, detect_inputs={"p1": rec})
    assert out["output"]["entries"][0]["texts"]["photo_caption:0"] == "성수동"


def test_scan_export_path_has_same_caps(admission, monkeypatch):
    """Veilo 내보내기(/scan)도 업로드와 같은 상한 — 긴 글로 점검 자리를 오래 붙잡지 못한다. 시연 크기는 통과."""
    monkeypatch.setattr(server, "_pipeline", lambda user_ref, posts: {"n": len(posts)})
    c = TestClient(server.app)
    huge = {"posts": [{"post_id": f"p{i}", "body": "가" * 19_000} for i in range(8)]}
    monkeypatch.setattr(server.sns_adapter, "load", lambda *a, **k: huge)
    r = c.post("/scan/u_00000000")
    assert r.status_code == 413 and "모두 합쳐" in r.json()["detail"]
    demo = {"posts": [{"post_id": f"E15_b{i:02d}", "title": "제목", "body": "가" * 3_300, "photos": [{"caption": "캡션"}] * 2,
                       "post_date": "2026-01-01", "activity_meta": {"nickname": "닉", "geo_tag": "성수동", "post_time": "10:00"}}
                      for i in range(30)]}
    monkeypatch.setattr(server.sns_adapter, "load", lambda *a, **k: demo)
    assert c.post("/scan/u_00000000").json() == {"n": 30}


def test_cancel_during_post_admission_disconnect_check_releases_slot():
    """자리를 잡은 직후 끊김 확인 중에 취소돼도 자리를 돌려준다 (Codex 2차 — 예전엔 영구히 새어 이후 점검이 모두 429)."""
    import asyncio
    adm = server._Admission(1, 1, 0.5)

    class Req:
        async def is_disconnected(self):
            raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adm.run(Req(), lambda: None))
    assert adm.sem.acquire(blocking=False) and not adm.sem.acquire(blocking=False)
    adm.sem.release()
