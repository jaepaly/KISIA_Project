"""분석기 서버. 화면 3개(스캔·진단·조치)를 엔진에 연결한다.

    ENGINE_MODE=mock uvicorn apps.analyzer.server:app --port 8000 --reload

경계: 가상 SNS 서비스에서는 HTTP로만 글을 받는다(adapters/sns_adapter.py).
그 서비스의 저장소나 내부 모듈을 이 디렉토리에서 직접 import하지 않는다.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from apps.analyzer import engines as engine
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
    return {"mode": os.getenv("ENGINE_MODE", "mock")}


def _detect_input(post: dict) -> dict:
    """1단 입력 — 제목·본문·사진 캡션 (export 의 photos 는 [{"caption": ...}])."""
    captions = [ph.get("caption") if isinstance(ph, dict) else ph for ph in post.get("photos") or []]
    record = {"post_id": post["post_id"], "title": post.get("title"), "body": post.get("body") or "",
              "photo_captions": [c for c in captions if c]}
    return {k: v for k, v in record.items() if v not in (None, [])}


def _run_pipeline(user_ref: str, posts: list[dict]) -> dict:
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
    }


@app.post("/scan/{user_ref}")
def scan(user_ref: str):
    try:
        export = sns_adapter.load(user_ref, base=SNS_BASE)
    except Exception as exc:  # SNS 서버 다운·404 등
        raise HTTPException(status_code=502, detail=f"내보내기 조회 실패: {exc}") from exc
    return _run_pipeline(user_ref, export.get("posts", []))


@app.post("/upload")
async def upload_and_scan(file: UploadFile = File(...)):
    """수동 업로드 경로. 파일은 메모리에서 읽고 버린다 — 디스크에 쓰지 않는다."""
    content = await file.read()
    try:
        export = file_adapter.load_from_bytes(content, file.filename or "upload.txt")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_pipeline(export["user_ref"], export.get("posts", []))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.getenv("ANALYZER_PORT", "8000")))
