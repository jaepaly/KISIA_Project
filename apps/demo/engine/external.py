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
# 심사위원을 기다리게 하지 않는다 — 이 안에 답이 안 오면 규칙·캐시 후보로 떨어진다(화면은 그대로 뜬다).
# 환경변수라 9/20 동결 뒤에도 서버에서 조절할 수 있다.
TIMEOUT = float(os.getenv("DEMO_EXTERNAL_TIMEOUT", "8"))
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
    return anthropic.Anthropic(**kw, max_retries=0, timeout=TIMEOUT, default_headers={"User-Agent": "padopool-demo/0.1"})


def enabled() -> bool:
    if os.getenv("DEMO_EXTERNAL_REWRITE", "").lower() != "true":
        return False
    _load_dotenv_keys()
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


# 꼬리를 떼다 남은 한 글자 — 「그」「한」「밖」 은 뜻이 없다. 「장」「길」「역」 처럼 뜻이 있는 한 글자는 남긴다
# 조사·연결어미로 끝나는 말 — 「하다」 앞자리에는 못 온다
_ENDINGS = set("는은이가을를에서로고며면야의도만랑과와")
_EMPTY_ONE = {"그", "이", "저", "한", "밖", "안", "것", "데", "때", "수", "더", "또"}
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
            cut = out[: -len(piece)].rstrip()       # 꼬리만 돌려줬으면 빈 문자열 = «지운다»
            # 자르고 나면 조사가 다시 끝에 드러난다 — 「장이 서지 않는 날의」 → 「장이」 → 「장」
            for pt in ({particle, _PARTICLE_ALT.get(particle, "")} - {""}):
                if cut.endswith(pt) and len(cut) > len(pt):
                    cut = cut[: -len(pt)].rstrip()
            return cut
    # 한 글자짜리 낱말도 겹치면 뗀다 — 「면사무소」→「그 앞」 이 「그 앞 앞 정류장」 이 되는 것 (9/16 배포 확인)
    head = tail.split()[0] if tail.split() else ""
    if head and out.endswith(head):
        return out[: -len(head)].rstrip()           # out 이 그 낱말뿐이면 "" = «지운다»
    return out


# 행정단위를 슬쩍 바꾸는 답을 버리기 위한 것 — 궁류«면» 사람에게 「읍사무소」는 거짓이다 (9/16 배포에서 발견).
# 프롬프트로도 막고 있지만 확률이라 샌다. 여기서 규칙이 한 번 더 거른다 — 「숫자는 규칙, 말은 모델, 검사는 규칙」.
_ADMIN_OFFICE = ("읍사무소", "면사무소", "동사무소", "리사무소", "시청", "군청", "구청", "도청")
_UNIT_TAIL = re.compile(r"[가-힣]{2,}([시군구읍면동리])$")
# 「면사무소」 → 「작은 «읍»의 관공서」 처럼 다른 단위 낱말이 끼어드는 것 (궁류면 사람에게 읍은 거짓이다)
_UNIT_WORD = re.compile(r"(?:^|[\s의])([읍면동리])(?:$|[\s의에])")


def _swaps_admin_unit(span_text: str, out: str) -> bool:
    """구간과 답이 «다른» 행정단위를 가리키면 True — 면사무소→읍사무소, 진영읍→진영동.

    구간에서 덜어내기만 한 답(「김해시 진영읍」→「김해시」)은 거짓이 아니므로 통과시킨다.
    """
    if out.strip() and out.strip() in span_text:
        return False
    a = {w for w in _ADMIN_OFFICE if w in span_text}
    b = {w for w in _ADMIN_OFFICE if w in out}
    if a and b and a != b:
        return True
    ma, mb = _UNIT_TAIL.search(span_text.strip()), _UNIT_TAIL.search(out.strip())
    if ma and mb and ma.group(1) != mb.group(1):
        return True
    unit = {w[0] for w in a} | ({ma.group(1)} if ma else set())        # 구간이 걸친 단위(면사무소 → 「면」)
    return bool(unit and {m.group(1) for m in _UNIT_WORD.finditer(out)} - unit)


