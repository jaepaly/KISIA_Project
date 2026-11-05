"""2단 실행 — 스팬 → 가명화 → Qwen3-4B + v2 어댑터 → 검증 → stage2-io Stage2Output.

    from kopl.c4_stage2.infer import analyze
    out = analyze(user_ref, posts, target_risk=40.0)            # 모델 (없으면 규칙 폴백)
    out = analyze(user_ref, posts, mode="rules")                 # 규칙만 (GPU 없는 PC · 시연 예행)

``posts`` 원소: ``{"post_id", "texts": {text_id: 원문}, "spans": [1단 스팬], "geo_tag": str | None}``

- 모델에는 원문이 가지 않는다. 학습과 같게 **가명 토큰으로 바꾼 스팬 목록**만 간다 (계약 설계 제약 5)
- findings 는 모델이, recommendation 은 추천 엔진 v1(규칙 · ``recommend.py``)이 낸다.
  어댑터(v1 · v2)는 기여도 입력 없이 학습돼 recommendation 을 내지 않는다
- 모델 출력은 받은 뒤 다시 검증한다 — 7속성 · verdict enum · 입력에 없는 span_id 근거 제거 ·
  기권이면 근거 비우고 신뢰도 ≤ 0.25 (계약 Finding if/then). 파싱이 안 되면 규칙 판정으로 폴백하고
  provenance.model_version 에 그렇다고 적는다
- 어댑터는 저장소에 없다 (models/registry.md 포인터). 기본 위치는 exp08 results/adapter_v2,
  다른 곳이면 ``STAGE2_ADAPTER_DIR``. 베이스 모델은 허브에 나가지 않고 로컬 캐시에서만 읽는다
- 엔진은 ``STAGE2_ENGINE`` 으로 고른다 — ``bnb`` 는 위 NF4 + 어댑터(``Stage2Model``).
  ``gguf`` 면 같은 함수(NF4 를 푼 베이스 + v2 LoRA)를 베이스 Q8_0 GGUF + LoRA f32 GGUF 두 파일(merge 안 함)로 바꿔
  로컬 llama-server ``-m 베이스 --lora 어댑터`` 로 돌린다 (``Stage2GGUF`` · ``STAGE2_GGUF`` · ``STAGE2_GGUF_LORA`` ·
  ``LLAMA_SERVER`` · models/registry.md). 비워 두면 ``STAGE2_GGUF`` 와 ``STAGE2_GGUF_LORA`` 를 둘 다 준 PC 만 gguf,
  아니면 bnb (DEC-017 · ``_engine_name``)
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .anonymize import anonymize
from .recommend import recommend
from .rewrite import rewrites_for
from .rules import ATTRS, TYPE_TO_ATTR, findings_from_spans

_LOG = logging.getLogger(__name__)

SCHEMA_VERSION = "0.1.0"
# 오프라인 GPU 서버(HF_HUB_OFFLINE=1)는 허브 이름 대신 받아 둔 스냅샷 폴더를 가리킨다 — 비우면 허브 이름 (서버 전용 커밋 258f904 를 main 으로)
BASE_MODEL = os.getenv("STAGE2_BASE_MODEL_DIR") or "Qwen/Qwen3-4B"
MODEL_VERSION = "qwen3-4b-qlora-v2"
# GGUF 경로(STAGE2_ENGINE=gguf) — 같은 v2 판정을 llama.cpp 로 낸 것. 화면 · 러너가 어느 엔진이었는지 구분하게 버전을 따로 적는다.
# 11/4 Q5_K_M merge 판(qwen3-4b-qlora-v2-gguf-q5km)은 115계정 797/805 로 기각 → 베이스 Q8_0 + LoRA 분리 판 (DEC-017 · exp45 결과 4)
MODEL_VERSION_GGUF = "qwen3-4b-qlora-v2-gguf-q8-lora"
MODEL_VERSIONS = (MODEL_VERSION, MODEL_VERSION_GGUF)   # 「모델이 판정했다」로 볼 버전 (규칙 폴백이 아닌 것)
RULES_VERSION = "rules-v1"
_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ADAPTER = _ROOT / "experiments" / "exp08-stage2-sft" / "results" / "adapter_v2"
# v1 어댑터 가중치 해시 (DEC-009 · 되돌리기용 보존). v2 프롬프트 · 상한으로 v1 가중치를 돌리면 판정하지 않은 구성이라 막는다 —
# 예전 STAGE2_ADAPTER_DIR 이 v1 을 가리킨 채 남은 PC 에서 조용히 섞이지 않게 (되돌리기는 models/registry.md)
V1_ADAPTER_SHA256 = "1053e7adcc77d1863e0789978b468d29d92930dc9c26a84a0a29e7fbc99a6a4b"
# GGUF — 두 파일이다. merge 하지 않는다: merge 뒤 재양자화하면 어댑터 몫(‖W‖의 약 0.8%)이 깎인다(Q5_K_M 잔존 약 81% · exp45 결과 4).
#   베이스: NF4(double quant) 를 bf16 으로 푼 Qwen3-4B(어댑터 없음) → llama.cpp b12090 convert(bf16) → Q8_0
#   어댑터: v2 LoRA(c045d353…) → convert_lora_to_gguf.py --outtype f32 · llama-server --lora (배율 1)
# 재현은 experiments/exp45-stage2-gguf · 기록은 models/registry.md. 둘 중 하나라도 다른 파일이면 기동하지 않는다 (판정하지 않은 가중치)
GGUF_SHA256 = "f4982df0149f89e7300314d0f1a5d20dc34b6b5d7d0c6e03a754c30431a575b0"        # 베이스 Q8_0 (STAGE2_GGUF)
GGUF_LORA_SHA256 = "ae0104d45f7359af3484ff0585840ffd1432951519ff2f0fc19de8b2d07eb74d"   # v2 LoRA f32 (STAGE2_GGUF_LORA)
GGUF_PORT = 8092          # 127.0.0.1 에만 연다. 바꾸려면 STAGE2_GGUF_PORT
GGUF_CTX = 4096           # 입력(상한 16/4 · 약 1천 토큰) + 출력 상한(최대 2048)이 들어가는 크기
# llama-server 요청 하나의 기한(초) — 출력 상한 2048 토큰도 RTX 3060(약 59 tok/s)에서 약 35초. 넘기면 서버를 내리고
# 다음 호출에 다시 띄운다(멈춘 생성이 GPU 자리를 붙잡지 않게 · Codex P1). 바꾸려면 STAGE2_GGUF_TIMEOUT
GGUF_TIMEOUT = 120.0
_VERDICTS = {"specified", "narrowed", "weak_signal", "abstain"}
# 모델 입력 상한 — v1 어댑터 학습 데이터는 입력당 스팬 중앙 4 · 최대 23, 한 유형 p90 5 였다 (exp08 train 342건).
# 실제 계정은 수십~수백 개라 출력(근거 목록)이 700토큰을 넘겨 JSON 이 잘리고 규칙 폴백으로 떨어졌다 (실제 글 내부 시험 10/8 ·
# 합성 재현: 스팬 39개 → 출력 700/700 잘림). 학습 범위 안으로 줄여 보낸다 — 규칙 판정·추천·k 는 전체 스팬을 그대로 쓴다.
# v2 어댑터(DEC-012)는 실제 크기 계정을 이 상한 16/4 로 줄이고 스팬 없는 글을 뺀 입력으로 학습했다 (exp08 make_sft_v2 · 2048 토큰 안).
# v1 은 24/6 · 빈 글 포함이었다 — 되돌릴 때 함께 되돌린다 (models/registry.md)
MODEL_MAX_SPANS = 16
MODEL_MAX_SPANS_PER_TYPE = 4
_LEVEL_RANK = {"explicit": 0, "implicit": 1, "inferential": 2}
_ABSTAIN_MAX_CONFIDENCE = 0.25

# v1 어댑터가 학습한 system 프롬프트 그대로 (exp08 data/v1_train.jsonl). make_sft_v1.SYSTEM 은
# 그 뒤에 바뀌었으므로(#279 판정 기준 등) 여기서 가져다 쓰지 않는다. 앱은 v2 를 쓴다 — v1 은 실험 재현(exp09 · exp22b)과 되돌리기용
SYSTEM_V1 = """공개 게시글 스팬 목록만 보고 글쓴이 7속성(age·sex·location·occupation·family·commute·income)이 얼마나 특정되는지 판정한다.
verdict: specified(확정) · narrowed(범위 좁혀짐) · weak_signal(약한 신호) · abstain(근거 없음 — 추측 금지, 정상 동작).
규칙: evidence 는 근거 스팬의 post_id·span_id 만 (프로필 스팬은 post_id null). subject "other" 는 남의 정보라 근거 불가.
본인 얘기라도 예전 거주지·출신지·방문지·이사 갈 곳·예전 직장은 지금 것이 아니다 — 근거 불가.
cross_post 는 근거가 서로 다른 글 2편 이상일 때만 true. 실제 값(나이·지명)은 쓰지 않는다.
출력은 {"findings": {7속성 전부}, "rewrites": []} JSON 하나."""

# v2 어댑터가 학습한 system 프롬프트 그대로 (exp08 make_sft_v2.SYSTEM_V2 = v1 + #296 판정 기준 한 줄). test_infer 가 같은지 확인한다
SYSTEM_V2 = """공개 게시글 스팬 목록만 보고 글쓴이 7속성(age·sex·location·occupation·family·commute·income)이 얼마나 특정되는지 판정한다.
verdict: specified(확정) · narrowed(범위 좁혀짐) · weak_signal(약한 신호) · abstain(근거 없음 — 추측 금지, 정상 동작).
판정 기준(속성마다 그 속성 유형의 본인 스팬만): explicit 이 하나라도 있으면 specified · 아니면 implicit 이 하나라도 있으면 narrowed · 아니면 inferential 만 있는데 서로 다른 글 2편 이상이면 narrowed · inferential 이 글 1편뿐이면 weak_signal · 단서가 없으면 abstain.
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


