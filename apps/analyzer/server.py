"""분석기 서버. 화면 3개(스캔·진단·조치)를 엔진에 연결한다.

    ENGINE_MODE=mock uvicorn apps.analyzer.server:app --port 8000 --reload

경계: 가상 SNS 서비스에서는 HTTP로만 글을 받는다(adapters/sns_adapter.py).
그 서비스의 저장소나 내부 모듈을 이 디렉토리에서 직접 import하지 않는다.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from apps.analyzer import engines as engine
from kopl.c4_stage2.links import find_direct_identifiers
from apps.analyzer.adapters import file_adapter, sns_adapter

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
SNS_BASE = os.getenv("SNS_BASE_URL", "http://localhost:3000")

app = FastAPI(title="분석기 (mock)")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root():
    return RedirectResponse("/static/scan.html")


@app.get("/api/engine-mode")
def engine_mode():
    """화면 하단 배지용 — 지금 mock인지 real인지."""
    return {"mode": os.getenv("ENGINE_MODE", "mock"), "c1_rules": os.getenv("C1_RULES", "1") != "0"}  # c1_rules.py 와 같은 기본값(켬)


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
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise HTTPException(status_code=400, detail=f"같은 post_id 가 여러 번 있습니다: {', '.join(dup[:5])}")


def _run_pipeline(user_ref: str, posts: list[dict]) -> dict:
    _check_posts(posts)
    spans_by_post = {p["post_id"]: engine.detect_spans(_detect_input(p)) for p in posts}
    # 조건 · k · 기여도 — real: k 엔진(본인 단서 · 여러 글 교집합 · 위치태그) · LOO / mock: 형식만
    conditions = engine.conditions(posts, spans_by_post)
    spec = engine.specificity({"user_ref": user_ref, "conditions": conditions})
    contrib = engine.contribution(user_ref, posts, spans_by_post=spans_by_post)

    baseline = contrib["output"]["baseline_risk"]
    target = round(max(baseline - 40.0, 0.0), 1)
    stage2 = engine.stage2(user_ref, posts, risk_current=baseline, risk_target=target)

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
    }


@app.post("/scan/{user_ref}")
def scan(user_ref: str):
    try:
        export = sns_adapter.load(user_ref, base=SNS_BASE)
    except Exception as exc:  # SNS 서버 다운·404 등
        raise HTTPException(status_code=502, detail=f"내보내기 조회 실패: {exc}") from exc
    return _run_pipeline(user_ref, export.get("posts", []))


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
    """수동 업로드 경로. 파일은 메모리에서 읽고 버린다 — 디스크에 쓰지 않는다."""
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
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_pipeline(export["user_ref"], export.get("posts", []))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.getenv("ANALYZER_PORT", "8000")))
