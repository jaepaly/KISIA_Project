"""B·C·D 완성 후 여기로 교체한다. 부분 교체 가능 — 아직 안 온 함수는
mock에서 그대로 가져와 쓴다 (docs/roles/howto/e-integration.md §3).

c1(스팬 탐지)과 stage2(2단 판정 + 추천 엔진 v1)가 실제다. c1 은 B 의 v1 체크포인트를 experiments/exp06-finetune/infer.py
의 SpanDetector 로 부른다. 가이드 예시(kopl.c1_span.predict)와 다르게 가는 이유:
  - local_files_only=True — 체크포인트를 허브에서 받으러 나가지 않는다 (외부 요청 0건)
  - 체크포인트가 없으면 에러 — kopl 쪽은 조용히 목 결과로 폴백해 진짜와 구분이 안 된다
  - 임계값 0.7 · 긴 글 창 나눔 — W7 성능 수치(#276)를 잰 경로와 같다

체크포인트는 gitignore 경로에 둔다 (#266). 다른 곳에 뒀으면 C1_CHECKPOINT_DIR 로 지정.
"""

from __future__ import annotations

import os
import sys
import threading
import unicodedata
from collections import OrderedDict
from pathlib import Path

from .c23 import conditions, contribution, per_post_k, specificity  # noqa: F401 — C2·C3 실제 (k 엔진 · LOO)
from . import c1_rules as _c1_rules

_ROOT = Path(__file__).resolve().parents[3]
_EXP06 = _ROOT / "experiments" / "exp06-finetune"
_DEFAULT_CHECKPOINT = _EXP06 / "runs" / "v1_lr5e-5" / "checkpoint-epoch-10"
_MIN_SPAN_SCORE = 0.7  # v1 운용 임계값 (#266 B 코멘트)