def select_for_model(entries: Sequence[Mapping[str, Any]], *, max_spans: int = MODEL_MAX_SPANS,
                     max_per_type: int = MODEL_MAX_SPANS_PER_TYPE) -> list[dict[str, Any]]:
    """모델에 보낼 스팬을 학습 범위 안으로 고른다. 글 순서·글 안 순서는 원래대로 둔다.

    - 같은 글 · 같은 채널에서 같은 유형 · 같은 표현이 되풀이되면(「엄마」 ×6) 가장 순위 높은 하나만.
      가명 토큰은 채널마다 번호가 새로 붙으므로 채널(text_id)까지 키에 넣는다 (Codex 10/8)
    - 우선순위: 본인(self) > 등급 explicit > implicit > inferential
    - 같은 순위 안에서만 글을 돌아가며 고른다 — 여러 글에 걸친 근거(cross_post)는 살리되, 글을 퍼뜨리려고
      순위 낮은 단서(타인 등)가 본인 단서를 밀어내지 않게 (Codex 10/8)
    """
    best: dict[tuple[str, str, str, str], tuple[int, int, int, str, dict[str, Any]]] = {}
    for pi, e in enumerate(entries):
        for si, sp in enumerate(e["spans"]):
            key = (e["post_id"], str(sp.get("text_id")), str(sp.get("type")), str(sp.get("text")))
            rank = (0 if sp.get("subject", "self") == "self" else 1) * 10 + _LEVEL_RANK.get(str(sp.get("level")), 3)
            cand = (rank, pi, si, e["post_id"], sp)
            if key not in best or cand[:3] < best[key][:3]:
                best[key] = cand
    pool: dict[str, list[tuple[int, int, int, str, dict[str, Any]]]] = {}
    for cand in best.values():
        pool.setdefault(str(cand[4].get("type")), []).append(cand)

    picked_by_type: dict[str, list[tuple[int, int, int, str, dict[str, Any]]]] = {}
    for stype, cands in pool.items():
        cands.sort(key=lambda c: c[:3])
        chosen: list[tuple[int, int, int, str, dict[str, Any]]] = []
        used_posts: set[str] = set()
        for rank in sorted({c[0] for c in cands}):
            tier = [c for c in cands if c[0] == rank]
            for c in tier:  # 이 순위 안에서 아직 안 나온 글 먼저
                if len(chosen) < max_per_type and c[3] not in used_posts:
                    chosen.append(c)
                    used_posts.add(c[3])
            for c in tier:  # 그다음 같은 순위의 나머지
                if len(chosen) < max_per_type and c not in chosen:
                    chosen.append(c)
        picked_by_type[stype] = chosen

    # 전체 상한 — 유형을 돌아가며 한 개씩 (한 유형이 자리를 독차지하지 않게). 순서는 유형별 최상위 후보 순
    final: list[tuple[int, int, int, str, dict[str, Any]]] = []
    depth = 0
    order = sorted(picked_by_type, key=lambda t: picked_by_type[t][0][:3])
    while len(final) < max_spans and any(depth < len(picked_by_type[t]) for t in order):
        for stype in order:
            if depth < len(picked_by_type[stype]) and len(final) < max_spans:
                final.append(picked_by_type[stype][depth])
        depth += 1
    keep = {(c[1], c[2]) for c in final}
    return [{"post_id": e["post_id"], "spans": [sp for si, sp in enumerate(e["spans"]) if (pi, si) in keep]}
            for pi, e in enumerate(entries)]


