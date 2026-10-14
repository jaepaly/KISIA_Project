"""B·C·D 완성 후 여기로 교체한다. 부분 교체 가능 — 아직 안 온 함수는
mock에서 그대로 가져와 쓴다 (docs/roles/howto/e-integration.md §3).

c1(스팬 탐지)과 stage2(2단 판정 + 추천 엔진 v1)가 실제다. c1 은 B 의 **기준선 v2**(교사 라벨 재학습 + 명시 규칙 · DEC-011 ·
#310 · exp17b 본인 재현율 0.699 · exp17c 0.752) 체크포인트를 ``kopl.c1_span.infer`` 의 SpanDetector 로 부른다(experiments/exp06-finetune 에서 옮김 · D 9번). 가이드 예시(kopl.c1_span.predict)와 다르게 가는 이유:
  - local_files_only=True + HF_HUB_OFFLINE 기본값 — 체크포인트를 허브에서 받으러 나가지 않고 허브에 확인 요청도 안 한다 (외부 요청 0건)
  - 체크포인트가 없으면 에러 — kopl 쪽은 조용히 목 결과로 폴백해 진짜와 구분이 안 된다
  - 임계값 0.7 · 긴 글 창 나눔 — W7 성능 수치(#276)를 잰 경로와 같다

체크포인트는 gitignore 경로에 둔다 (#266). 다른 곳에 뒀으면 C1_CHECKPOINT_DIR 로 지정.
"""

from __future__ import annotations

import os
import sys
import unicodedata
from pathlib import Path

# 모델 허브 접속을 아예 끈다 — 실제 모드는 로컬 가중치만 쓴다 (외부 요청 0건).
# local_files_only=True 만으로는 부족했다: GPU 경로(2단 Qwen3-4B + QLoRA)에서 첫 기동 때 huggingface.co 로
# 연결이 한 번 나갔다 (10/7 PM 측정 · 이후 재현 안 됨 · 라이브러리의 확인 요청으로 보임). transformers 를
# 불러오기 전에 정해야 하므로 이 파일 맨 위에 둔다. 굳이 허브를 쓰려면 환경변수로 0 을 주면 된다
for _k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "HF_HUB_DISABLE_IMPLICIT_TOKEN"):
    os.environ.setdefault(_k, "1")

from .c23 import conditions, contribution, per_post_k, specificity  # noqa: F401 — C2·C3 실제 (k 엔진 · LOO)
from . import c1_rules as _c1_rules

_ROOT = Path(__file__).resolve().parents[3]
_EXP06 = _ROOT / "experiments" / "exp06-finetune"
# 기준선 v2 — 10/8 확정 (#310 · DEC-011) · exp17c 에서 후보(C그룹 + o-weight 0.05)보다 낫지 않아 유지 (#322 · 10/9).
# 예전 v1(`v1_lr5e-5/checkpoint-epoch-10`)로 비교하려면 C1_CHECKPOINT_DIR 로 지정
_DEFAULT_CHECKPOINT = _EXP06 / "runs" / "variant_base_20261008" / "checkpoint-epoch-10"
_MIN_SPAN_SCORE = 0.7  # 운용 임계값 — v1 (#266) · v2 (#310 · exp17b/exp17c 채점 조건) 같음

if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from kopl.c1_span import infer  # noqa: E402
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


_CHECKPOINT = Path(os.getenv("C1_CHECKPOINT_DIR", _DEFAULT_CHECKPOINT))


def c1_checkpoint() -> str:
    """지금 올라간 1단 체크포인트 — /api/engine-mode 에서 시연 PC 가 어느 폴더를 쓰는지 확인용 (README D 12번)."""
    from . import checkpoint_label

    return checkpoint_label(_CHECKPOINT)


def _load_detector() -> "infer.SpanDetector":
    checkpoint = _CHECKPOINT
    if not (checkpoint / "config.json").is_file():
        raise RuntimeError(
            f"c1 체크포인트가 없다: {checkpoint}\n"
            "B 에게 받은 파일(config.json · model.safetensors · tokenizer*.json)을 이 폴더에 두거나 "
            "C1_CHECKPOINT_DIR 로 위치를 지정한다 (#266). 목 엔진으로 돌리려면 ENGINE_MODE=mock.")
    detector = infer.SpanDetector(checkpoint, device="cpu", min_span_score=_MIN_SPAN_SCORE)
    return detector


def _set_torch_threads() -> None:
    """CPU 추론 스레드 수를 한 번 정한다 (TORCH_THREADS · 기본 2 = 운영 t3.medium vCPU 수). 점검은 한 번에 하나만
    돌므로(server SCAN_CONCURRENCY) 그 하나가 코어를 다 쓰게 하고, 웹 스레드와 다투지 않게 코어 수를 넘기지 않는다.
    목 모드는 이 파일을 불러오지 않아 torch 도 불러오지 않는다."""
    n = int(os.getenv("TORCH_THREADS", "2"))   # 0 이면 torch 기본값 그대로
    if n <= 0:
        return
    try:
        import torch
    except ImportError:
        return
    torch.set_num_threads(n)


