"""2단 실행 — 스팬 → 가명화 → Qwen3-4B + v1 어댑터 → 검증 → stage2-io Stage2Output.

    from kopl.c4_stage2.infer import analyze
    out = analyze(user_ref, posts, target_risk=40.0)            # 모델 (없으면 규칙 폴백)
    out = analyze(user_ref, posts, mode="rules")                 # 규칙만 (GPU 없는 PC · 시연 예행)

``posts`` 원소: ``{"post_id", "texts": {text_id: 원문}, "spans": [1단 스팬], "geo_tag": str | None}``

- 모델에는 원문이 가지 않는다. 학습과 같게 **가명 토큰으로 바꾼 스팬 목록**만 간다 (계약 설계 제약 5)
- findings 는 모델이, recommendation 은 추천 엔진 v1(규칙 · ``recommend.py``)이 낸다.
  v1 어댑터는 기여도 입력 없이 학습돼 recommendation 을 내지 않는다
- 모델 출력은 받은 뒤 다시 검증한다 — 7속성 · verdict enum · 입력에 없는 span_id 근거 제거 ·
  기권이면 근거 비우고 신뢰도 ≤ 0.25 (계약 Finding if/then). 파싱이 안 되면 규칙 판정으로 폴백하고
  provenance.model_version 에 그렇다고 적는다
- 어댑터는 저장소에 없다 (models/registry.md 포인터). 기본 위치는 exp08 results/adapter,
  다른 곳이면 ``STAGE2_ADAPTER_DIR``. 베이스 모델은 허브에 나가지 않고 로컬 캐시에서만 읽는다
"""

from __future__ import annotations

import json
import math
import os
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .anonymize import anonymize
from .recommend import recommend
from .rewrite import rewrites_for
from .rules import ATTRS, TYPE_TO_ATTR, findings_from_spans

SCHEMA_VERSION = "0.1.0"
BASE_MODEL = "Qwen/Qwen3-4B"
MODEL_VERSION = "qwen3-4b-qlora-v1"
RULES_VERSION = "rules-v1"
_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ADAPTER = _ROOT / "experiments" / "exp08-stage2-sft" / "results" / "adapter"
_VERDICTS = {"specified", "narrowed", "weak_signal", "abstain"}
_ABSTAIN_MAX_CONFIDENCE = 0.25

# v1 어댑터가 학습한 system 프롬프트 그대로 (exp08 data/v1_train.jsonl). make_sft_v1.SYSTEM 은
# 그 뒤에 바뀌었으므로(#279 판정 기준 등) 여기서 가져다 쓰지 않는다 — 어댑터를 다시 학습하면 같이 바꾼다
SYSTEM_V1 = """공개 게시글 스팬 목록만 보고 글쓴이 7속성(age·sex·location·occupation·family·commute·income)이 얼마나 특정되는지 판정한다.
verdict: specified(확정) · narrowed(범위 좁혀짐) · weak_signal(약한 신호) · abstain(근거 없음 — 추측 금지, 정상 동작).
규칙: evidence 는 근거 스팬의 post_id·span_id 만 (프로필 스팬은 post_id null). subject "other" 는 남의 정보라 근거 불가.
본인 얘기라도 예전 거주지·출신지·방문지·이사 갈 곳·예전 직장은 지금 것이 아니다 — 근거 불가.
cross_post 는 근거가 서로 다른 글 2편 이상일 때만 true. 실제 값(나이·지명)은 쓰지 않는다.
출력은 {"findings": {7속성 전부}, "rewrites": []} JSON 하나."""


# ── 입력 ────────────────────────────────────────────────────────────────

def pseudonymize_spans(post: Mapping[str, Any]) -> list[dict[str, Any]]:
    """한 글의 스팬을 채널별로 가명 토큰으로 바꾼다. 오프셋이 원문과 안 맞는 스팬은 뺀다 (학습과 같다)."""
    texts = post.get("texts") or {}
    by_channel: dict[str, list[dict[str, Any]]] = {}
    for s in post.get("spans") or []:
        text = texts.get(s.get("text_id"))
        if text is None or s.get("start") is None or s.get("end") is None:
            continue
        if text[s["start"]:s["end"]] != s.get("text"):
            continue
        by_channel.setdefault(s["text_id"], []).append(dict(s))
    out: list[dict[str, Any]] = []
    for text_id, spans in by_channel.items():
        try:
            _, key = anonymize(texts[text_id], spans)
        except Exception:  # noqa: BLE001 — 가명화 실패 채널은 통째로 뺀다 (원문이 새는 것보다 낫다)
            continue
        token_of = {orig: tok for tok, orig in key.items()}
        for s in spans:
            if s["text"] not in token_of:
                continue
            out.append({
                "span_id": s["span_id"],
                "text_id": text_id,
                "text": token_of[s["text"]],
                "type": s["type"],
                "level": s.get("level", "implicit"),
                "subject": s.get("subject", "self"),
            })
    return out


