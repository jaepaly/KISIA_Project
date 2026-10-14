"""분석기 서버. 화면 3개(스캔·진단·조치)를 엔진에 연결한다.

    ENGINE_MODE=mock uvicorn apps.analyzer.server:app --port 8000 --reload

경계: 가상 SNS 서비스에서는 HTTP로만 글을 받는다(adapters/sns_adapter.py).
그 서비스의 저장소나 내부 모듈을 이 디렉토리에서 직접 import하지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections import Counter
from urllib.parse import urlsplit

import requests

from fastapi import FastAPI, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from apps.analyzer import engines as engine
from kopl.c4_stage2.links import find_direct_identifiers
from apps.analyzer.engines import c1_rules  # os · threading 만 — 목 모드에서도 모델을 불러오지 않는다
from kopl.c4_stage2.timeline import find_marks, infer_starts
from apps.analyzer.adapters import file_adapter, sns_adapter

log = logging.getLogger("analyzer")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
SNS_BASE = os.getenv("SNS_BASE_URL", "http://localhost:3000")   # 서버가 Veilo 를 부르는 주소 (adapter)
# 브라우저가 보는 Veilo 주소 — 「Veilo 로 돌아가기」 · 글 링크. 빈 값 = 같은 도메인 루트(인스턴스 veilo.site)
# 로컬에서 따로 띄우면 SNS_PUBLIC_URL=http://localhost:3000 (Veilo 쪽 PADO_BASE 와 짝)
SNS_PUBLIC_URL = os.getenv("SNS_PUBLIC_URL", "").rstrip("/")

app = FastAPI(title="분석기 (mock)")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Veilo 화면(다른 포트)이 점검을 부를 수 있게 — SNS_PUBLIC_URL 이 다른 출처일 때만 그 하나를 허용한다.
# 인스턴스는 같은 도메인이라 켜지지 않는다. 외부로 나가는 요청이 아니라 들어오는 요청의 허용이다
if SNS_PUBLIC_URL.startswith(("http://", "https://")):
    _o = urlsplit(SNS_PUBLIC_URL)
    app.add_middleware(CORSMiddleware, allow_origins=[f"{_o.scheme}://{_o.netloc}"],
                       allow_methods=["GET", "POST"], allow_headers=["*"])


@app.get("/")
def root():
    return RedirectResponse("/static/scan.html")


@app.get("/config.js")
def config_js():
    """화면 설정 — 세 화면이 common.js 보다 먼저 읽는다 (<script src="../config.js">)."""
    return Response(f"window.SNS_PUBLIC = {json.dumps(SNS_PUBLIC_URL)};\n", media_type="application/javascript")


def _upstream_error(what: str, exc: Exception, missing_account: bool = False) -> HTTPException:
    """Veilo 호출 실패를 화면용 고정 문구로 바꾼다. 예외 원문에는 내부 주소(SNS_BASE_URL)가 들어 있어 로그에만 남긴다."""
    log.warning("%s 실패: %r", what, exc)
    # 「없는 계정」은 내보내기 창구가 404 로 답한 경우뿐 — 검색 창구의 404 는 경로 문제라 502 로 둔다
    resp = getattr(exc, "response", None)
    if missing_account and isinstance(exc, requests.HTTPError) and resp is not None and resp.status_code == 404:
        return HTTPException(status_code=404, detail="계정을 찾지 못했습니다")
    return HTTPException(status_code=502, detail=f"{what} 실패 — 가상 SNS 에 닿지 못했습니다")


@app.get("/sns/authors")
def sns_authors(request: Request, q: str = "", limit: int | None = Query(default=None, ge=1, le=200)):
    """스캔 화면 계정 고르기 — Veilo 를 화면이 직접 부르지 않고 어댑터를 거친다 (sns-minimal-spec §6 · #337 리뷰).
    빈 q 는 둘러보기(공개 글 많은 순) — 처음 온 사람은 계정 이름을 모른다. limit 은 「더 보기」."""
    try:
        kw = {"limit": limit} if limit is not None else {}
        return sns_adapter.search_authors(q, base=SNS_BASE, session_id=request.cookies.get("veilo_sid"), **kw)
    except Exception as exc:  # SNS 서버 다운 등
        raise _upstream_error("계정 찾기", exc) from exc


@app.get("/api/engine-mode")
def engine_mode():
    """화면 하단 배지용 — 지금 mock인지 real인지 · 1단 체크포인트 폴더(시연 PC 확인용 · 마지막 두 단계만)."""
    # 엔진이 실제로 쓰는 값(import 때 고정)을 그대로 — 환경변수를 다시 읽으면 배지와 동작이 어긋날 수 있다 (Codex 10/9)
    return {"mode": os.getenv("ENGINE_MODE", "mock"), "c1_rules": c1_rules.enabled(), "c1_checkpoint": engine.c1_checkpoint()}


def _detect_input(post: dict) -> dict:
    """1단 입력 — 제목·본문·사진 캡션 (export 의 photos 는 [{"caption": ...}]).

    빈 캡션도 자리를 지킨다 — 빼면 뒤 캡션의 번호(photo_caption:N)가 화면과 어긋난다.
    """
    captions = [(ph.get("caption") if isinstance(ph, dict) else ph) or "" for ph in post.get("photos") or []]
    record = {"post_id": post["post_id"], "title": post.get("title"), "body": post.get("body") or "",
              "photo_captions": captions}
    return {k: v for k, v in record.items() if v not in (None, [])}


def _channels(post: dict) -> dict[str, str]:
    """화면(common.js channelsOf)과 같은 채널 이름 — title · body · photo_caption:N (빈 캡션도 번호를 지킨다)"""
    out = {"title": post.get("title") or "", "body": post.get("body") or ""}
    for i, ph in enumerate(post.get("photos") or []):
        out[f"photo_caption:{i}"] = (ph.get("caption") if isinstance(ph, dict) else ph) or ""
    return out


def _check_posts(posts: list[dict]) -> None:
    """글 0편은 허용한다 — 「글 0편인 작성자도 화면이 에러 없이」(e-integration §4). 중복·빈 ID 는 막는다."""
    ids = [p.get("post_id") for p in posts]
    if any(not isinstance(i, str) or not i for i in ids):
        raise HTTPException(status_code=400, detail="모든 글에 post_id 가 있어야 합니다")
    dup = sorted(i for i, n in Counter(ids).items() if n > 1)
    if dup:
        raise HTTPException(status_code=400, detail=f"같은 post_id 가 여러 번 있습니다: {', '.join(dup[:5])}")


# ── 예상 점검 시간 — 시간의 95% 이상이 1단 탐지이고 글자 수에 거의 비례한다(integration-W08 「스캔 시간」).
#    기계마다 2배 넘게 달라(이 PC 0.6ms/자 · veilo.site 서버 1.4ms/자) 숫자를 고정하지 않는다 — 서버 실측(1.45ms/자)에서 시작해
#    실제 점검이 끝날 때마다 이 프로세스의 속도로 고쳐 간다(지수 평균). 글자 수가 적은 점검은 고정 시간 몫이 커서 속도 추정에 쓰지 않는다
SCAN_BASE_S = 1.0
#    목업 엔진은 모델을 안 돌려 거의 즉시 끝난다 — 처음부터 그 속도로(첫 예상이 「12초」로 나와 시연을 헷갈리게 하지 않게)
_rate_lock = threading.Lock()   # 동시 점검이 속도를 같이 고칠 때 — 읽고 고치고 세는 것을 한 번에
_scan_rate = {"ms_per_char": float(os.getenv("SCAN_MS_PER_CHAR", "1.45" if os.getenv("ENGINE_MODE", "mock") == "real" else "0.02")),
              "samples": 0}


def _chars(posts: list[dict]) -> int:
    """점검에 들어가는 글자 수 — 제목 · 본문 · 사진 캡션 (1단 입력과 같은 채널)"""
    n = 0
    for p in posts:
        n += len(p.get("title") or "") + len(p.get("body") or "")
        for ph in p.get("photos") or []:
            n += len((ph.get("caption") if isinstance(ph, dict) else ph) or "")
    return n


def _estimate(chars: int) -> dict:
    with _rate_lock:
        rate, n = _scan_rate["ms_per_char"], _scan_rate["samples"]
    return {"n_chars": chars, "seconds": round(SCAN_BASE_S + chars * rate / 1000, 1), "calibrated": n > 0}


def _learn_rate(chars: int, seconds: float) -> None:
    if chars < 2000:
        return
    r = max(0.0, seconds - SCAN_BASE_S) * 1000 / chars
    with _rate_lock:
        _scan_rate["ms_per_char"] = r if _scan_rate["samples"] == 0 else 0.5 * _scan_rate["ms_per_char"] + 0.5 * r
        _scan_rate["samples"] += 1


@app.get("/sns/estimate/{user_ref}")
def sns_estimate(user_ref: str, request: Request):
    """계정 점검 예상 시간 — 내보내기(계약 그대로)로 글자 수를 세고 이 프로세스의 속도로 곱한다. 화면이 「예상 약 N초」를 띄운다."""
    try:
        export = sns_adapter.load(user_ref, base=SNS_BASE, session_id=request.cookies.get("veilo_sid"))
    except Exception as exc:
        raise _upstream_error("내보내기 조회", exc, missing_account=True) from exc
    posts = export.get("posts", [])
    return {"n_posts": len(posts), **_estimate(_chars(posts))}


@app.get("/api/scan-estimate")
def scan_estimate(chars: int = Query(ge=0, le=5_000_000)):
    """파일 업로드 예상 시간 — 화면이 파일 크기로 어림한 글자 수를 준다."""
    return _estimate(chars)


def _run_pipeline(user_ref: str, posts: list[dict]) -> dict:
    _check_posts(posts)
    t0 = time.perf_counter()
    out = _pipeline(user_ref, posts)   # 실패한 점검(예외)은 속도를 배우지 않는다 — 빨리 끝난 실패가 예상을 망치지 않게 (Codex 10/14)
    _learn_rate(_chars(posts), time.perf_counter() - t0)
    return out


def _pipeline(user_ref: str, posts: list[dict]) -> dict:
    spans_by_post = {p["post_id"]: engine.detect_spans(_detect_input(p)) for p in posts}
    # 조건 · k · 기여도 — real: k 엔진(본인 단서 · 여러 글 교집합 · 위치태그) · LOO / mock: 형식만
    conditions = engine.conditions(posts, spans_by_post)
    spec = engine.specificity({"user_ref": user_ref, "conditions": conditions})
    contrib = engine.contribution(user_ref, posts, spans_by_post=spans_by_post)

    baseline = contrib["output"]["baseline_risk"]
    target = round(max(baseline - 40.0, 0.0), 1)
    # 이번 요청의 스팬을 그대로 넘긴다 — 엔진 전역에 원문을 두지 않는다 (A3 · 동시 점검이 섞이지 않게)
    stage2 = engine.stage2(user_ref, posts, risk_current=baseline, risk_target=target, spans_by_post=spans_by_post)

    return {
        "user_ref": user_ref,
        "posts": posts,
        "spans": spans_by_post,
        "specificity": spec,
        "contribution": contrib,
        "k_by_post": engine.per_post_k(posts, spans_by_post),
        "stage2": stage2,
        # 계정 링크 · 이메일 · 전화 · @아이디 — 하나만으로 글쓴이에게 닿는다. k 로 잴 대상이 아니라 위험 점수와 별개로 먼저 안내한다
        # (스팬 계약 밖 · 화면 전용). 글마다 [{text_id, start, end, kind, label, value}]
        "direct_identifiers": {p["post_id"]: find_direct_identifiers(_channels(p)) for p in posts},
        # 글을 합치면 드러나는 시점 — 「날짜 + n일차/n주차」에서 시작일을 역산해, 여러 글이 같은 시작을 가리키면 묶는다 (#331).
        # 본문 날짜가 없으면 SNS export 의 작성 날짜(post_date · #334)를 기준점으로 쓴다. 파일 업로드는 작성일이 없어 본문 날짜만.
        # 스팬 계약 밖 · 화면 전용 — direct_identifiers 와 같은 방식
        "timeline": infer_starts({p["post_id"]: find_marks(_channels(p), p.get("post_date")) for p in posts}),
    }


# ── 점검 입장 제한 (A1) — 점검 하나가 2 vCPU 를 15~60초 다 쓴다. 동시에 여러 개를 돌리면 모두 느려지고 메모리가 모자란다.
#    한 번에 SCAN_CONCURRENCY 개(기본 1)만 돌리고, 기다리는 요청은 SCAN_QUEUE_MAX 개(기본 3)까지 SCAN_QUEUE_WAIT 초(기본 90)만 기다린다.
#    넘치면 429 + 고정 문구 — 화면(scan.html failMsg · action.html 다시 점검 · Veilo 글쓰기 점검)이 이 문구를 그대로 보인다
BUSY_DETAIL = "지금 다른 점검이 진행 중입니다. 잠시 뒤 다시 시도해 주세요."
SCAN_CONCURRENCY = max(1, int(os.getenv("SCAN_CONCURRENCY", "1")))
SCAN_QUEUE_MAX = max(0, int(os.getenv("SCAN_QUEUE_MAX", "3")))
SCAN_QUEUE_WAIT = max(0.0, float(os.getenv("SCAN_QUEUE_WAIT", "90")))
_POLL_S = 0.2


class _Admission:
    """프로세스 하나에 하나 — 점검 자리(세마포어)와 기다리는 줄의 길이.

    자리는 이벤트 루프에서 「막지 않고」 잡는다(acquire(blocking=False) + 짧은 sleep) — 기다리는 동안에도 다른 요청
    (엔진 배지 · 계정 찾기 · Veilo 화면)을 받는다. 기다리다 브라우저가 떠나면(글쓰기 실시간 점검의 abort) 줄에서 빠진다.
    자리는 점검을 실제로 돌린 스레드가 돌려준다 — 기다리던 코루틴이 취소돼도 점검이 끝나기 전에 자리가 풀리지 않게."""

    def __init__(self, concurrency: int, queue_max: int, wait_s: float):
        self.sem = threading.BoundedSemaphore(concurrency)
        self.queue_max, self.wait_s = queue_max, wait_s
        self._lock = threading.Lock()
        self.waiting = 0

    async def acquire(self, request: Request | None = None) -> None:
        if self.sem.acquire(blocking=False):
            return
        with self._lock:
            if self.waiting >= self.queue_max:
                raise HTTPException(status_code=429, detail=BUSY_DETAIL, headers={"Retry-After": "30"})
            self.waiting += 1
        try:
            deadline = time.monotonic() + self.wait_s
            while not self.sem.acquire(blocking=False):
                if time.monotonic() >= deadline:
                    raise HTTPException(status_code=429, detail=BUSY_DETAIL, headers={"Retry-After": "30"})
                if request is not None and await request.is_disconnected():
                    raise HTTPException(status_code=499, detail="요청이 취소되었습니다")
                await asyncio.sleep(_POLL_S)
        finally:
            with self._lock:
                self.waiting -= 1

    async def run(self, request: Request | None, fn, *args):
        """자리를 잡고 fn(*args) 를 스레드에서 돌린다. 자리는 그 스레드가 끝날 때 돌려준다."""
        await self.acquire(request)
        started = False

        def work():
            nonlocal started
            started = True
            try:
                return fn(*args)
            finally:
                self.sem.release()

        try:
            return await run_in_threadpool(work)
        except BaseException:
            if not started:   # 스레드가 시작도 못 하고 취소됐다 — 잡은 자리를 여기서 돌려준다
                self.sem.release()
            raise


_admission = _Admission(SCAN_CONCURRENCY, SCAN_QUEUE_MAX, SCAN_QUEUE_WAIT)


# ── 같은 출처 확인 (A6) — 점검 POST 는 이 화면(같은 출처)과 Veilo(SNS_PUBLIC_URL · 로컬 분리 실행)에서만 부른다.
#    브라우저는 다른 사이트에서 보내는 POST 에 Origin 을 반드시 싣는다 — Origin(없으면 Referer)이 있는데 허용 목록 밖이면 403.
#    둘 다 없으면(curl · 내부 호출) 통과 — 쿠키를 실어 보내는 브라우저 공격이 아니다.
#    nginx 가 Host 를 바꿔 넘기는 배치면 ALLOWED_ORIGINS=https://veilo.site 로 공개 주소를 알려 준다
def _origin_hosts() -> set[str]:
    hosts = set()
    for u in [SNS_PUBLIC_URL, *os.getenv("ALLOWED_ORIGINS", "").split(",")]:
        u = u.strip()
        if u.startswith(("http://", "https://")):
            hosts.add(urlsplit(u).netloc.lower())
    return hosts


_ALLOWED_HOSTS = _origin_hosts()


def _check_origin(request: Request) -> None:
    src = request.headers.get("origin") or request.headers.get("referer")
    if not src:
        return
    netloc = urlsplit(src).netloc.lower() if src.startswith(("http://", "https://")) else None
    own = {h.lower() for h in (request.headers.get("host"), request.headers.get("x-forwarded-host")) if h}
    if netloc is None or netloc not in own | _ALLOWED_HOSTS:
        log.warning("다른 출처의 점검 요청 거부: %r", src[:100])
        raise HTTPException(status_code=403, detail="이 화면에서 보낸 요청만 받습니다")


@app.post("/scan/{user_ref}")
async def scan(user_ref: str, request: Request):
    _check_origin(request)
    try:
        # 같은 도메인이라 Veilo 의 방문자 쿠키가 여기까지 온다 — 그 사람의 사본을 읽도록 넘긴다
        export = await run_in_threadpool(sns_adapter.load, user_ref, base=SNS_BASE,
                                         session_id=request.cookies.get("veilo_sid"))
    except Exception as exc:  # SNS 서버 다운·404 등
        raise _upstream_error("내보내기 조회", exc, missing_account=True) from exc
    posts = export.get("posts", [])
    _check_posts(posts)   # 줄에 서기 전에 — 틀린 입력이 자리를 차지하지 않게
    return await _admission.run(request, _run_pipeline, user_ref, posts)


# 업로드 상한 — 멀티파트 해석기는 1MiB(1,048,576B)를 넘는 파일을 임시 파일(디스크)로 넘긴다. 받은 본문 전체를
# 그보다 작게 묶어 「메모리에서 읽고 버린다」를 지킨다. 헤더(Content-Length)는 속일 수 있으니 실제로 받은 바이트를 센다
MAX_UPLOAD_BYTES = 1_040_000


async def _read_capped(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="파일이 너무 큽니다 (약 1MB 이하)")
    return bytes(body)


@app.post("/upload")
async def upload_and_scan(request: Request):
    """수동 업로드 경로. 파일은 메모리에서 읽고 버린다 — 디스크에 쓰지 않는다.

    점검은 스레드에서 돈다(A2) — 이벤트 루프를 15~60초 막아 다른 요청까지 멈추던 것."""
    _check_origin(request)
    body = await _read_capped(request)

    async def _replay() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    form = await Request(request.scope, _replay).form()  # 상한 아래라 해석기도 메모리에서만 다룬다
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise HTTPException(status_code=400, detail="file 필드가 필요합니다")
    content = await file.read()
    await form.close()
    try:
        export = file_adapter.load_from_bytes(content, getattr(file, "filename", None) or "upload.txt")
    except file_adapter.UploadError as exc:   # 고정 문구만 — 해석기 예외 원문을 화면에 내지 않는다
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    posts = export["posts"]
    _check_posts(posts)
    return await _admission.run(request, _run_pipeline, export["user_ref"], posts)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.getenv("ANALYZER_PORT", "8000")))
