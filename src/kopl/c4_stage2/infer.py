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
"""

from __future__ import annotations

import hashlib
import json
import logging
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
# 오프라인 GPU 서버(HF_HUB_OFFLINE=1)는 허브 이름 대신 받아 둔 스냅샷 폴더를 가리킨다 — 비우면 허브 이름 (서버 전용 커밋 258f904 를 main 으로)
BASE_MODEL = os.getenv("STAGE2_BASE_MODEL_DIR") or "Qwen/Qwen3-4B"
MODEL_VERSION = "qwen3-4b-qlora-v2"
RULES_VERSION = "rules-v1"
_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ADAPTER = _ROOT / "experiments" / "exp08-stage2-sft" / "results" / "adapter_v2"
# v1 어댑터 가중치 해시 (DEC-009 · 되돌리기용 보존). v2 프롬프트 · 상한으로 v1 가중치를 돌리면 판정하지 않은 구성이라 막는다 —
# 예전 STAGE2_ADAPTER_DIR 이 v1 을 가리킨 채 남은 PC 에서 조용히 섞이지 않게 (되돌리기는 models/registry.md)
V1_ADAPTER_SHA256 = "1053e7adcc77d1863e0789978b468d29d92930dc9c26a84a0a29e7fbc99a6a4b"
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


_LOG = logging.getLogger(__name__)


def _public_reason(e: BaseException) -> str:
    """응답 provenance 에 싣는 실패 이유 — 고정 문구만. 원문(PC 경로 등)은 서버 로그에만 남긴다 (#347 리뷰).

    /scan 응답 JSON 은 화면 밖으로도 나가므로, 예외 문장을 그대로 실으면 어댑터 절대 경로가 샌다.
    """
    msg = str(e)
    if isinstance(e, FileNotFoundError):
        return "2단 어댑터 없음"
    if isinstance(e, ImportError):
        return "추론 라이브러리 없음"
    if msg.startswith("v1 어댑터를 v2 구성으로"):
        return "v1 어댑터 거부 (v2 구성)"
    if msg.startswith("CUDA GPU 가 없다"):
        return "CUDA GPU 없음"
    if "out of memory" in msg:
        return "GPU 메모리 부족"
    return type(e).__name__


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
                _LOG.warning("2단 모델 로드 실패 — 규칙으로 폴백: %s: %s", type(e).__name__, e)
                _MODEL_ERROR = _public_reason(e)
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
    model: Stage2Model | None = None,
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
                raw = (m.generate(user_prompt, max_new_tokens=output_budget(entries)) if isinstance(m, Stage2Model)
                       else m.generate(user_prompt))
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
                version = MODEL_VERSION
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