def build_user_prompt(user_ref: str, posts: Sequence[Mapping[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    entries = [{"post_id": p["post_id"], "spans": pseudonymize_spans(p)} for p in posts]
    payload = {"user_ref": user_ref, "profile": None, "posts": entries}
    return json.dumps(payload, ensure_ascii=False), entries


# ── 출력 검증 ───────────────────────────────────────────────────────────

def validate_findings(raw: Any, entries: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]] | None:
    """모델 findings 를 계약 모양으로 고친다. 구조가 깨졌으면 None (폴백).

    근거는 입력에 있는 스팬이면서 **그 속성의 유형이고 본인(self) 것**만 남긴다 —
    있는 span_id 라도 나이 스팬을 소득 근거로 대거나 남의 정보를 본인 근거로 대면 지운다.
    """
    if not isinstance(raw, Mapping) or set(raw) != set(ATTRS):
        return None
    spans = {(e["post_id"], s["span_id"]): s for e in entries for s in e["spans"]}
    out: dict[str, dict[str, Any]] = {}
    for attr in ATTRS:
        f = raw[attr]
        if not isinstance(f, Mapping) or not isinstance(f.get("verdict"), str) or f["verdict"] not in _VERDICTS:
            return None
        conf = f.get("confidence")
        if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not math.isfinite(conf):
            return None
        raw_evidence = f.get("evidence") or []
        if not isinstance(raw_evidence, list):
            return None
        evidence = []
        for e in raw_evidence:
            if not isinstance(e, Mapping):
                continue
            key = (e.get("post_id"), e.get("span_id"))
            if not all(isinstance(x, str) for x in key) or key not in spans:
                continue
            span = spans[key]
            if TYPE_TO_ATTR.get(str(span.get("type"))) == attr and span.get("subject") == "self"                     and {"post_id": key[0], "span_id": key[1]} not in evidence:
                evidence.append({"post_id": key[0], "span_id": key[1]})
        verdict = f["verdict"]
        if verdict != "abstain" and not evidence:
            verdict = "abstain"  # 근거가 다 지어낸 것이었으면 기권으로 — 근거 없는 판정은 내보내지 않는다
        conf = min(max(float(conf), 0.0), 1.0)
        if verdict == "abstain":
            evidence, conf = [], min(conf, _ABSTAIN_MAX_CONFIDENCE)
        out[attr] = {
            "verdict": verdict,
            "confidence": round(conf, 2),
            "cross_post": len({e["post_id"] for e in evidence}) >= 2,
            "evidence": evidence,
        }
    return out


# ── 모델 ────────────────────────────────────────────────────────────────

class Stage2Model:
    """Qwen3-4B 4bit + v1 어댑터. 서버가 켜질 때 한 번만 만든다 (로딩 수십 초)."""

    def __init__(self, adapter_dir: str | Path | None = None, max_new_tokens: int = 700) -> None:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        adapter = Path(adapter_dir or os.getenv("STAGE2_ADAPTER_DIR", _DEFAULT_ADAPTER))
        if not (adapter / "adapter_config.json").is_file():
            raise FileNotFoundError(f"2단 어댑터가 없다: {adapter} (STAGE2_ADAPTER_DIR 로 지정)")
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU 가 없다 — 2단 모델은 4bit GPU 추론만 지원한다 (mode='rules' 로 폴백)")
        self._torch = torch
        self.tok = AutoTokenizer.from_pretrained(BASE_MODEL, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            local_files_only=True,
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True),
            device_map={"": 0}, dtype=torch.bfloat16, attn_implementation="sdpa")
        self.model = PeftModel.from_pretrained(model, adapter)
        self.model.eval()
        self.max_new_tokens = max_new_tokens

    def generate(self, user_prompt: str) -> str:
        """exp08 eval.py · exp09 run_qwen.py 와 같은 디코딩 — greedy · thinking 끔."""
        msgs = [{"role": "system", "content": SYSTEM_V1}, {"role": "user", "content": user_prompt}]
        prompt = self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                              enable_thinking=False)
        ids = self.tok(prompt, return_tensors="pt").to(self.model.device)
        with self._torch.no_grad():
            out = self.model.generate(**ids, max_new_tokens=self.max_new_tokens, do_sample=False,
                                      temperature=None, top_p=None, top_k=None)
        return self.tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def parse_findings(text: str) -> Any:
    try:
        return json.loads(text[text.index("{"): text.rindex("}") + 1])["findings"]
    except Exception:  # noqa: BLE001
        return None


