"""c4_stage2 — 2단(추론·조치) 입력용 가명화·복원 계층.

docs/contracts/label-schema.md §3-2(정본 10종) 및 span.schema.json 준수.

목적:
- 1단(c1_span)이 뽑은 스팬을 가명 토큰으로 치환해 QLoRA 학습·추론 입력을 만든다.
- 추론 후 모델 출력의 가명 토큰을 원문으로 되돌린다(restore).
- 계약상 완료 기준은 라운드트립: restore(anonymize(text, spans)[0], key) == text.

전제: text 는 NFC 정규화된 문자열이고 스팬 offset 은 그 위에서 정의된다
(span.schema.json 제약 1). 이 모듈은 입력을 그대로 보존하므로 NFC 보장은 호출 측 몫이다.

라운드트립 보장 방식:
- 각 가명 토큰은 (1) 서로 유일하고 (2) 원문에 부분문자열로 존재하지 않도록 만든다.
  → 원문에 우연히 토큰처럼 생긴 리터럴이 있어도 복원이 그것을 건드리지 않는다.
- restore 는 모든 토큰을 한 번에(single-pass) 치환한다.
  → 이미 복원된 원문이 다음 치환에 다시 걸리는 연쇄를 구조적으로 막는다.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Tuple

# label-schema §3-2 정본 10종 → 사람이 읽을 수 있는 가명 라벨 접두어.
# AGE 는 연령대 일반화를 따로 하므로 여기서는 폴백 라벨로만 쓴다.
TYPE_LABELS: Dict[str, str] = {
    "AGE": "나이",
    "SEX": "성별",
    "LOC_ADMIN": "지역",
    "LOC_FACILITY": "시설",
    "REL_HOME": "거주관계",
    "REL_WORK": "직장관계",
    "JOB": "직업",
    "FAM": "가족",
    "COMMUTE": "통근지",
    "INCOME": "소득",
}

_DIGIT_RE = re.compile(r"\d+")

# 사람 나이로 볼 수 있는 상한. 이를 넘거나 '년'(출생연도)이 붙으면 연령대로 환산하지 않는다.
_MAX_AGE = 149


def _age_decade(text: str) -> str:
    """'48'·'48세'·'40대' → '40'. 나이로 환산할 수 없으면 빈 문자열.

    - 한글 수사('마흔여덟')는 환산하지 않는다 (숫자 없음).
    - 출생연도('1990년생')·비현실적 숫자('1990')는 나이가 아니므로 환산하지 않는다.
      → §3-2 상 AGE 여도 값이 나이가 아니면 일반 토큰으로 떨어지되 라운드트립은 보장된다.
    """
    if "년" in text:  # '1990년생'·'90년대생' 등 출생연도 표현
        return ""
    m = _DIGIT_RE.search(text)
    if not m:
        return ""
    try:
        n = int(m.group())
    except ValueError:
        # 비정상적으로 긴 숫자열(Python int 변환 한도 등)
        return ""
    if not (0 <= n <= _MAX_AGE):  # 출생연도 등 나이 범위 밖
        return ""
    return str((n // 10) * 10)


def _validate_spans(text: str, spans: List[Dict[str, Any]]) -> None:
    """anonymize 입력 경계 검증. c1_span.validate_span_output 이 이미 거르지만,
    잘못된 스팬이 오면 조용히 원문과 다른 문자열로 복원되므로 여기서 명확히 막는다.

    - offset 범위: 0 <= start < end <= len(text) (span.schema.json)
    - 텍스트 일치: text[start:end] == sp["text"]
    - 겹침 금지: 같은 채널 내 겹침 (label-schema §6) — 역순 교체가 토큰을 절단
    """
    n = len(text)
    for sp in spans:
        start, end = sp["start"], sp["end"]
        if not (0 <= start < end <= n):
            raise ValueError(
                f"스팬 offset 범위 오류: [{start},{end}) "
                f"(0 <= start < end <= {n} 필요) — {sp.get('text')!r}"
            )
        if text[start:end] != sp["text"]:
            raise ValueError(
                f"스팬 텍스트 불일치: text[{start}:{end}]={text[start:end]!r} "
                f"!= {sp['text']!r}"
            )

    ordered = sorted(spans, key=lambda s: (s["start"], s["end"]))
    for prev, cur in zip(ordered, ordered[1:]):
        if cur["start"] < prev["end"]:
            raise ValueError(
                "겹치는 스팬 (label-schema §6 위반): "
                f"[{prev['start']},{prev['end']}) {prev.get('text')!r} vs "
                f"[{cur['start']},{cur['end']}) {cur.get('text')!r}"
            )


def _unique_token(
    build: Callable[[str], str],
    original: str,
    used: Dict[str, str],
    text: str,
) -> str:
    """유일하고 원문에 없는 토큰을 만든다.

    build(suffix): suffix 를 붙인 후보 토큰을 만드는 함수. build("") 가 기본형.
    후보가 원문에 존재하거나 다른 원문에 이미 쓰였으면 '_2', '_3' … 으로 분리한다.
    동일 원문에는 같은 토큰을 재사용해도 무방하다.
    """
    candidate = build("")
    k = 1
    while candidate in text or used.get(candidate, original) != original:
        k += 1
        candidate = build(f"_{k}")
    used[candidate] = original
    return candidate


def _make_placeholder(
    typ: str,
    original: str,
    type_counter: Dict[str, int],
    used: Dict[str, str],
    text: str,
) -> str:
    """스팬 하나에 유일하고 원문과 충돌하지 않는 가명 토큰을 배정한다.

    정본 10종(§3-2) 밖의 유형은 조용히 처리하지 않고 거부한다 — span.schema.json
    의 유형 상한 위반을 호출 측이 확인할 수 있어야 한다.
    """
    if typ not in TYPE_LABELS:
        raise ValueError(
            f"허용되지 않은 스팬 유형: {typ!r} (정본 10종만 허용, label-schema §3-2)"
        )

    if typ == "AGE":
        decade = _age_decade(original)
        if decade:
            return _unique_token(lambda sfx: f"[{decade}대{sfx}]", original, used, text)

    label = TYPE_LABELS[typ]
    type_counter[typ] = type_counter.get(typ, 0) + 1
    n = type_counter[typ]
    return _unique_token(lambda sfx: f"[{label}{n}{sfx}]", original, used, text)


def anonymize(text: str, spans: List[Dict[str, Any]]) -> Tuple[str, Dict[str, str]]:
    """원문 + 스팬 목록 → (가명 텍스트, 복원 키).

    text:  원문 문자열 (NFC)
    spans: c1_span 출력 스팬 목록. 각 원소는 start·end·type·text 를 가진다.

    반환:
      anon_text: 가명 토큰으로 치환된 텍스트
      key:       {가명토큰: 원문} 복원 매핑

    입력을 경계에서 검증한다(offset 범위·텍스트 일치·겹침·정본 10종). 스팬은
    뒤(큰 start)에서 앞으로 교체해 offset 밀림을 막는다.
    """
    _validate_spans(text, spans)

    ordered = sorted(spans, key=lambda s: s["start"], reverse=True)
    key: Dict[str, str] = {}
    type_counter: Dict[str, int] = {}
    used: Dict[str, str] = {}

    result = text
    for sp in ordered:
        typ = sp.get("type", "UNKNOWN")
        original = sp["text"]
        placeholder = _make_placeholder(typ, original, type_counter, used, text)
        key[placeholder] = original
        result = result[: sp["start"]] + placeholder + result[sp["end"] :]

    return result, key


def restore(anon_text: str, key: Dict[str, str]) -> str:
    """가명 텍스트 + 복원 키 → 원문.

    모든 토큰을 정규식 하나로 한 번에 치환한다. 순차 치환과 달리 이미 복원된
    원문이 다음 토큰 치환에 다시 걸리지 않는다. 긴 토큰을 먼저 매칭해
    접두어가 겹치는 후보의 오매칭을 피한다.
    """
    if not key:
        return anon_text
    pattern = re.compile("|".join(re.escape(tok) for tok in sorted(key, key=len, reverse=True)))
    return pattern.sub(lambda m: key[m.group(0)], anon_text)
