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
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
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
from kopl.c4_stage2.residence import find_residence
from apps.analyzer.adapters import file_adapter, sns_adapter

log = logging.getLogger("analyzer")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
SNS_BASE = os.getenv("SNS_BASE_URL", "http://localhost:3000")   # 서버가 Veilo 를 부르는 주소 (adapter)
# 브라우저가 보는 Veilo 주소 — 「Veilo 로 돌아가기」 · 글 링크. 빈 값 = 같은 도메인 루트(인스턴스 veilo.site)
# 로컬에서 따로 띄우면 SNS_PUBLIC_URL=http://localhost:3000 (Veilo 쪽 PADO_BASE 와 짝)
SNS_PUBLIC_URL = os.getenv("SNS_PUBLIC_URL", "").rstrip("/")

app = FastAPI(title="분석기 (mock)")


class _RevalidatedStatic(StaticFiles):
    """화면 · 스크립트 · 스타일은 쓸 때마다 서버에 「바뀌었나」를 물어보게 한다(Cache-Control: no-cache).
    StaticFiles 는 Last-Modified · ETag 만 붙여서 브라우저가 스스로 정한 기간 동안 묻지도 않고 옛 파일을 썼다 —
    배포 직후에도 diagnosis.html 이 예전 모양으로 보였다(E 리뷰 #381). no-cache 는 「저장 금지」가 아니라
    「쓰기 전에 확인」이라 안 바뀌었으면 304 로 본문 없이 끝난다. 이 헤더를 한 번 받은 뒤부터 적용된다 —
    배포 전에 받아 둔 옛 파일은 브라우저가 그대로 쓸 수 있으니 ?v= 버전 표시는 그대로 둔다"""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if path.endswith((".html", ".js", ".css")):
            resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/static", _RevalidatedStatic(directory=STATIC_DIR), name="static")

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