_MODEL: Stage2Model | None = None
_MODEL_ERROR: str | None = None
_MODEL_LOCK = threading.Lock()  # 동시 첫 요청이 모델을 두 번 올려 GPU 메모리가 터지지 않게


def _get_model() -> Stage2Model | None:
    """한 번만 로드를 시도한다. 실패 이유는 남겨 provenance 에 적는다.

    성공·실패 둘 다 캐시한다 — 어댑터를 새로 두었거나 경로를 바꿨으면 ``reset_model()`` 또는 서버 재시작.
    """
    global _MODEL, _MODEL_ERROR
    with _MODEL_LOCK:
        if _MODEL is None and _MODEL_ERROR is None:
            try:
                _MODEL = Stage2Model()
            except Exception as e:  # noqa: BLE001
                _MODEL_ERROR = f"{type(e).__name__}: {str(e)[:120]}"
        return _MODEL


def reset_model() -> None:
    """캐시한 모델·실패 이유를 버린다. 다음 호출이 다시 로드한다."""
    global _MODEL, _MODEL_ERROR
    with _MODEL_LOCK:
        _MODEL, _MODEL_ERROR = None, None


def _dict_version() -> str:
    from kopl.c2_specificity import engine

    return str(json.loads(Path(engine.DEFAULT_REGIONS_PATH).read_text(encoding="utf-8"))["dict_version"])


# ── 공개 API ────────────────────────────────────────────────────────────

def analyze(
    user_ref: str,
    posts: Sequence[Mapping[str, Any]],
    *,
    target_risk: float = 40.0,
    mode: str = "auto",
    model: Stage2Model | None = None,
) -> dict[str, Any]:
    """stage2-io ``Stage2Output`` 을 낸다.

    mode — ``auto``: 모델을 쓰고 안 되면 규칙 · ``model``: 모델만(안 되면 에러) · ``rules``: 규칙만.
    """
    if mode not in {"auto", "model", "rules"}:
        raise ValueError(f"mode: {mode!r}")
    user_prompt, entries = build_user_prompt(user_ref, posts)
    findings, version = None, RULES_VERSION
    if mode != "rules":
        m = model or _get_model()
        if m is None:
            if mode == "model":
                raise RuntimeError(f"2단 모델을 쓸 수 없다: {_MODEL_ERROR}")
            version = f"{RULES_VERSION} (fallback: {_MODEL_ERROR})"
        else:
            try:
                findings = validate_findings(parse_findings(m.generate(user_prompt)), entries)
                reason = "model output invalid"
            except Exception as e:  # noqa: BLE001 — 생성 중 GPU 오류 등. auto 면 규칙으로 넘어간다
                if mode == "model":
                    raise
                findings, reason = None, f"{type(e).__name__}: {str(e)[:120]}"
            if findings is None:
                if mode == "model":
                    raise RuntimeError("2단 모델 출력을 파싱하지 못했다")
                version = f"{RULES_VERSION} (fallback: {reason})"
            else:
                version = MODEL_VERSION
    if findings is None:
        findings = findings_from_spans(entries)
    rec_posts = [{"post_id": p["post_id"], "spans": list(p.get("spans") or []), "geo_tag": p.get("geo_tag")}
                 for p in posts]
    return {
        "schema_version": SCHEMA_VERSION,
        "findings": findings,
        "recommendation": recommend(user_ref=user_ref, posts=rec_posts, target_risk=target_risk),
        # 바꿔 쓰기 후보 — 추천 엔진 리라이트 조치와 같은 대상(본인 명시 단서). 확실한 후보만 (rewrite.py) · 원문은 담지 않는다
        "rewrites": rewrites_for([{"post_id": p["post_id"], "texts": p.get("texts") or {}, "spans": list(p.get("spans") or [])}
                                  for p in posts]),
        "provenance": {
            "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model_version": version,
            "dict_version": _dict_version(),
            "external_llm_used": False,
        },
    }