def build_user_prompt(user_ref: str, posts: Sequence[Mapping[str, Any]], *,
                      cap: bool = False) -> tuple[str, list[dict[str, Any]]]:
    """모델 입력. ``cap=True`` 면 v2 학습과 같게 줄인다(앱 경로) — 상한 16/4 · 스팬 없는 글 뺌.
    실험 재현(exp13 등)은 기본값 그대로 전체."""
    entries = [{"post_id": p["post_id"], "spans": pseudonymize_spans(p)} for p in posts]
    if cap:
        entries = [e for e in select_for_model(entries) if e["spans"]]
    payload = {"user_ref": user_ref, "profile": None, "posts": entries}
    return json.dumps(payload, ensure_ascii=False), entries


def output_budget(entries: Sequence[Mapping[str, Any]]) -> int:
    """출력 토큰 상한 — 모델에 보내는 스팬이 모두 근거로 돌아와도 잘리지 않게.

    Qwen3 토크나이저 실측(10/12): 근거 0개 답변 235 토큰 · 근거 하나 `{"post_id": …, "span_id": …}` 는
    글 ID 길이에 따라 27(`S01_b07`) ~ 43(`u_3f2a91c4_p001`) 토큰 — 「10 + 글 ID 글자 수 + 스팬 ID 글자 수」가
    네 가지 ID 형식에서 모두 실측보다 조금 크다. 예전 「근거당 17토큰」은 작아서 글 많은 계정의 답변이
    중간에 잘려 규칙으로 떨어졌다(exp22 · v1 · v2 모두 30계정 중 23개). 모델은 답을 다 쓰면 멈추므로
    상한을 높여도 짧은 답은 그대로이고, 예전에 잘리던 긴 답만 끝까지 쓴다(그만큼 시간 · KV 캐시가 는다).
    700 아래로는 내리지 않고 2048 에서 막는다 — ID 가 아주 길거나 모델이 근거를 지어내 늘리면 여전히
    잘릴 수 있고, 그때는 지금처럼 규칙으로 떨어진다 (analyze 의 「model output truncated」).
    """
    per = sum(10 + len(str(e.get("post_id", ""))) + len(str(s.get("span_id", "")))
              for e in entries for s in e.get("spans") or [])
    return min(max(700, int(300 + 1.1 * per)), 2048)


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
    """Qwen3-4B 4bit + v2 어댑터. 서버가 켜질 때 한 번만 만든다 (로딩 수십 초)."""

    model_version = MODEL_VERSION

    def __init__(self, adapter_dir: str | Path | None = None, max_new_tokens: int = 700,
                 system: str | None = None) -> None:
        """system — 어댑터가 학습한 프롬프트. 기본 SYSTEM_V2 · v1 어댑터를 재현할 때만 SYSTEM_V1 을 넘긴다."""
        adapter = Path(adapter_dir or os.getenv("STAGE2_ADAPTER_DIR", _DEFAULT_ADAPTER))
        if not (adapter / "adapter_config.json").is_file():
            raise FileNotFoundError(f"2단 어댑터가 없다: {adapter} (STAGE2_ADAPTER_DIR 로 지정)")
        if (system or SYSTEM_V2) == SYSTEM_V2 and _sha256(adapter / "adapter_model.safetensors") == V1_ADAPTER_SHA256:
            raise RuntimeError(f"v1 어댑터를 v2 구성으로 돌리려 했다: {adapter} — STAGE2_ADAPTER_DIR 을 v2 로 바꾸거나 지운다")
        import torch  # 경로 · 해시 확인은 torch 없이 (GPU 없는 PC 에서도 이유가 정확히 남게)
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

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
        self.system = system or SYSTEM_V2

    def generate(self, user_prompt: str, max_new_tokens: int | None = None) -> str:
        """exp08 eval.py · exp09 run_qwen.py 와 같은 디코딩 — greedy · thinking 끔."""
        msgs = [{"role": "system", "content": self.system}, {"role": "user", "content": user_prompt}]
        prompt = self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                              enable_thinking=False)
        ids = self.tok(prompt, return_tensors="pt").to(self.model.device)
        with self._torch.no_grad():
            out = self.model.generate(**ids, max_new_tokens=max_new_tokens or self.max_new_tokens, do_sample=False,
                                      temperature=None, top_p=None, top_k=None)
        return self.tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def chat_prompt(system: str, user_prompt: str) -> str:
    """Qwen3 chat 템플릿을 ``apply_chat_template(add_generation_prompt=True, enable_thinking=False)`` 와 같은 글자로.

    GGUF 경로는 토크나이저(transformers)를 올리지 않고 이 문자열을 llama-server 에 그대로 넣는다 — HF 경로와
    입력 토큰 수가 같은 것을 확인했다(exp45). test_infer 가 토크나이저가 있는 PC 에서 글자까지 같은지 본다.
    """
    return (f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user_prompt}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n")


