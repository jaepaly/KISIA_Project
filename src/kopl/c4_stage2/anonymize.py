"""c4_stage2 — 2단(추론·조치) 입력용 가명화·복원 계층.

docs/contracts/label-schema.md §3-2(정본 10종) 및 span.schema.json 준수.

목적:
- 1단(c1_span)이 뽑은 스팬을 가명 토큰으로 치환해 QLoRA 학습·추론 입력을 만든다.
- 추론 후 모델 출력의 가명 토큰을 원문으로 되돌린다(restore).
- 계약상 완료 기준은 라운드트립: restore(anonymize(text, spans)[0], key) == text.

전제: text 는 NFC 정규화된 문자열이고 스팬 offset 은 그 위에서 정의된다
(span.schema.json 제약 1). 이 모듈은 입력을 그대로 보존하므로 NFC 보장은 호출 측 몫이다.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

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


def _age_decade(text: str) -> str:
    """'48'·'48세'·'40대' → '40'. 숫자가 없으면(한글 나이 등) 빈 문자열.

    한글 수사('마흔여덟')는 환산하지 않는다 — 파서를 두면 오차·유지비만 늘고,
    일반화 실패 시 일반 토큰으로 떨어져도 라운드트립은 그대로 보장된다.
    """
    m = _DIGIT_RE.search(text)
    if not m:
        return ""
    return str((int(m.group()) // 10) * 10)


def _make_placeholder(
    typ: str,
    original: str,
    type_counter: Dict[str, int],
    used: Dict[str, str],
) -> str:
    """스팬 하나에 유일한 가명 토큰을 배정한다.

    같은 토큰이 서로 다른 원문에 매핑되면 복원이 깨지므로, 유일성을 항상 보장한다.
    동일 원문에는 같은 토큰을 재사용해도 라운드트립이 유지된다.
    """
    if typ == "AGE":
        decade = _age_decade(original)
        if decade:
            base = f"[{decade}대]"
            if used.get(base, original) == original:
                used[base] = original
                return base
            # 같은 연령대인데 원문이 다르다 → 접미어로 분리 (48세 vs 42세)
            k = 2
            while used.get(f"[{decade}대_{k}]", original) != original:
                k += 1
            tok = f"[{decade}대_{k}]"
            used[tok] = original
            return tok

    label = TYPE_LABELS.get(typ, "단서")
    type_counter[typ] = type_counter.get(typ, 0) + 1
    tok = f"[{label}{type_counter[typ]}]"
    used[tok] = original
    return tok


def anonymize(text: str, spans: List[Dict[str, Any]]) -> Tuple[str, Dict[str, str]]:
    """원문 + 스팬 목록 → (가명 텍스트, 복원 키).

    text:  원문 문자열 (NFC)
    spans: c1_span 출력 스팬 목록. 각 원소는 start·end·type·text 를 가진다.

    반환:
      anon_text: 가명 토큰으로 치환된 텍스트
      key:       {가명토큰: 원문} 복원 매핑

    스팬은 뒤(큰 start)에서 앞으로 교체해 offset 밀림을 막는다.
    """
    ordered = sorted(spans, key=lambda s: s["start"], reverse=True)
    key: Dict[str, str] = {}
    type_counter: Dict[str, int] = {}
    used: Dict[str, str] = {}

    result = text
    for sp in ordered:
        typ = sp.get("type", "UNKNOWN")
        original = sp["text"]
        placeholder = _make_placeholder(typ, original, type_counter, used)
        key[placeholder] = original
        result = result[: sp["start"]] + placeholder + result[sp["end"] :]

    return result, key


def restore(anon_text: str, key: Dict[str, str]) -> str:
    """가명 텍스트 + 복원 키 → 원문.

    긴 토큰부터 치환해 접두어가 겹치는 토큰([40대] ⊂ [40대_2] 형태)의
    부분 치환을 막는다.
    """
    result = anon_text
    for placeholder in sorted(key, key=len, reverse=True):
        result = result.replace(placeholder, key[placeholder])
    return result