# infer.py 는 같은 폴더의 train·prepare_bio 와 kopl.c1_span.schema 를 import 한다
for _path in (_EXP06, _ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import infer  # noqa: E402
from kopl.c4_stage2.infer import analyze as _stage2_analyze  # noqa: E402

from kopl.c4_stage2.infer import _get_model as _load_stage2  # noqa: E402

# 2단 실행 방식 — auto: GPU·어댑터가 있으면 모델, 없으면 규칙 폴백 · rules: 규칙만 · model: 모델만(없으면 에러)
_STAGE2_MODE = os.getenv("STAGE2_MODE", "auto")
_STAGE2_TARGET = float(os.getenv("STAGE2_TARGET_RISK", "40"))

from kopl.c1_span.attributes import resolve as resolve_attributes  # noqa: E402


def _attributes(texts: dict, candidate: dict) -> dict:
    """level·subject 판정 — 규칙 판정기 (kopl.c1_span.attributes · exp16).

    모델은 level·subject 를 예측하지 않는다. 임시값(implicit/self)을 쓰면 타인 단서(「친구가 [화정에서]」)도
    본인 것으로 k 를 좁히고, 「본인 명시 단서」를 다루는 추천·바꿔 쓰기가 한 번도 돌지 않는다.
    """
    return resolve_attributes(texts, candidate)


def _load_detector() -> "infer.SpanDetector":
    checkpoint = Path(os.getenv("C1_CHECKPOINT_DIR", _DEFAULT_CHECKPOINT))
    if not (checkpoint / "config.json").is_file():
        raise RuntimeError(
            f"c1 체크포인트가 없다: {checkpoint}\n"
            "B 에게 받은 파일(config.json · model.safetensors · tokenizer*.json)을 이 폴더에 두거나 "
            "C1_CHECKPOINT_DIR 로 위치를 지정한다 (#266). 목 엔진으로 돌리려면 ENGINE_MODE=mock.")
    detector = infer.SpanDetector(checkpoint, device="cpu", min_span_score=_MIN_SPAN_SCORE)
    return detector


# 서버가 켜질 때 한 번만 로드한다 (글마다 로드하면 1편에 수십 초)
_DETECTOR = _load_detector()
# 2단 모델도 켜질 때 올린다 — 첫 요청이 30~50초 막히지 않게. 실패하면 이유를 남기고 규칙으로 돈다
if _STAGE2_MODE != "rules":
    _load_stage2()


# 진단 화면과 2단이 같은 스팬을 쓰도록, 서버가 탐지한 결과(그때의 채널 그대로)를 2단이 다시 쓴다.
# 서버가 제목·캡션을 넘기기 시작하면(E) 2단도 저절로 따라간다.
# ⚠️ 원문이 담기므로 「분석 후 즉시 파기」(file_adapter) — 2단이 꺼내 쓴 항목은 그 요청이 끝날 때 지운다.
# 2단까지 가지 못한 요청(중간 오류)의 항목만 남을 수 있어 개수를 묶는다 (메모리에만 있고 디스크에 안 쓴다)
_SPAN_CACHE: "OrderedDict[str, tuple[dict, dict]]" = OrderedDict()
_SPAN_CACHE_MAX = 2048
_SPAN_CACHE_LOCK = threading.Lock()


def _captions(post: dict) -> list[str]:
    """photo_captions(문자열 목록) 또는 SNS 내보내기 photos(``{"caption": …}`` 목록) → 캡션 문자열 목록."""
    raw = post.get("photo_captions")
    if raw is None:
        raw = post.get("photos") or []
    out = []
    for item in raw:
        caption = item.get("caption") if isinstance(item, dict) else item
        if isinstance(caption, str):
            out.append(caption)
    return out


def detect_spans(post: dict) -> dict:
    """B(c1) 자리. span.schema.json 준수 — infer.format_contract 가 스키마 검사까지 한다."""
    record = {key: post[key] for key in ("post_id", "title", "body") if post.get(key) is not None}
    if post.get("photo_captions") is not None or post.get("photos"):
        record["photo_captions"] = _captions(post)
    result = _c1_rules.detect(_DETECTOR, record, _attributes)  # C1_RULES=1 이면 명시 규칙 병합 (기본 꺼짐)
    with _SPAN_CACHE_LOCK:
        _SPAN_CACHE[record["post_id"]] = (record, result)
        _SPAN_CACHE.move_to_end(record["post_id"])
        while len(_SPAN_CACHE) > _SPAN_CACHE_MAX:
            _SPAN_CACHE.popitem(last=False)
    return result


def _texts(record: dict) -> dict[str, str]:
    """탐지에 넣은 채널 그대로 → {text_id: 원문}. 탐지기와 같게 NFC 로 맞춘다 (스팬 offset 기준)."""
    texts = {"title": record.get("title"), "body": record.get("body")}
    texts.update({f"photo_caption:{i}": c for i, c in enumerate(record.get("photo_captions") or [])})
    return {k: unicodedata.normalize("NFC", v) for k, v in texts.items() if isinstance(v, str) and v}


def _spans_for(post: dict) -> tuple[dict, dict]:
    """서버가 이 글을 탐지할 때 쓴 채널·결과를 찾는다. 글이 바뀌었거나 없으면 본문만 다시 탐지한다
    (서버 _run_pipeline 과 같은 채널 — 진단 화면 하이라이트와 2단 근거가 어긋나지 않게)."""
    with _SPAN_CACHE_LOCK:
        cached = _SPAN_CACHE.get(post["post_id"])
        if cached is not None:
            _SPAN_CACHE.move_to_end(post["post_id"])
    if cached and cached[0].get("body") == post.get("body"):
        return cached
    record = {"post_id": post["post_id"], "body": post.get("body", "")}
    return record, detect_spans(record)


def stage2(user_ref: str, posts: list[dict], risk_current: float = 0.0, risk_target: float = 40.0) -> dict:
    """D(c4) 자리. output 은 stage2-io Stage2Output 그대로 (findings · recommendation · provenance).

    - findings 는 2단 모델(GPU·어댑터가 없거나 출력이 깨지면 규칙 폴백 — provenance.model_version 에 이유)
    - recommendation 은 추천 엔진 v1. 현재 위험도는 C2 로 직접 계산하고, 목표는 서버가 넘긴 값이 아니라
      STAGE2_TARGET_RISK(기본 40 · 0~100 절대값)를 쓴다 — 서버의 목표는 아직 목 기여도에서 나온다
    - 스팬의 level·subject 는 아직 임시값이다 (_attributes · #266) — 판정이 들어오면 결과가 바뀐다
    """
    entries = []
    try:
        for post in posts:
            record, result = _spans_for(post)
            entries.append({
                "post_id": post["post_id"],
                "texts": _texts(record),
                "spans": result["spans"],
                "geo_tag": (post.get("activity_meta") or {}).get("geo_tag"),
            })
        output = _stage2_analyze(user_ref, entries, target_risk=_STAGE2_TARGET, mode=_STAGE2_MODE)
    finally:
        with _SPAN_CACHE_LOCK:
            for post in posts:
                _SPAN_CACHE.pop(post.get("post_id"), None)
    # 화면은 output 만 읽는다. 계약 Stage2Input 전체(가명 텍스트 · pseudonym_map)는 W9 — 여기는 요약만
    summary = {
        "user_ref": user_ref,
        "post_ids": [e["post_id"] for e in entries],
        "risk": {"current": output["recommendation"]["projected"]["current_risk"], "target": _STAGE2_TARGET},
        "note": "요약 — 계약 Stage2Input 이 아니다 (전체 입력은 아직 만들지 않는다)",
    }
    return {"input": summary, "output": output}