# 가족 호칭은 바꾸면 «다른 사람» 이 된다. 「남편」→「집사람」 은 성별까지 뒤집혀 거짓이 된다 (D06 은 여성).
_FAMILY = [
    {"남편", "신랑", "바깥양반", "서방"},
    {"아내", "집사람", "마누라", "와이프", "안사람", "처"},
    {"아들"}, {"딸"}, {"아버지", "아빠", "부친"}, {"어머니", "엄마", "모친"},
    {"형", "오빠"}, {"누나", "언니"}, {"할아버지"}, {"할머니"},
]


def _swaps_family_term(span_text: str, out: str) -> bool:
    """구간의 가족 호칭을 «다른» 호칭으로 바꾸면 True."""
    mine = {i for i, g in enumerate(_FAMILY) if any(w in span_text for w in g)}
    if not mine:
        return False
    theirs = {i for i, g in enumerate(_FAMILY) if any(w in out for w in g)}
    return bool(theirs - mine)


def _clashes_with_verb(sentence: str, span_text: str, out: str, after: str = "") -> bool:
    """구간이 「출근」처럼 «하다» 앞에 붙는 말인데 답이 부사구면 True — 「직장에서」+「할 때」.

    이 자리에 올 수 있는 것은 명사뿐이다.
    """
    if after:
        nxt = after[:1]                        # 같은 말이 문장에 여러 번 나오면 find 는 엉뚱한 자리를 본다
    else:
        i = sentence.find(span_text)
        nxt = sentence[i + len(span_text): i + len(span_text) + 1] if i >= 0 else ""
    # 이 자리에 올 수 있는 것은 명사뿐이다 — 조사나 연결어미로 끝나면 「…에서는할 때」 가 된다
    return nxt in ("하", "한", "할", "해", "했") and out[-1:] in _ENDINGS


def _echoes_tail(sentence: str, span_text: str, out: str) -> bool:
    """답이 구간 바로 뒤에 오는 말을 다시 품고 있으면 True.

    「오일장」 뒤가 「이 서지 않는 날의」 인데 답이 「장날이 아닌 날의」 면 넣었을 때 같은 말이 두 번 나온다.
    모델이 구간이 아니라 «절» 을 바꾸려 들 때 생긴다.
    """
    i = sentence.find(span_text)
    head = sentence[i + len(span_text): i + len(span_text) + 12] if i >= 0 else ""
    words = [w for w in head.replace(",", " ").split() if len(w) >= 2]
    return any(w in out for w in words)


def _borrows_other_clue(out: str, others: list[str] | None) -> bool:
    """답이 같은 문장의 «다른 단서» 를 그대로 끌어다 쓰면 True.

    「면사무소」→「정류장 근처」, 「정류장」→「면사무소 앞 …」 — 하나를 가리면서 다른 하나를 드러낸다.
    """
    return any(o and len(o) >= 2 and o in out for o in (others or []))


def _repeats_nearby(sentence: str, span_text: str, out: str) -> bool:
    """답을 넣었을 때 바로 뒤 몇 낱말 안에서 같은 말이 되풀이되면 True.

    「면사무소」→「읍내 정류장」 이 「읍내 정류장 앞 정류장」 이 되는 것. 억지로 다듬기보다 후보를 버린다.
    """
    i = sentence.find(span_text)
    tail = sentence[i + len(span_text):] if i >= 0 else ""
    words = (out + " " + tail).split()[:6]
    seen: dict[str, int] = {}
    for n, w in enumerate(words):
        w = w.strip(".,!?·“”‘’\"'")
        if len(w) < 2:
            continue
        if w in seen and n - seen[w] <= 2:
            return True
        seen[w] = n
    return False