@app.get("/api/scan-queue")
def scan_queue(ticket: str = Query(min_length=8, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")):
    """대기 순서 — 점검을 보낸 화면이 자기 대기표로 1초마다 묻는다. 줄에 서 있으면 앞사람 수(점검 중 포함), 아니면 waiting false.
    대기표 말고는 아무것도 돌려주지 않는다(다른 사람의 계정 · 글 · 수를 알 수 없다)."""
    n = _admission.ahead(ticket)
    return {"waiting": n is not None, "ahead": n or 0}


def _run_pipeline(user_ref: str, posts: list[dict]) -> dict:
    _check_posts(posts)
    t0 = time.perf_counter()
    out = _pipeline(user_ref, posts)   # 실패한 점검(예외)은 속도를 배우지 않는다 — 빨리 끝난 실패가 예상을 망치지 않게 (Codex 10/14)
    _learn_rate(_chars(posts), time.perf_counter() - t0)
    return out


_LOC_SPAN_TYPES = ("LOC_ADMIN", "LOC_FACILITY")


def _without_location(posts: list[dict], spans_by_post: dict[str, dict]) -> tuple[list[dict], dict[str, dict]]:
    """해외 거주로 보일 때 k · 위험도 · 2단에 넘길 입력 — 위치 스팬(LOC_ADMIN · LOC_FACILITY)과 위치 태그를 뺀다.

    국내 인구 사전으로 사는 곳을 세지 않는다 — 외국 지명은 어차피 사전에 없고, 남는 것은 「예산」 「음성」처럼 지명과 글자가
    같은 일반 낱말이다. 나이 · 성별 · 직업 · 가족 · 통근 · 소득 스팬은 그대로 둔다. 원본(posts · spans)은 바꾸지 않는다 —
    화면 하이라이트는 원래 스팬을 그대로 쓴다."""
    k_posts = [{**p, "activity_meta": {**p["activity_meta"], "geo_tag": None}}
               if (p.get("activity_meta") or {}).get("geo_tag") else p for p in posts]
    k_spans = {pid: {**res, "spans": [s for s in res.get("spans") or [] if s.get("type") not in _LOC_SPAN_TYPES]}
               for pid, res in spans_by_post.items()}
    return k_posts, k_spans


def _abstain_location(stage2: dict) -> None:
    """2단 location 판정을 기권으로 — 위치 스팬을 뺀 입력이면 모델 · 규칙 모두 기권이 나오지만, 목 엔진 · 모델의 근거 없는
    판정까지 확실히 막는다. 계약(stage2-io)의 abstain 모양 그대로(근거 없음 · 신뢰도 0.25 이하)."""
    findings = (stage2.get("output") or {}).get("findings")
    if isinstance(findings, dict) and "location" in findings:
        findings["location"] = {"verdict": "abstain", "granularity": None, "evidence": [], "confidence": 0.1,
                                "cross_post": False}


def _residence_view(res: dict) -> dict:
    """화면에 넘길 해외 거주 판별 — 여부 · 나라 · 글 수 · 근거 표현(글쓴이 본인 글의 짧은 조각, direct_identifiers 와 같은 방식)."""
    return {
        "overseas": res["overseas"],
        "country": res["country"],
        "location_excluded": res["overseas"],   # 위치 단서를 k · 위험도 · 2단 location 에서 뺐다
        "rule": res["rule"],
        "n_posts": {k: len(v) for k, v in res["posts"].items()},
        "evidence": [{k: h[k] for k in ("post_id", "text_id", "start", "end", "value")} for h in res["evidence"]]
        if res["overseas"] else [],
    }


def _pipeline(user_ref: str, posts: list[dict]) -> dict:
    inputs = {p["post_id"]: _detect_input(p) for p in posts}
    spans_by_post = {pid: engine.detect_spans(rec) for pid, rec in inputs.items()}
    # 해외 거주 판별 — 본인 거주 표현(「미국에서 지내다 보니」 「미국생활」)이 여러 글에 있고 국내 거주 단서보다 많을 때만 (residence.py).
    # 해외로 보이면 사는 곳은 국내 인구 기준으로 추정하지 않는다 — 아래 k · 위험도 · 2단에 위치 단서를 넘기지 않는다
    residence = find_residence({p["post_id"]: _channels(p) for p in posts},
                               {pid: res.get("spans") or [] for pid, res in spans_by_post.items()})
    k_posts, k_spans = _without_location(posts, spans_by_post) if residence["overseas"] else (posts, spans_by_post)
    # 조건 · k · 기여도 — real: k 엔진(본인 단서 · 여러 글 교집합 · 위치태그) · LOO / mock: 형식만
    conditions = engine.conditions(k_posts, k_spans)
    spec = engine.specificity({"user_ref": user_ref, "conditions": conditions})
    contrib = engine.contribution(user_ref, k_posts, spans_by_post=k_spans)

    baseline = contrib["output"]["baseline_risk"]
    target = round(max(baseline - 40.0, 0.0), 1)
    # 이번 요청의 스팬을 그대로 넘긴다 — 엔진 전역에 원문을 두지 않는다 (A3 · 동시 점검이 섞이지 않게)
    # 1단에 넣은 입력(채널)도 그대로 — 2단 근거의 원문과 스팬 offset 이 같은 글에서 나온다
    stage2 = engine.stage2(user_ref, k_posts, risk_current=baseline, risk_target=target, spans_by_post=k_spans,
                           detect_inputs=inputs)
    if residence["overseas"]:
        _abstain_location(stage2)

    return {
        "user_ref": user_ref,
        "posts": posts,
        "spans": spans_by_post,
        "specificity": spec,
        "contribution": contrib,
        "k_by_post": engine.per_post_k(k_posts, k_spans),
        "stage2": stage2,
        # 조치별 「바꾸면 같은 조건의 사람 몇 명」 — 비공개(k_by_post)와 같은 k 계산을 위치 태그 지우기 · 바꿔 쓰기에도.
        # stage2-io Action 에 사람 수 칸이 없어 계약 밖 · 화면 전용으로 둔다 (k_by_post 와 같은 방식)
        "k_by_action": engine.projected_k(k_posts, k_spans, stage2.get("output")),
        # k 를 실제로 정한 단서와 근거 스팬 — 작성자가 「내 얘기 아님」으로 확인한다(/api/recompute · 화면 전용 · 계약 밖)
        "decisive_clues": engine.decisive_clues(k_posts, k_spans, spec.get("output")),
        # 해외 거주 판별 — 해외로 보이면 사는 곳을 국내 인구 기준으로 추정하지 않았다는 안내 · 근거(화면 전용 · 계약 밖).
        # stage2-io 에 해외 값 · 이유 칸이 없어 location 은 abstain 으로만 두고, 여부와 근거는 여기로 넘긴다
        "residence": _residence_view(residence),
        # 계정 링크 · 이메일 · 전화 · @아이디 — 하나만으로 글쓴이에게 닿는다. k 로 잴 대상이 아니라 위험 점수와 별개로 먼저 안내한다
        # (스팬 계약 밖 · 화면 전용). 글마다 [{text_id, start, end, kind, label, value}]
        "direct_identifiers": {p["post_id"]: find_direct_identifiers(_channels(p)) for p in posts},
        # 글을 합치면 드러나는 시점 — 「날짜 + n일차/n주차」에서 시작일을 역산해, 여러 글이 같은 시작을 가리키면 묶는다 (#331).
        # 본문 날짜가 없으면 SNS export 의 작성 날짜(post_date · #334)를 기준점으로 쓴다. 파일 업로드는 작성일이 없어 본문 날짜만.
        # 스팬 계약 밖 · 화면 전용 — direct_identifiers 와 같은 방식
        "timeline": infer_starts({p["post_id"]: find_marks(_channels(p), p.get("post_date")) for p in posts}),
    }


# ── 결정 단서 확인 — 「내 얘기 아님」으로 뺀 단서를 빼고 k · 위험도를 다시 센다 ─────────────────────────
#    서버는 점검 결과를 보관하지 않는다(화면이 sessionStorage 에 둔다). 그래서 화면이 처음 결과의 글 · 스팬 · 2단 출력과
#    뺄 단서 목록을 그대로 다시 보내고, 서버는 계산만 하고 버린다 — 원문을 새로 저장하지 않는다.
#    다시 세는 것: 조건 · k(specificity) · 기여도(contribution · 위험도) · 글별 k · 조치별 k · 결정 단서.
#    다시 돌리지 않는 것: 1단 탐지 · 2단 판정과 추천(사용자당 수십 초) — 화면에 「처음 점검 기준」이라고 밝힌다
MAX_RECOMPUTE_BYTES = 4_000_000   # 글(업로드 상한 약 1MB) + 스팬 + 2단 출력
MAX_RECOMPUTE_SPANS = 20_000
_USER_REF = re.compile(r"^u_[0-9a-f]{8,}$")
_SPAN_STR = ("span_id", "text_id", "text", "type", "level", "subject")
_SPAN_ENUM = {"level": {"explicit", "implicit", "inferential"}, "subject": {"self", "other", "unknown"}}   # span.schema.json


class _BadResult(ValueError):
    """화면이 보낸 점검 결과의 모양이 어긋났다 — 400 고정 문구로 답한다."""


def _clean_spans(raw, post_ids: set[str]) -> dict[str, dict]:
    """화면이 돌려보낸 스팬 — 계약 8필드 중 계산에 쓰는 칸만 남긴다. 모르는 글의 스팬은 버린다."""
    if not isinstance(raw, dict):
        raise _BadResult("spans")
    out: dict[str, dict] = {pid: {"spans": []} for pid in post_ids}
    n = 0
    for pid, entry in raw.items():
        if pid not in post_ids:
            continue
        spans = entry.get("spans") if isinstance(entry, dict) else None
        if not isinstance(spans, list):
            raise _BadResult("spans")
        for s in spans:
            if not isinstance(s, dict) or not all(isinstance(s.get(k), str) for k in _SPAN_STR) \
                    or not all(isinstance(s.get(k), int) and not isinstance(s.get(k), bool) for k in ("start", "end")) \
                    or any(s[k] not in allowed for k, allowed in _SPAN_ENUM.items()) or not 0 <= s["start"] <= s["end"]:
                raise _BadResult("span")
            n += 1
            if n > MAX_RECOMPUTE_SPANS:
                raise _BadResult("too many spans")
            out[pid]["spans"].append({k: s[k] for k in (*_SPAN_STR, "start", "end")})
    return out


def _list(v, what: str) -> list:
    if v is None:
        return []
    if not isinstance(v, list):
        raise _BadResult(what)
    return v


def _clean_stage2_output(raw) -> dict:
    """조치별 k(projected_k)에 쓰는 칸만 — 추천 조치의 대상 글 · 바꿔 쓰기 후보 스팬. 모양이 어긋나면 400."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _BadResult("stage2_output")
    rec = raw.get("recommendation")
    if rec is not None and not isinstance(rec, dict):
        raise _BadResult("recommendation")
    actions = []
    for a in _list((rec or {}).get("actions"), "actions"):
        if not isinstance(a, dict) or not isinstance(a.get("action_type"), str):
            raise _BadResult("action")
        targets = [{"kind": t.get("kind"), "ref": t["ref"]} for t in _list(a.get("targets"), "targets")
                   if isinstance(t, dict) and isinstance(t.get("ref"), str)]
        actions.append({"action_type": a["action_type"], "targets": targets})
    rewrites = [{"post_id": r["post_id"], "span_id": r["span_id"]} for r in _list(raw.get("rewrites"), "rewrites")
                if isinstance(r, dict) and isinstance(r.get("post_id"), str) and isinstance(r.get("span_id"), str)]
    return {"recommendation": {"actions": actions}, "rewrites": rewrites}


def _parse_exclude(exclude) -> tuple[set[tuple[str, str]], set[str]]:
    """「내 얘기 아님」 목록 — 스팬은 (post_id, span_id), 위치 태그는 (post_id, geo_tag: true)."""
    if not isinstance(exclude, list) or len(exclude) > MAX_RECOMPUTE_SPANS:
        raise _BadResult("exclude")
    drop_spans: set[tuple[str, str]] = set()
    drop_tags: set[str] = set()
    for e in exclude:
        if not isinstance(e, dict) or not isinstance(e.get("post_id"), str):
            raise _BadResult("exclude item")
        if e.get("geo_tag") is True:
            drop_tags.add(e["post_id"])
        elif isinstance(e.get("span_id"), str):
            drop_spans.add((e["post_id"], e["span_id"]))
        else:
            raise _BadResult("exclude item")
    return drop_spans, drop_tags


def _apply_exclusions(posts: list[dict], spans_by_post: dict[str, dict],
                      exclude: tuple[set[tuple[str, str]], set[str]]) -> tuple[list[dict], dict[str, dict], dict]:
    """뺄 스팬 · 위치 태그를 뺀 사본. 원본은 바꾸지 않는다."""
    drop_spans, drop_tags = exclude
    spans = {pid: {"spans": [s for s in res["spans"] if (pid, s["span_id"]) not in drop_spans]}
             for pid, res in spans_by_post.items()}
    kept = [{**p, "activity_meta": {**(p.get("activity_meta") or {}), "geo_tag": None}}
            if p["post_id"] in drop_tags else p for p in posts]
    n_spans = sum(len(spans_by_post[pid]["spans"]) - len(spans[pid]["spans"]) for pid in spans_by_post)
    n_tags = sum(1 for p in posts if p["post_id"] in drop_tags and (p.get("activity_meta") or {}).get("geo_tag"))
    return kept, spans, {"n_spans": n_spans, "n_geo_tags": n_tags}


def _recompute(user_ref: str, posts: list[dict], spans_by_post: dict[str, dict], stage2_output: dict,
               exclude: tuple[set[tuple[str, str]], set[str]]) -> dict:
    """처음 점검(_pipeline)과 같은 순서로 k · 위험도만 다시 센다 — 해외 거주 판별은 처음 스팬(뺀 것 포함)으로 다시 한다.
    처음 점검과 같은 입력이면 같은 판별이 나와야 하고, 화면이 보낸 판별 결과를 믿지 않아도 된다."""
    residence = find_residence({p["post_id"]: _channels(p) for p in posts},
                               {pid: res["spans"] for pid, res in spans_by_post.items()})
    kept_posts, kept_spans, n = _apply_exclusions(posts, spans_by_post, exclude)
    k_posts, k_spans = _without_location(kept_posts, kept_spans) if residence["overseas"] else (kept_posts, kept_spans)
    conditions = engine.conditions(k_posts, k_spans)
    spec = engine.specificity({"user_ref": user_ref, "conditions": conditions})
    return {
        "specificity": spec,
        "contribution": engine.contribution(user_ref, k_posts, spans_by_post=k_spans),
        "k_by_post": engine.per_post_k(k_posts, k_spans),
        "k_by_action": engine.projected_k(k_posts, k_spans, stage2_output),
        "decisive_clues": engine.decisive_clues(k_posts, k_spans, spec.get("output")),
        "residence": _residence_view(residence),
        # 실제로 빠진 수 — 화면이 보낸 목록 중 지금 결과에 있는 것만 센다
        "clue_exclusions": n,
    }


def _parse_recompute(body: bytes) -> tuple[str, list[dict], dict[str, dict], dict, tuple]:
    """입력 검사는 모두 여기서 — 점검 자리(_admission)를 잡기 전에 끝낸다."""
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise _BadResult("json") from exc
    if not isinstance(doc, dict):
        raise _BadResult("json")
    user_ref = doc.get("user_ref")
    if not isinstance(user_ref, str) or not _USER_REF.fullmatch(user_ref):
        raise _BadResult("user_ref")
    try:
        posts = file_adapter.clean_posts(doc.get("posts"))
    except file_adapter.UploadError as exc:
        raise _BadResult("posts") from exc
    spans = _clean_spans(doc.get("spans"), {p["post_id"] for p in posts})
    exclude = doc.get("exclude")
    return (user_ref, posts, spans, _clean_stage2_output(doc.get("stage2_output")),
            _parse_exclude([] if exclude is None else exclude))


# ── 점검 입장 제한 (A1) — 점검 하나가 2 vCPU 를 15~60초 다 쓴다. 동시에 여러 개를 돌리면 모두 느려지고 메모리가 모자란다.
#    한 번에 SCAN_CONCURRENCY 개(기본 1)만 돌리고, 기다리는 요청은 SCAN_QUEUE_MAX 개(기본 3)까지 SCAN_QUEUE_WAIT 초(기본 90)만 기다린다.
#    넘치면 429 + 고정 문구 — 화면(scan.html failMsg · action.html 다시 점검 · Veilo 글쓰기 점검)이 이 문구를 그대로 보인다
BUSY_DETAIL = "지금 다른 점검이 진행 중입니다. 잠시 뒤 다시 시도해 주세요."
SCAN_CONCURRENCY = max(1, int(os.getenv("SCAN_CONCURRENCY", "1")))
SCAN_QUEUE_MAX = max(0, int(os.getenv("SCAN_QUEUE_MAX", "3")))
SCAN_QUEUE_WAIT = max(0.0, float(os.getenv("SCAN_QUEUE_WAIT", "90")))
_POLL_S = 0.2
_TICKET = re.compile(r"[A-Za-z0-9_-]{8,40}")   # 화면이 만든 대기표 — 다른 값은 받지 않는다


class _Admission:
    """프로세스 하나에 하나 — 점검 자리(세마포어)와 기다리는 줄의 길이.

    자리는 이벤트 루프에서 「막지 않고」 잡는다(acquire(blocking=False) + 짧은 sleep) — 기다리는 동안에도 다른 요청
    (엔진 배지 · 계정 찾기 · Veilo 화면)을 받는다. 기다리다 브라우저가 떠나면(글쓰기 실시간 점검의 abort) 줄에서 빠진다.
    자리는 점검을 실제로 돌린 스레드가 돌려준다 — 기다리던 코루틴이 취소돼도 점검이 끝나기 전에 자리가 풀리지 않게."""

    def __init__(self, concurrency: int, queue_max: int, wait_s: float):
        self.sem = threading.BoundedSemaphore(concurrency)
        # 점검 전용 스레드 — 공용 스레드 풀(AnyIO 기본 40개)이 다른 요청으로 차 있어도 자리를 잡은 점검은 바로 시작한다.
        # 공용 풀에서 스레드를 기다리면 그 기다림은 90초 한도 · 연결 끊김 확인 밖이라, 떠난 요청의 점검이 나중에 돌았다 (Codex 검토)
        self.pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="scan")
        self.queue_max, self.wait_s = queue_max, wait_s
        self._lock = threading.Lock()
        self.waiting = 0
        # 대기 순서 표시 — 화면이 보낸 대기표(X-Scan-Ticket) → 줄에 선 차례. 점검 중인 수(running)와 합쳐 「앞에 N명」을 만든다.
        # 자리는 폴링으로 잡아서 엄밀한 선착순은 아니다(먼저 선 사람이 거의 늘 먼저 잡는다) — 화면에는 어림으로만 쓴다
        self.running = 0
        self._order = 0
        self._waiters: set[int] = set()          # 줄에 선 모든 요청의 순번 — 대기표가 없는 요청도 센다(Codex P2)
        self._tickets: dict[str, int] = {}       # 대기표 → 그 요청의 순번. 같은 표가 이미 줄에 있으면 뒤 요청은 등록하지 않는다(Codex P3)

    def _take(self) -> None:
        with self._lock:
            self.running += 1

    def release(self) -> None:
        with self._lock:
            self.running = max(0, self.running - 1)
        self.sem.release()

    def _head(self, order: int) -> bool:
        """줄 맨 앞인가 — 자리가 비면 맨 앞만 잡는다. 아니면 먼저 깨어난 뒷사람이 새치기한다(E 리뷰 #374 · 두 번 재현)."""
        with self._lock:
            return order == min(self._waiters)

    def ahead(self, ticket: str) -> int | None:
        """대기표의 앞사람 수(점검 중 + 먼저 선 사람). 줄에 없으면(점검 중 · 끝남 · 모르는 표) None."""
        with self._lock:
            mine = self._tickets.get(ticket)
            if mine is None:
                return None
            return self.running + sum(1 for o in self._waiters if o < mine)

    async def acquire(self, request: Request | None = None) -> None:
        # 바로 잡기는 줄이 비어 있을 때만 — 자리가 빈 순간 새로 온 요청이 줄을 건너뛰지 않게 (Codex · #374 FIFO)
        with self._lock:
            if not self._waiters and self.sem.acquire(blocking=False):
                self.running += 1
                return
        ticket = request.headers.get("x-scan-ticket", "") if request is not None else ""
        ticket = ticket if _TICKET.fullmatch(ticket) else ""
        with self._lock:
            if self.waiting >= self.queue_max:
                raise HTTPException(status_code=429, detail=BUSY_DETAIL, headers={"Retry-After": "30"})
            self.waiting += 1
            self._order += 1
            order = self._order
            self._waiters.add(order)
            if ticket and ticket not in self._tickets:
                self._tickets[ticket] = order
        try:
            deadline = time.monotonic() + self.wait_s
            while not (self._head(order) and self.sem.acquire(blocking=False)):
                if time.monotonic() >= deadline:
                    raise HTTPException(status_code=429, detail=BUSY_DETAIL, headers={"Retry-After": "30"})
                if request is not None and await request.is_disconnected():
                    raise HTTPException(status_code=499, detail="요청이 취소되었습니다")
                await asyncio.sleep(_POLL_S)
            self._take()
        finally:
            with self._lock:
                self.waiting -= 1
                self._waiters.discard(order)
                if ticket and self._tickets.get(ticket) == order:   # 내가 등록한 표만 지운다
                    del self._tickets[ticket]

    async def _in_thread(self, work):
        return await asyncio.get_running_loop().run_in_executor(self.pool, work)

    async def run(self, request: Request | None, fn, *args):
        """자리를 잡고 fn(*args) 를 스레드에서 돌린다. 자리는 그 스레드가 끝날 때 돌려준다."""
        await self.acquire(request)
        # 자리를 돌려줄 쪽은 정확히 하나 — 스레드가 먼저 「시작」을 적으면 스레드가, 기다리던 쪽이 먼저 「취소」를 적으면
        # 기다리던 쪽이 돌려준다(취소된 뒤 늦게 도는 스레드는 점검도 반환도 하지 않는다). 둘 다 돌려주면 자리가 늘어난다 (Codex 검토)
        state = {"v": "pending"}
        state_lock = threading.Lock()

        def work():
            with state_lock:
                if state["v"] == "cancelled":
                    return None
                state["v"] = "running"
            try:
                return fn(*args)
            finally:
                self.release()

        try:
            # 자리를 잡는 사이 떠났으면 돌리지 않는다 — 이 확인도 반환 보호 안에서 (여기서 취소돼도 자리를 돌려준다 · Codex 2차)
            if request is not None and await request.is_disconnected():
                raise HTTPException(status_code=499, detail="요청이 취소되었습니다")
            return await self._in_thread(work)
        except BaseException:
            with state_lock:
                if state["v"] == "pending":
                    state["v"] = "cancelled"
                    self.release()
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
    # 요즘 브라우저는 Sec-Fetch-Site 를 싣는다(페이지 스크립트가 못 바꾼다) — same-origin 이면 Host 헤더와 상관없이 통과.
    # nginx 가 Host 를 내부 주소로 바꿔 넘겨도 운영(veilo.site/check) 화면이 막히지 않게 (Codex 검토)
    if request.headers.get("sec-fetch-site") == "same-origin":
        return
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
    # 업로드와 같은 상한 · 형식 검사 — Veilo 세션 사본에 아주 긴 글을 써 두고 /scan 으로 점검 자리를 오래 붙잡지 못하게 (Codex 검토).
    # 시드 계정은 모두 안에 들어간다 (가장 긴 E15 30편 · 약 97,000자)
    try:
        posts = file_adapter.clean_posts(export.get("posts", []))
    except file_adapter.UploadError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    _check_posts(posts)   # 줄에 서기 전에 — 틀린 입력이 자리를 차지하지 않게
    return await _admission.run(request, _run_pipeline, user_ref, posts)


# 업로드 상한 — 멀티파트 해석기는 1MiB(1,048,576B)를 넘는 파일을 임시 파일(디스크)로 넘긴다. 받은 본문 전체를
# 그보다 작게 묶어 「메모리에서 읽고 버린다」를 지킨다. 헤더(Content-Length)는 속일 수 있으니 실제로 받은 바이트를 센다
MAX_UPLOAD_BYTES = 1_040_000


async def _read_capped(request: Request, limit: int = MAX_UPLOAD_BYTES,
                       detail: str = "파일이 너무 큽니다 (약 1MB 이하)") -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise HTTPException(status_code=413, detail=detail)
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


@app.post("/api/recompute")
async def recompute(request: Request):
    """결정 단서 확인 — 화면이 처음 점검 결과(글 · 스팬 · 2단 출력)와 「내 얘기 아님」 목록을 보내면 k · 위험도만 다시 센다.
    받은 본문은 메모리에서 계산하고 버린다. 계산은 점검과 같은 자리(_admission)에서 돈다 — 글이 많으면 몇 초 CPU 를 쓴다."""
    _check_origin(request)
    body = await _read_capped(request, MAX_RECOMPUTE_BYTES, "점검 결과가 너무 큽니다")
    try:
        user_ref, posts, spans, stage2_output, exclude = _parse_recompute(body)
    except _BadResult as exc:
        log.info("다시 계산 입력 거부: %s", exc)
        raise HTTPException(status_code=400, detail="점검 결과 형식이 올바르지 않습니다. 다시 점검해 주세요") from exc
    _check_posts(posts)
    return await _admission.run(request, _recompute, user_ref, posts, spans, stage2_output, exclude)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.getenv("ANALYZER_PORT", "8000")))