class Stage2GGUF:
    """v2 GGUF(베이스 Q8_0 + LoRA f32)를 로컬 llama-server 로 돌린다 — ``Stage2Model`` 과 같은 ``generate(user_prompt, max_new_tokens)``.

    - 서버가 켜질 때 한 번 llama-server 를 띄우고(모델 적재 수 초) 127.0.0.1:포트 로만 부른다. 외부로 나가는 요청은 없다 —
      llama-server 는 ``--host 127.0.0.1`` · 웹 화면 끔이고, 호출은 프록시 설정을 무시하는 opener 로 한다
    - 포트에 이미 무언가 떠 있으면 기동하지 않는다 — 모르는 서버에 판정을 맡기지 않는다
    - 두 파일 모두 기동 때 SHA-256 을 확인한다(베이스 ``GGUF_SHA256`` · LoRA ``GGUF_LORA_SHA256``) · 하나라도 다르면 거부
    - 정리: ``close()`` · 인터프리터 종료(atexit) · Windows 는 Job 개체(KILL_ON_JOB_CLOSE)라 분석기가 강제 종료돼도 같이 꺼진다.
      ``close()`` 는 여러 번 불러도 되고, atexit 등록 · Job 핸들까지 놓는다
    - 요청 하나가 ``timeout``(기본 ``GGUF_TIMEOUT`` · ``STAGE2_GGUF_TIMEOUT``)을 넘기면 서버를 내리고 예외 — auto 는 규칙 결과를
      그대로 둔다. 서버가 (닫지 않았는데) 꺼져 있으면 다음 호출이 다시 띄운다
    - 디코딩은 HF 경로와 같다 — greedy(temperature 0 · top_k 1) · thinking 끔 · 출력 상한 ``max_new_tokens``
    """

    model_version = MODEL_VERSION_GGUF

    def __init__(self, gguf: str | Path | None = None, server: str | Path | None = None, *, lora: str | Path | None = None,
                 port: int | None = None, max_new_tokens: int = 700, system: str | None = None,
                 sha256: str = GGUF_SHA256, lora_sha256: str = GGUF_LORA_SHA256,
                 ctx: int = GGUF_CTX, gpu_layers: int = 99, start_timeout: float = 300.0,
                 command: Sequence[str] | None = None, timeout: float | None = None) -> None:
        """command — 테스트용 실행 명령 앞부분(가짜 서버). 주면 ``server`` 대신 그것을 띄운다."""
        self._proc: subprocess.Popen | None = None
        self._job: Any = None
        self._closed = False
        gguf_name = str(gguf or os.getenv("STAGE2_GGUF") or "")
        if not gguf_name or not Path(gguf_name).is_file():
            raise FileNotFoundError(f"2단 GGUF 가 없다: {gguf_name} (STAGE2_GGUF 로 지정)")
        gguf_path = Path(gguf_name)
        lora_name = str(lora or os.getenv("STAGE2_GGUF_LORA") or "")
        if not lora_name or not Path(lora_name).is_file():
            raise FileNotFoundError(f"2단 LoRA GGUF 가 없다: {lora_name} (STAGE2_GGUF_LORA 로 지정)")
        lora_path = Path(lora_name)
        exe = [str(x) for x in command] if command else [str(server or os.getenv("LLAMA_SERVER") or "")]
        if not command and (not exe[0] or not Path(exe[0]).is_file()):
            raise FileNotFoundError(f"llama-server 가 없다: {exe[0]} (LLAMA_SERVER 로 지정)")
        if _sha256(gguf_path) != sha256:
            raise RuntimeError(f"GGUF 해시가 다르다: {gguf_path} — 판정한 파일(models/registry.md)만 쓴다")
        if _sha256(lora_path) != lora_sha256:
            raise RuntimeError(f"LoRA GGUF 해시가 다르다: {lora_path} — 판정한 파일(models/registry.md)만 쓴다")
        self.port = int(port or os.getenv("STAGE2_GGUF_PORT") or GGUF_PORT)
        if _port_open(self.port):
            raise RuntimeError(f"llama-server 포트가 이미 쓰이고 있다: 127.0.0.1:{self.port} (STAGE2_GGUF_PORT 로 바꾼다)")
        self.max_new_tokens = max_new_tokens
        self.system = system or SYSTEM_V2
        self._base = f"http://127.0.0.1:{self.port}"
        self._http = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 프록시 설정을 타지 않는다
        self._lock = threading.Lock()   # 슬롯 하나(-np 1) — 동시에 부르면 하나씩
        self.timeout = float(timeout or os.getenv("STAGE2_GGUF_TIMEOUT") or GGUF_TIMEOUT)
        self._start_timeout = start_timeout
        self._args = [*exe, "-m", str(gguf_path), "--lora", str(lora_path), "-c", str(ctx), "-np", "1", "-ngl", str(gpu_layers),
                      "--host", "127.0.0.1", "--port", str(self.port), "--no-webui"]
        import atexit
        atexit.register(self.close)
        try:
            self._start()
        except BaseException:
            self.close()
            raise

    def _start(self) -> None:
        self._proc = subprocess.Popen(self._args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._job = _kill_with_parent(self._proc)
        deadline = time.monotonic() + self._start_timeout
        while not self._healthy():
            if self._proc.poll() is not None or time.monotonic() > deadline:
                code = self._proc.poll()
                self._stop_server()
                raise RuntimeError(f"llama-server 기동 실패 (종료 코드 {code})")
            time.sleep(0.5)

    def _healthy(self) -> bool:
        try:
            with self._http.open(f"{self._base}/health", timeout=2) as r:
                return json.loads(r.read()).get("status") == "ok"
        except (OSError, ValueError):
            return False

    def generate(self, user_prompt: str, max_new_tokens: int | None = None) -> str:
        body = {"prompt": chat_prompt(self.system, user_prompt), "n_predict": int(max_new_tokens or self.max_new_tokens),
                "temperature": 0, "top_k": 1, "seed": 0, "cache_prompt": False}
        req = urllib.request.Request(f"{self._base}/completion", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with self._lock:
            if self._closed:
                code = self._proc.returncode if self._proc is not None else None
                raise RuntimeError(f"llama-server 가 꺼져 있다 (종료 코드 {code})")
            if self._proc is None or self._proc.poll() is not None:
                # 닫지 않았는데 꺼져 있다 — 앞 요청이 기한을 넘겨 내렸거나 서버가 죽었다. 다시 띄운다(포트를 남이 잡았으면 거부)
                self._stop_server()
                for _ in range(20):   # 방금 내린 서버의 포트가 풀리기를 잠깐 기다린다
                    if not _port_open(self.port):
                        break
                    time.sleep(0.25)
                if _port_open(self.port):
                    raise RuntimeError(f"llama-server 포트가 이미 쓰이고 있다: 127.0.0.1:{self.port} (STAGE2_GGUF_PORT 로 바꾼다)")
                _LOG.warning("llama-server 를 다시 띄운다 (127.0.0.1:%s)", self.port)
                self._start()
            try:
                with self._http.open(req, timeout=self.timeout) as r:
                    res = json.loads(r.read())
            except (TimeoutError, socket.timeout) as e:
                self._stop_server()   # 멈춘 생성을 끊는다 — 다음 호출이 다시 띄운다
                raise TimeoutError(f"llama-server 응답 기한 초과 ({self.timeout:.0f}초)") from e
            except urllib.error.URLError as e:
                if isinstance(e.reason, (TimeoutError, socket.timeout)):
                    self._stop_server()
                    raise TimeoutError(f"llama-server 응답 기한 초과 ({self.timeout:.0f}초)") from e
                raise
        return str(res.get("content", "")).strip()

    def _stop_server(self) -> None:
        """llama-server 를 끄고 Job 핸들을 닫는다. 여러 번 불러도 된다"""
        proc, job = self._proc, self._job
        self._job = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(10)
        _close_handle(job)

    def close(self) -> None:
        """서버를 끄고 정리한다 — atexit 등록 · Job 핸들까지. 여러 번 불러도 된다. 닫은 뒤 generate 는 다시 띄우지 않는다"""
        self._closed = True
        self._stop_server()
        try:
            import atexit
            atexit.unregister(self.close)
        except Exception:  # noqa: BLE001 — 인터프리터 종료 중
            pass


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _kill_with_parent(proc: subprocess.Popen) -> Any:
    """Windows — 자식을 KILL_ON_JOB_CLOSE Job 에 넣는다. 분석기 프로세스가 어떻게 끝나든(작업 관리자 강제 종료 포함)
    핸들이 닫히면 llama-server 도 꺼져 GPU 메모리를 잡고 남지 않는다. 다른 OS 는 atexit · close() 로만 정리한다."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("Read", "Write", "Other", "ReadT", "WriteT", "OtherT")]

        class _Ext(ctypes.Structure):
            _fields_ = [("Basic", _Basic), ("Io", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        info = _Ext()
        info.Basic.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = bool(job) and bool(k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)))
        ok = ok and bool(k32.AssignProcessToJobObject(job, int(proc._handle)))  # type: ignore[attr-defined]
        if not ok:
            _LOG.warning("llama-server 를 Job 에 넣지 못했다 — 분석기가 강제 종료되면 직접 꺼야 한다")
        return job   # 핸들을 들고 있어야 한다 (닫히면 자식이 꺼진다)
    except Exception as e:  # noqa: BLE001
        _LOG.warning("llama-server Job 설정 실패: %s", e)
        return None


def _close_handle(handle: Any) -> None:
    """_kill_with_parent 가 돌려준 Job 핸들을 닫는다(Windows). 자식은 이미 꺼진 뒤에 부른다 — 닫히면 자식도 꺼진다"""
    if not handle or os.name != "nt":
        return
    try:
        import ctypes

        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(ctypes.c_void_p(handle))
    except Exception as e:  # noqa: BLE001
        _LOG.warning("Job 핸들 닫기 실패: %s", e)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_findings(text: str) -> Any:
    try:
        return json.loads(text[text.index("{"): text.rindex("}") + 1])["findings"]
    except Exception:  # noqa: BLE001
        return None


def _public_reason(e: BaseException) -> str:
    """응답 provenance 에 싣는 실패 이유 — 고정 문구만. 원문(PC 경로 등)은 서버 로그에만 남긴다 (#347 리뷰).

    /scan 응답 JSON 은 화면 밖으로도 나가므로, 예외 문장을 그대로 실으면 어댑터 절대 경로가 샌다.
    """
    msg = str(e)
    if isinstance(e, FileNotFoundError):
        if msg.startswith("2단 GGUF 가 없다"):
            return "2단 GGUF 없음"
        if msg.startswith("2단 LoRA GGUF 가 없다"):
            return "2단 LoRA GGUF 없음"
        if msg.startswith("llama-server 가 없다"):
            return "llama-server 없음"
        return "2단 어댑터 없음"
    if msg.startswith("GGUF 해시가 다르다"):
        return "GGUF 해시 불일치"
    if msg.startswith("LoRA GGUF 해시가 다르다"):
        return "LoRA GGUF 해시 불일치"
    if msg.startswith("llama-server 포트가 이미"):
        return "llama-server 포트 사용 중"
    if msg.startswith("llama-server 기동 실패"):
        return "llama-server 기동 실패"
    if msg.startswith("llama-server 가 꺼져"):
        return "llama-server 꺼짐"
    if msg.startswith("llama-server 응답 기한 초과"):
        return "llama-server 응답 기한 초과"
    if isinstance(e, (urllib.error.URLError, ConnectionError, TimeoutError)):
        return "llama-server 응답 없음"
    if msg.startswith("2단 엔진을 모른다"):
        return "2단 엔진 설정 오류"
    if isinstance(e, ImportError):
        return "추론 라이브러리 없음"
    if msg.startswith("v1 어댑터를 v2 구성으로"):
        return "v1 어댑터 거부 (v2 구성)"
    if msg.startswith("CUDA GPU 가 없다"):
        return "CUDA GPU 없음"
    if "out of memory" in msg:
        return "GPU 메모리 부족"
    return type(e).__name__


_MODEL: Stage2Model | Stage2GGUF | None = None
_MODEL_ERROR: str | None = None
_MODEL_LOCK = threading.Lock()  # 동시 첫 요청이 모델을 두 번 올려 GPU 메모리가 터지지 않게


def _engine_name() -> str:
    """STAGE2_ENGINE 이 있으면 그것(bnb · gguf). 비어 있으면 STAGE2_GGUF(베이스) 와 STAGE2_GGUF_LORA(어댑터)를 둘 다 준
    PC 만 gguf, 아니면 bnb (DEC-017). 하나만 준 PC 는 bnb 로 두고 로그에 경고한다 — 예전 Q5 merge 판 설정(STAGE2_GGUF 하나)이
    남은 PC 가 해시 불일치로 규칙 폴백하지 않게. 그 PC 에서 GGUF 를 쓰려면 두 변수를 다 준다(또는 STAGE2_ENGINE=gguf 로 사유 확인).

    GGUF 는 저장소에 없다 — 코드 기본을 gguf 로 두면 GGUF 를 받지 않은 PC 가 모두 규칙 폴백이 된다. 그래서
    「GGUF 를 둔 PC 에서는 GGUF 가 기본」으로만 올린다. 두 변수를 다 줬는데 해시 · llama-server 가 안 맞으면 NF4 로 조용히 바꾸지 않고
    규칙 폴백 + 사유(「GGUF 해시 불일치」 등)로 드러낸다 — GGUF 를 쓰려던 PC 가 1분 걸리는 NF4 로 도는 것을 놓치지 않게.
    되돌리기: STAGE2_ENGINE=bnb (또는 STAGE2_GGUF 를 지운다)
    """
    engine = (os.getenv("STAGE2_ENGINE") or "").strip().lower()
    if engine:
        return engine
    base = bool((os.getenv("STAGE2_GGUF") or "").strip())
    lora = bool((os.getenv("STAGE2_GGUF_LORA") or "").strip())
    if base != lora:
        _LOG.warning("STAGE2_GGUF · STAGE2_GGUF_LORA 중 하나만 있다 — 2단은 NF4(bnb)로 돈다 (GGUF 는 두 파일이 다 있어야 한다)")
    return "gguf" if base and lora else "bnb"


def _new_model() -> Stage2Model | Stage2GGUF:
    """STAGE2_ENGINE — bnb: NF4 + 어댑터 · gguf: llama-server (STAGE2_GGUF · STAGE2_GGUF_LORA · LLAMA_SERVER) · 비우면 ``_engine_name``."""
    engine = _engine_name()
    if engine == "bnb":
        return Stage2Model()
    if engine == "gguf":
        return Stage2GGUF()
    raise ValueError(f"2단 엔진을 모른다: {engine!r} (bnb · gguf)")


def _get_model() -> Stage2Model | Stage2GGUF | None:
    """한 번만 로드를 시도한다. 실패 이유는 남겨 provenance 에 적는다.

    성공·실패 둘 다 캐시한다 — 어댑터를 새로 두었거나 경로를 바꿨으면 ``reset_model()`` 또는 서버 재시작.
    """
    global _MODEL, _MODEL_ERROR
    with _MODEL_LOCK:
        if _MODEL is None and _MODEL_ERROR is None:
            try:
                _MODEL = _new_model()
            except Exception as e:  # noqa: BLE001
                _LOG.warning("2단 모델 로드 실패 — 규칙으로 폴백: %s: %s", type(e).__name__, e)
                _MODEL_ERROR = _public_reason(e)
        return _MODEL


def reset_model() -> None:
    """캐시한 모델·실패 이유를 버린다. 다음 호출이 다시 로드한다."""
    global _MODEL, _MODEL_ERROR
    with _MODEL_LOCK:
        if isinstance(_MODEL, Stage2GGUF):
            _MODEL.close()   # 띄운 llama-server 도 끈다
        _MODEL, _MODEL_ERROR = None, None


def _dict_version() -> str:
    from kopl.c2_specificity import engine

    return str(json.loads(Path(engine.DEFAULT_REGIONS_PATH).read_text(encoding="utf-8"))["dict_version"])


# ── 공개 API ────────────────────────────────────────────────────────────

def _app_conditions(spans: Sequence[Mapping[str, Any]], post_id: str) -> list[dict[str, Any]]:
    """추천 엔진의 조건 생성을 분석 앱(c23)과 같게 — 약칭·동 겹침 · 사전 밖 지명 · 장소 관계 불명 신뢰도 (#299 후속).

    기본값(build_conditions)은 exp10 재현용으로 recommend() 에 그대로 남는다. 앱 경로만 이 함수를 넘긴다 —
    화면의 위험도와 추천 조치가 본 「현재 위험」이 같은 숫자가 되게.
    """
    from kopl.c2_specificity.k_engine import conditions_from_posts

    return conditions_from_posts([{"post_id": post_id, "spans": list(spans)}])


def _app_geo_condition(tag: str, post_id: str) -> dict[str, Any] | None:
    """위치태그 → 조건. 앱(conditions_from_posts 의 geo_tag)과 같은 함수."""
    from kopl.c2_specificity.k_engine import geo_tag_condition

    return geo_tag_condition(str(tag), post_id)


def analyze(
    user_ref: str,
    posts: Sequence[Mapping[str, Any]],
    *,
    target_risk: float = 40.0,
    mode: str = "auto",
    model: Stage2Model | Stage2GGUF | None = None,
) -> dict[str, Any]:
    """stage2-io ``Stage2Output`` 을 낸다.

    mode — ``auto``: 모델을 쓰고 안 되면 규칙 · ``model``: 모델만(안 되면 에러) · ``rules``: 규칙만.
    """
    if mode not in {"auto", "model", "rules"}:
        raise ValueError(f"mode: {mode!r}")
    _, all_entries = build_user_prompt(user_ref, posts)
    user_prompt, entries = build_user_prompt(user_ref, posts, cap=True)
    findings, version = None, RULES_VERSION
    if mode != "rules":
        m = model or _get_model()
        if m is None:
            if mode == "model":
                raise RuntimeError(f"2단 모델을 쓸 수 없다: {_MODEL_ERROR}")
            version = f"{RULES_VERSION} (fallback: {_MODEL_ERROR})"
        else:
            try:
                raw = (m.generate(user_prompt, max_new_tokens=output_budget(entries))
                       if isinstance(m, (Stage2Model, Stage2GGUF)) else m.generate(user_prompt))
                findings = validate_findings(parse_findings(raw), entries)
                # 닫는 괄호 없이 끝났으면 출력 상한에 잘린 것 — 「invalid」와 구분해 남긴다
                reason = ("model output truncated" if not raw.rstrip().endswith("}")
                          else "model output invalid")
            except Exception as e:  # noqa: BLE001 — 생성 중 GPU 오류 등. auto 면 규칙으로 넘어간다
                if mode == "model":
                    raise
                _LOG.warning("2단 생성 실패 — 규칙으로 폴백: %s: %s", type(e).__name__, e)
                findings, reason = None, _public_reason(e)
            if findings is None:
                if mode == "model":
                    raise RuntimeError("2단 모델 출력을 파싱하지 못했다")
                version = f"{RULES_VERSION} (fallback: {reason})"
            else:
                version = getattr(m, "model_version", MODEL_VERSION)
    if findings is None:
        findings = findings_from_spans(all_entries)  # 규칙 판정은 줄이지 않은 전체로
    rec_posts = [{"post_id": p["post_id"], "spans": list(p.get("spans") or []), "geo_tag": p.get("geo_tag")}
                 for p in posts]
    if rec_posts:
        recommendation = recommend(user_ref=user_ref, posts=rec_posts, target_risk=target_risk,
                                   conditions_fn=_app_conditions, geo_condition_fn=_app_geo_condition)
    else:  # 글이 없는 계정 — 오류 대신 「위험 없음 · 조치 없음」
        recommendation = {"actions": [], "projected": {"current_risk": 0.0, "projected_risk": 0.0,
                                                       "reduction_pct": None, "target_met": True},
                          "optimality_gap_pct": None}
    return {
        "schema_version": SCHEMA_VERSION,
        "findings": findings,
        "recommendation": recommendation,
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