_set_torch_threads()
# 서버가 켜질 때 한 번만 로드한다 (글마다 로드하면 1편에 수십 초)
_DETECTOR = _load_detector()
# 2단 모델도 켜질 때 올린다 — 첫 요청이 30~50초 막히지 않게. 실패하면 이유를 남기고 규칙으로 돈다
if _STAGE2_MODE != "rules":
    _load_stage2()


# 진단 화면과 2단이 같은 스팬을 쓰도록, 서버가 이번 요청에서 탐지한 결과(spans_by_post)를 stage2 에 그대로 넘긴다.
# 예전에는 post_id 로만 묶은 전역 캐시를 썼다 — 동시 점검끼리 같은 post_id(upload_000 · 같은 계정)가 섞이고,
# 2단 전에 실패한 요청의 원문이 메모리에 남았다 (A3). 이제 요청 밖에 원문을 두지 않는다.


def _captions(post: dict) -> list[str]:
    """photo_captions(문자열 목록) 또는 SNS 내보내기 photos(``{"caption": …}`` 목록) → 캡션 문자열 목록."""
    raw = post.get("photo_captions")
    if raw is None:
        raw = post.get("photos") or []
    out = []
    for item in raw:
        caption = item.get("caption") if isinstance(item, dict) else item
        out.append(caption if isinstance(caption, str) else "")   # 빈 캡션도 자리를 지킨다 — photo_caption:N 번호 (server _detect_input 과 같게)
    return out


def _record(post: dict) -> dict:
    """1단 입력 채널 — post_id · title · body · photo_captions. 서버 _detect_input 결과든 export 글이든 같은 모양으로."""
    record = {key: post[key] for key in ("post_id", "title", "body") if post.get(key) is not None}
    if post.get("photo_captions") is not None or post.get("photos"):
        record["photo_captions"] = _captions(post)
    return record


def detect_spans(post: dict) -> dict:
    """B(c1) 자리. span.schema.json 준수 — infer.format_contract 가 스키마 검사까지 한다."""
    return _c1_rules.detect(_DETECTOR, _record(post), _attributes)  # 명시 규칙 병합 — 기준선 v2 의 일부라 기본 켬 (C1_RULES=0 이면 끔)


def _texts(record: dict) -> dict[str, str]:
    """탐지에 넣은 채널 그대로 → {text_id: 원문}. 탐지기와 같게 NFC 로 맞춘다 (스팬 offset 기준)."""
    texts = {"title": record.get("title"), "body": record.get("body")}
    texts.update({f"photo_caption:{i}": c for i, c in enumerate(record.get("photo_captions") or [])})
    return {k: unicodedata.normalize("NFC", v) for k, v in texts.items() if isinstance(v, str) and v}


def stage2(user_ref: str, posts: list[dict], risk_current: float = 0.0, risk_target: float = 40.0, *,
           spans_by_post: dict[str, dict] | None = None) -> dict:
    """D(c4) 자리. output 은 stage2-io Stage2Output 그대로 (findings · recommendation · provenance).

    - findings 는 2단 모델(GPU·어댑터가 없거나 출력이 깨지면 규칙 폴백 — provenance.model_version 에 이유)
    - recommendation 은 추천 엔진 v1. 현재 위험도는 C2 로 직접 계산하고, 목표는 서버가 넘긴 값이 아니라
      STAGE2_TARGET_RISK(기본 40 · 0~100 절대값)를 쓴다 — 서버의 목표는 아직 목 기여도에서 나온다
    - 스팬의 level·subject 는 규칙 판정기(_attributes · #306)로 붙는다
    - spans_by_post: 서버가 이번 요청에서 탐지한 결과 — 진단 화면 하이라이트와 2단 근거가 같은 스팬을 쓴다.
      없는 글만 여기서 다시 탐지한다 (채널은 서버 _detect_input 과 같다 — 제목 · 본문 · 캡션)
    """
    spans_by_post = spans_by_post or {}
    entries = []
    for post in posts:
        record = _record(post)
        result = spans_by_post.get(post["post_id"])
        if result is None:
            result = detect_spans(record)
        entries.append({
            "post_id": post["post_id"],
            "texts": _texts(record),
            "spans": result["spans"],
            "geo_tag": (post.get("activity_meta") or {}).get("geo_tag"),
        })
    output = _stage2_analyze(user_ref, entries, target_risk=_STAGE2_TARGET, mode=_STAGE2_MODE)
    # 화면은 output 만 읽는다. 계약 Stage2Input 전체(가명 텍스트 · pseudonym_map)는 W9 — 여기는 요약만
    summary = {
        "user_ref": user_ref,
        "post_ids": [e["post_id"] for e in entries],
        "risk": {"current": output["recommendation"]["projected"]["current_risk"], "target": _STAGE2_TARGET},
        "note": "요약 — 계약 Stage2Input 이 아니다 (전체 입력은 아직 만들지 않는다)",
    }
    return {"input": summary, "output": output}