def _extract_span(sentence: str, span_text: str, out: str, particle: str = "") -> str | None:
    """모델이 구간 대신 문장 전체를 돌려줬으면 앞뒤 공통 부분을 벗겨 대체 표현만 남긴다. 못 벗기면 None."""
    out = out.strip().strip("「」\"'")
    if not out or out == span_text:
        return None
    # 길이로만 가른다 — 예전에는 «답이 원문 안에 있으면 문장을 통째로 돌려준 것» 으로 봤는데,
    # 「오일장」→「장에」 처럼 답이 원문의 일부와 겹치면 엉뚱한 가지로 빠져 조사가 안 떨어졌다 (9/16)
    if len(out) <= max(24, len(span_text) * 3) and len(out) < len(sentence) * 0.6:
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
        "「같은 문장의 다른 단서」로 적힌 말은 그것 자체가 가려야 할 정보이므로 대신 쓰지 않는다. "
        "(3) 「사다리」로 적힌 상위 지명·연령대는 이미 제안됐으니 똑같은 안은 내지 않는다 — 대신 정보를 지우거나 에둘러 말한다. "
        "나이·장소를 다른 값이나 다른 연령대로 바꾸지 않는다(스물셋 → «스물 안 된», 예순여덟 → «여든 가까운» 은 거짓이다). "
        "방언·어미는 원문에 있는 것만 쓰고 새로 만들지 않는다(«안 오라» 같은 어미를 지어내지 않는다). "
        "가족 호칭은 다른 호칭으로 바꾸지 않는다(남편 → «집사람» 은 사람이 바뀐다). 지우거나 «그 사람» 처럼 두루뭉술하게 한다. "
        "(4) 후보 3개: ① 정보만 지운 최소 수정 ② 표현을 조금 더 바꾼 안 ③ 이유나 서술 자체를 바꾼 안. 없던 사실을 지어내지 않는다. "
        'JSON 배열만 출력한다: [{"text": "...", "note": "10자 안팎 설명"}]'
    )
    user = (f"문장: {sentence}\n바꿀 구간: {span_text}\n말투 힌트: {voice_hint}"
            f"\n앞 문장: {ctx.get('prev') or '(없음)'}\n뒤 문장: {ctx.get('next') or '(없음)'}"
            f"\n구간 뒤 조사: {ctx.get('particle') or '(없음)'}"
            f"\n이미 바뀐 구간: {ctx.get('already') or '(없음)'}"
            f"\n사다리(이미 제안됨, 피할 것): {' → '.join(ctx.get('ladder') or []) or '(없음)'}")
    try:
        # 1200 — 후보 3개는 200토큰이면 되지만, 「생각」을 하는 큰 모델은 그 예산까지 여기서 쓴다.
        # 400 이면 생각하다 답이 잘려 후보가 통째로 사라졌다 (claude-sonnet-5, 9/16)
        msg = _client().messages.create(model=MODEL, max_tokens=1200, system=system,
                                        messages=[{"role": "user", "content": user}])
        # 큰 모델은 답 앞에 «생각» 블록을 붙여 보낸다 — 글 블록만 모은다 (haiku 는 글 하나뿐이라 그대로다)
        content = "\n".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
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
            if t and _swaps_admin_unit(span_text, t):
                continue                       # 행정단위를 바꾼 답은 버린다 (거짓이 된다)
            if t and _repeats_nearby(sentence, span_text, t):
                continue                       # 넣으면 같은 말이 겹치는 답도 버린다
            if t and _echoes_tail(sentence, span_text, t):
                continue                       # 구간 뒤의 말을 도로 끌어안은 답도 버린다
            if t and _clashes_with_verb(sentence, span_text, t, ctx.get("after") or ""):
                continue                       # 「출근」 자리에 부사구를 넣어 「직장에서할 때」 가 되는 답도 버린다
            if t and _borrows_other_clue(t, ctx.get("others")):
                continue                       # 같은 문장의 다른 단서를 끌어다 쓴 답도 버린다
            if len(t) > max(14, len(span_text) * 4):
                continue                       # 구간을 대신할 «표현» 이 아니라 문장을 새로 쓴 답은 버린다
            if _swaps_family_term(span_text, t):
                continue                       # 가족 호칭을 바꾼 답은 버린다 (다른 사람이 된다)
            if t in _EMPTY_ONE:
                continue                       # 꼬리만 남은 한 글자는 후보가 아니다
            out.append({"text": t, "note": (str(a.get("note", "")).strip()[:40] if t else "그냥 지운다"), "source": "llm"})
        return out[:3] or None
    except Exception:  # noqa: BLE001 — 데모는 외부 실패로 멈추지 않는다. 캐시·규칙으로 떨어진다
        return None
