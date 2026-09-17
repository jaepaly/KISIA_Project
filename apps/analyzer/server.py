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


_AXIS_BY_TYPE = {
    "LOC_FACILITY": "location", "LOC_ADMIN": "location",
    "REL_HOME": "location", "REL_WORK": "location",
    "AGE": "age", "SEX": "sex", "JOB": "occupation",
    "FAM": "family", "COMMUTE": "commute", "INCOME": "income",
}


def _derive_conditions(spans_by_post: dict[str, dict], all_post_ids: list[str]) -> list[dict]:
    """탐지된 스팬 유형에서 특정성 엔진에 넘길 조건을 만든다.

    실제 조건 산출은 C 몫이다. 여기서는 목 엔진이 요구하는 최소 형태(계약의
    conditions minItems 1)만 채운다.
    """
    by_axis: dict[str, list[str]] = {}
    for post_id, result in spans_by_post.items():
        for span in result["spans"]:
            axis = _AXIS_BY_TYPE.get(span["type"])
            if axis:
                by_axis.setdefault(axis, []).append(post_id)

    if not by_axis:
        # 네거티브 컨트롤 — 탐지된 단서가 하나도 없다. axis를 location이 아닌
        # 값으로 둬 mock.specificity가 UNKNOWN(산출 불가)을 내도록 한다.
        return [{
            "axis": "occupation", "kind": "none_detected", "value": "MOCK_NONE",
            "resolution": 0, "confidence": 0.0,
            "source_post_ids": all_post_ids or ["mock_post"],
        }]

    conditions = []
    for axis, post_ids in by_axis.items():
        cond = {
            "axis": axis, "kind": "mock_detected", "value": "MOCK",
            "resolution": 1, "confidence": 0.5,
            "source_post_ids": sorted(set(post_ids)),
        }
        if axis == "location":
            cond["geo_code"] = "4146351000"
        conditions.append(cond)
    return conditions


def _run_pipeline(user_ref: str, posts: list[dict]) -> dict:
    spans_by_post = {
        p["post_id"]: engine.detect_spans({"post_id": p["post_id"], "body": p.get("body", "")})
        for p in posts
    }
    conditions = _derive_conditions(spans_by_post, [p["post_id"] for p in posts])
    spec = engine.specificity({"user_ref": user_ref, "conditions": conditions})
    contrib = engine.contribution(user_ref, posts)

    baseline = contrib["output"]["baseline_risk"]
    target = round(max(baseline - 40.0, 0.0), 1)
    stage2 = engine.stage2(user_ref, posts, risk_current=baseline, risk_target=target)

    return {
        "user_ref": user_ref,
        "posts": posts,
        "spans": spans_by_post,
        "specificity": spec,
        "contribution": contrib,
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
