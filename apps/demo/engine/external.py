"""외부 LLM 호출은 이 파일에서만 한다 (E-system.md §2 「한 파일에서만 · 게이트를 통과」).

기본값은 **꺼짐**이다. 켜려면 두 조건이 모두 필요하다 —
    DEMO_EXTERNAL_REWRITE=true   AND   ANTHROPIC_API_KEY 또는 ANTHROPIC_AUTH_TOKEN 이 있다 (선택: ANTHROPIC_BASE_URL).
    켜져 있고 환경변수가 비어 있으면 저장소 루트의 .env 에서 ANTHROPIC_* 만 읽는다 (키는 파일에만 둔다).

켜지면 리라이트의 «다르게 쓰기» 후보를 API 로 만들고, provenance.external_llm_used 가 true 가 된다.
사다리(지명 → 상위 행정구역, 나이 → 10년 단위)와 그 인구 수는 여전히 규칙이 낸다 — **숫자는 규칙, 말은 모델, 검사는 규칙**.
꺼져 있거나 실패하면 `recommend.py` 의 캐시·규칙 후보를 쓴다. 데모 페이지는 어느 쪽을 썼는지 표시한다.

⚠️ 보내는 것은 단서 문장 하나와 앞뒤 문장, 스팬 구간뿐이다. 글 전체·닉네임·user_ref 는 보내지 않는다.
   .env 의 ALLOW_EXTERNAL_LLM 기본값은 건드리지 않는다 — 이 게이트는 데모 전용 별도 스위치다.
   협회 게이트웨이(monogpt.kr monorouter, Anthropic 호환)는 SDK 기본 User-Agent 를 막는다 → 우리 이름으로 보낸다.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

MODEL = os.getenv("DEMO_EXTERNAL_MODEL", "claude-haiku-4.5")
_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv_keys() -> None:
    """환경변수에 키가 없을 때만 .env 의 ANTHROPIC_* 를 읽는다. 값이 있는 마지막 줄이 이긴다."""
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return
    f = _ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k.startswith("ANTHROPIC_") and v:
            os.environ[k] = v


def _client():
    """API 키(ANTHROPIC_API_KEY) 또는 인증 토큰(ANTHROPIC_AUTH_TOKEN) 어느 쪽이든. ANTHROPIC_BASE_URL 이 있으면 그리로."""
    import anthropic
    kw: dict[str, Any] = {}
    if os.getenv("ANTHROPIC_AUTH_TOKEN"):
        kw["auth_token"] = os.environ["ANTHROPIC_AUTH_TOKEN"]
    elif os.getenv("ANTHROPIC_API_KEY"):
        kw["api_key"] = os.environ["ANTHROPIC_API_KEY"]
    if os.getenv("ANTHROPIC_BASE_URL"):
        kw["base_url"] = os.environ["ANTHROPIC_BASE_URL"]
    return anthropic.Anthropic(**kw, max_retries=1, timeout=20, default_headers={"User-Agent": "padopool-demo/0.1"})


def enabled() -> bool:
    if os.getenv("DEMO_EXTERNAL_REWRITE", "").lower() != "true":
        return False
    _load_dotenv_keys()
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


_PARTICLE_ALT = {"이": "가", "가": "이", "을": "를", "를": "을", "은": "는", "는": "은", "과": "와", "와": "과"}
# 구간 바로 뒤에 붙는 조사 — 문장에 그대로 남아 있으므로 모델 답 끝에 같은 조사가 있으면 뗀다 (「오일장에」→「장에」+「에」 = 「장에에」 방지)
_TAIL_PARTICLES = ("에서는", "에서", "으로", "부터", "까지", "한테", "께서", "에", "로", "의", "도", "만", "은", "는", "이", "가", "을", "를", "과", "와")


def _trim_tail(sentence: str, span_text: str, out: str, particle: str = "") -> str:
    """모델이 구간 뒤 말(「정류장에서」「되니」)까지 붙여 돌려줬으면 문장의 그 꼬리를 잘라낸다. 조사(와 그 받침 변형)도 뗀다."""
    i = sentence.find(span_text)
    tail = sentence[i + len(span_text):] if i >= 0 else ""
    if particle and tail.startswith(particle):
        tail = tail[len(particle):]
    # 구간 뒤에 조사가 이어지면(「오일장|에 다녀왔다」) 답 끝의 조사는 어떤 것이든 뗀다 — 문장의 조사가 그대로 남아 붙기 때문 (「장에」+에, 「장을」+에)
    if any(tail.startswith(tp) for tp in _TAIL_PARTICLES):
        for tp in sorted(_TAIL_PARTICLES, key=len, reverse=True):
            if out.endswith(tp) and len(out) > len(tp) + 0 and len(out) - len(tp) >= 1:
                out = out[: -len(tp)].rstrip()
                break
        for tp in _TAIL_PARTICLES:
            if tail.startswith(tp):
                tail = tail[len(tp):]
                break
    tail = tail.lstrip()
    for pt in ({particle, _PARTICLE_ALT.get(particle, "")} - {""}):
        if out.endswith(pt) and len(out) > len(pt):
            out = out[: -len(pt)].rstrip()
    for L in range(len(tail), 1, -1):
        piece = tail[:L].rstrip()
        if len(piece) >= 2 and out.endswith(piece):
            return out[: -len(piece)].rstrip()      # 꼬리만 돌려줬으면 빈 문자열 = «지운다»
    return out


def _extract_span(sentence: str, span_text: str, out: str, particle: str = "") -> str | None:
    """모델이 구간 대신 문장 전체를 돌려줬으면 앞뒤 공통 부분을 벗겨 대체 표현만 남긴다. 못 벗기면 None."""
    out = out.strip().strip("「」\"'")
    if not out or out == span_text:
        return None
    if len(out) <= max(24, len(span_text) * 3) and out not in sentence:
        return _trim_tail(sentence, span_text, out, particle)      # "" 이면 지우기 후보
    # 문장 전체 형태 — 공통 접두·접미 벗기기
    i = 0
    while i < min(len(sentence), len(out)) and sentence[i] == out[i]:
        i += 1
    j = 0
    while j < min(len(sentence), len(out)) - i and sentence[-1 - j] == out[-1 - j]:
        j += 1
    core = out[i: len(out) - j].strip()
    if not core or core == span_text or len(core) > max(30, len(span_text) * 4):
        return None
    return core


def rewrite_candidates(sentence: str, span_text: str, voice_hint: str,
                       context: dict[str, Any] | None = None) -> list[dict[str, Any]] | None:
    """«다르게 쓰기» 후보 — [{"text": 구간을 대신할 표현, "note": 한 줄 설명}] 2~3개. 실패·비활성이면 None.

    context = {"prev": 앞 문장, "next": 뒤 문장, "ladder": ["김해시", "경남"], "particle": "에", "already": "「집 앞」→「근처」"}
    """
    if not enabled():
        return None
    ctx = context or {}
    system = (
        "너는 한국어 글의 프라이버시 리라이터다. 문장에서 표시된 구간을 대신할 표현만 만든다. "
        "말투·어미·방언·문장 부호는 그대로 두고, 신상(지명·행정단위·시설 이름·배차 간격·나이·소득 주기)이 새는 정보만 없앤다. "
        "규칙: (1) 출력의 text 에는 구간을 대신할 표현만 쓴다 — 문장 전체를 쓰지 않는다, 구간 뒤에 오는 조사는 넣지 않는다. "
        "(2) 앞뒤 문장과 이어 읽었을 때 자연스러워야 한다. 같은 문장에 이미 바뀐 구간이 있으면 그 말과 겹치거나 반복되지 않게 한다. "
        "(3) 「사다리」로 적힌 상위 지명·연령대는 이미 제안됐으니 똑같은 안은 내지 않는다 — 대신 정보를 지우거나 에둘러 말한다. "
        "나이·장소를 다른 값이나 다른 연령대로 바꾸지 않는다(스물셋 → «스물 안 된», 예순여덟 → «여든 가까운» 은 거짓이다). "
        "방언·어미는 원문에 있는 것만 쓰고 새로 만들지 않는다(«안 오라» 같은 어미를 지어내지 않는다). "
        "(4) 후보 3개: ① 정보만 지운 최소 수정 ② 표현을 조금 더 바꾼 안 ③ 이유나 서술 자체를 바꾼 안. 없던 사실을 지어내지 않는다. "
        'JSON 배열만 출력한다: [{"text": "...", "note": "10자 안팎 설명"}]'
    )
    user = (f"문장: {sentence}\n바꿀 구간: {span_text}\n말투 힌트: {voice_hint}"
            f"\n앞 문장: {ctx.get('prev') or '(없음)'}\n뒤 문장: {ctx.get('next') or '(없음)'}"
            f"\n구간 뒤 조사: {ctx.get('particle') or '(없음)'}"
            f"\n이미 바뀐 구간: {ctx.get('already') or '(없음)'}"
            f"\n사다리(이미 제안됨, 피할 것): {' → '.join(ctx.get('ladder') or []) or '(없음)'}")
    try:
        msg = _client().messages.create(model=MODEL, max_tokens=400, system=system,
                                        messages=[{"role": "user", "content": user}])
        content = msg.content[0].text.strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?|\n?```$", "", content).strip()
        arr = json.loads(content)
        out: list[dict[str, Any]] = []
        particle = ctx.get("particle") or ""
        for a in arr:
            t = _extract_span(sentence, span_text, str(a.get("text", "")), particle)
            if t is None:
                continue
            if any(t == o["text"] for o in out):
                continue
            out.append({"text": t, "note": (str(a.get("note", "")).strip()[:40] if t else "그냥 지운다"), "source": "llm"})
        return out[:3] or None
    except Exception:  # noqa: BLE001 — 데모는 외부 실패로 멈추지 않는다. 캐시·규칙으로 떨어진다
        return None
