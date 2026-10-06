"""조사 맞춤 — 단서 구간을 다른 말로 바꿀 때 뒤에 붙은 조사·어미를 새 말에 맞춘다.

라벨 규칙(label-schema §5-2)상 스팬은 **끝 어절의 조사·어미를 포함한다** — 「신촌에서」 「서른넷인데」 「아이들은」.
그래서 바꿔 쓰기는 스팬을 「바꿀 말(core) + 그대로 둘 꼬리(tail)」로 쪼개고, 꼬리의 조사를 새 말의 끝소리에 맞춘다.

- 꼬리가 스팬 **안**에 있으면 → 조사 형태를 새 말에 맞춰 바꾼다 (「서른넷이」 → 「40대가」)
- 꼬리가 스팬 **밖**(뒤 글자)에 있으면 → 밖은 고칠 수 없으므로 **그 조사와 끝소리가 맞는 후보만** 쓴다
- 어절이 스팬 밖으로 이어지는데(「[서른셋이]야」) 조사 형태가 바뀌어야 하면 → 고칠 수 없으므로 기권
- **꼬리를 다 알아보지 못하면 기권한다** — 모르는 어미를 버리거나 잘못 붙이는 것보다 낫다

받침 판단: 한글은 종성, 숫자는 읽는 소리(「40」 → 사십 → ㅂ), 영문 약어는 알파벳 이름(KTX → 케이티엑스),
영어 단어는 발음을 확정할 수 없어 판단하지 않는다 (None).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 받침 있는 말 뒤 / 없는 말 뒤 형태 쌍 (서술격 「이다」 활용 포함) — 긴 것부터 맞춘다
_PAIRS: list[tuple[str, str]] = [
    ("이었습니다", "였습니다"), ("이었어요", "였어요"), ("이었는데", "였는데"), ("이었지만", "였지만"), ("이었다", "였다"),
    ("이었고", "였고"), ("이었어", "였어"), ("이어서", "여서"), ("이에요", "예요"), ("이지만", "지만"), ("이라서", "라서"),
    ("이라는", "라는"), ("이라고", "라고"), ("이라도", "라도"), ("이라면", "라면"), ("이랑은", "랑은"), ("이랑도", "랑도"),
    ("이랑", "랑"), ("이나마", "나마"), ("이나", "나"), ("이라", "라"), ("이란", "란"), ("이며", "며"), ("이고", "고"),
    ("이든", "든"), ("이야", "야"), ("이여", "여"), ("이지", "지"),
    ("으로부터", "로부터"), ("으로서", "로서"), ("으로써", "로써"), ("으로는", "로는"), ("으로도", "로도"), ("으론", "론"),
    ("으로", "로"),
    ("이", "가"), ("을", "를"), ("은", "는"), ("과", "와"),
]
# 받침과 무관한 조사·어미
_INVARIANT: list[str] = [
    "에서부터", "에서는", "에서도", "에서의", "에서", "에게서", "에게는", "에게", "에는", "에도", "에의", "에", "엔",
    "한테서", "한테는", "한테", "께서는", "께서", "께", "까지는", "까지도", "까지", "부터는", "부터", "보다는", "보다",
    "처럼", "만큼", "마다", "조차", "밖에", "하고", "의", "도", "만", "인데도", "인데", "인지", "인가", "인걸", "인건",
    "입니다", "이다",
]
# 위치 표현에서만 꼬리로 보는 구어 축약 — 「서울서」(= 서울에서). 「경찰서 · 소방서」처럼 「서」로 끝나는 명사가 많다
_LOC_ONLY = ["서"]

_CONS_FORM = {c: v for c, v in _PAIRS}
_VOW_FORM = {v: c for c, v in _PAIRS}
_ALL = sorted({*(_CONS_FORM), *(_VOW_FORM), *_INVARIANT}, key=len, reverse=True)
_ALL_LOC = sorted({*_ALL, *_LOC_ONLY}, key=len, reverse=True)

# 끝이 조사처럼 보이지만 명사인 말 — 「아이 → 아+이」 「회의 → 회+의」로 자르지 않게
_NOUN_ENDS_WITH_PARTICLE = {
    "아이", "고양이", "어린이", "놀이", "길이", "높이", "오이", "거미", "할아버지", "누이", "사이", "나이",
    "아주머니", "어머니", "할머니", "언니", "누나", "오빠", "형님", "막내", "둘째", "셋째", "첫째", "손주", "자녀",
    "이웃", "노인", "주인", "부인", "애인", "직장인", "회사원", "공무원", "간호사", "교사", "기사", "의사", "약사",
    "학원", "공원", "병원", "도서관", "시장", "고등학교", "대학교", "초등학교", "중학교", "어린이집", "유치원", "가게",
    "다리", "거리", "자리", "도로", "대로", "철로", "선로", "산책로", "진로", "경로", "통로", "종로", "을지로", "가로", "세로",
    "마을", "동네", "근처", "주변", "쪽", "앞", "뒤", "옆", "안", "밖", "회의", "지도", "대구", "가구", "부산", "이마트",
}
_NOUN_SUFFIX_NOT_PARTICLE = ("대로", "산책로", "도로", "회의", "지도")  # 「부산대로 · 대학로」 같은 길 이름 등
_PLURAL = "들"
_DEUL_NOUNS = ("아들",)

_DIGIT_JONG = {"0": True, "1": True, "2": False, "3": True, "4": False, "5": False, "6": True, "7": True, "8": True, "9": False}
_DIGIT_RIEUL = {"1", "7", "8"}
_LETTER_NAME_BATCHIM = set("LMNR")      # 약어는 알파벳 이름으로 읽는다 — 엘·엠·엔·알만 받침
_LETTER_NAME_RIEUL = set("LR")          # 엘 · 알 — ㄹ받침
# 끝의 문장부호·이모지·괄호 — 꼬리 뒤에 그대로 둔다
_TRAILING_SYMBOLS = re.compile(r"[^\w가-힣\s]+$")


def _jong(ch: str) -> int | None:
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28
    return None


def _last_letters(w: str) -> str:
    parts = w.split()
    token = parts[-1] if parts else ""
    return "".join(c for c in token if c.isascii() and c.isalpha())


def has_batchim(word: str) -> bool | None:
    """끝소리에 받침이 있는가. 판단 못 하면 None."""
    w = _TRAILING_SYMBOLS.sub("", word.rstrip())
    if not w:
        return None
    ch = w[-1]
    j = _jong(ch)
    if j is not None:
        return j != 0
    if ch in _DIGIT_JONG:
        return _DIGIT_JONG[ch]  # 0 은 십·백·천·만 모두 받침
    if ch.isascii() and ch.isalpha():
        letters = _last_letters(w)
        if letters.isupper() and len(letters) <= 6:
            return ch in _LETTER_NAME_BATCHIM
        return None  # 영어 단어는 발음을 확정할 수 없다 (Google · game)
    return None


def ends_with_rieul(word: str) -> bool:
    w = _TRAILING_SYMBOLS.sub("", word.rstrip())
    if not w:
        return False
    j = _jong(w[-1])
    if j is not None:
        return j == 8
    if w[-1] in _DIGIT_RIEUL:
        return True
    return w[-1].isascii() and w[-1].isalpha() and _last_letters(w).isupper() and w[-1] in _LETTER_NAME_RIEUL


def fit(word: str, particle: str) -> str | None:
    """``word`` 뒤에 맞는 ``particle`` 형태. 받침과 무관한 조사는 그대로. 받침을 모르면 None (기권)."""
    if not particle:
        return particle
    if particle not in _CONS_FORM and particle not in _VOW_FORM:
        return particle
    cons = particle if particle in _CONS_FORM else _VOW_FORM[particle]
    vow = _CONS_FORM[cons]
    b = has_batchim(word)
    if b is None:
        return None
    if cons.startswith("으로") or cons == "으론":
        return vow if (not b or ends_with_rieul(word)) else cons
    return cons if b else vow


def _form_ok(stem: str, particle: str) -> bool:
    """잘라 낸 조사가 앞말 받침과 맞는 형태인가 — 맞지 않으면 그 자리는 조사가 아니다."""
    if particle not in _CONS_FORM and particle not in _VOW_FORM:
        return True
    want = fit(stem, particle)
    return want is None or want == particle


@dataclass(frozen=True)
class Split:
    core: str          # 바꿀 말
    tail: str          # 그대로 둘 꼬리 (복수 「들」 + 조사·어미 + 끝 기호). 없으면 ""
    particle: str      # tail 안의 조사·어미 부분 (「들은」 → 「은」)
    symbols: str = ""  # 끝 문장부호·이모지


def split_tail(text: str, *, copula_in: bool = False, loc: bool = False) -> Split:
    """스팬 문자열 → (바꿀 말, 꼬리). 마지막 어절 끝에서 조사·어미를 긴 것부터 떼어 본다.

    ``copula_in`` — 서술격 관형형 「인」(「쉰여덟인 지금」)도 꼬리로 본다 (나이 표현에서만).
    ``loc`` — 위치 표현의 구어 축약 「서」(「서울서」)도 꼬리로 본다.
    """
    t = text.rstrip()
    m = _TRAILING_SYMBOLS.search(t)
    symbols = m.group(0) if m else ""
    t = t[: len(t) - len(symbols)] if symbols else t
    head, sep, last = t.rpartition(" ")
    prefix = head + sep
    if last in _NOUN_ENDS_WITH_PARTICLE or last.endswith(_NOUN_SUFFIX_NOT_PARTICLE):
        return Split(t, symbols, "", symbols)
    if copula_in and len(last) > 1 and last.endswith("인") and not last.endswith(("노인", "부인", "주인")):
        return Split(prefix + last[:-1], "인" + symbols, "인", symbols)
    for p in (_ALL_LOC if loc else _ALL):
        if len(last) > len(p) and last.endswith(p):
            stem = last[: -len(p)]
            plural = ""
            if stem.endswith(_PLURAL) and len(stem) > 1 and not stem.endswith(_DEUL_NOUNS):
                plural, stem = _PLURAL, stem[:-1]
            if (stem + plural + p) in _NOUN_ENDS_WITH_PARTICLE:
                continue
            if stem in _NOUN_ENDS_WITH_PARTICLE or _form_ok(stem + plural, p):
                return Split(prefix + stem, plural + p + symbols, p, symbols)
    if last.endswith(_PLURAL) and len(last) > 1 and not last.endswith(_DEUL_NOUNS):
        return Split(prefix + last[:-1], _PLURAL + symbols, "", symbols)
    return Split(t, symbols, "", symbols)


_LEADING = re.compile("^(" + "|".join(map(re.escape, _ALL)) + r")(?![가-힣])")


def leading_particle(after: str) -> str:
    """스팬 **뒤** 글자가 조사로 시작하면 그 조사 (라벨러가 조사를 빼고 그은 경우). 뒤가 한글이 아니면 끝으로 본다."""
    m = _LEADING.match(after)
    return m.group(1) if m else ""


def continues_outside(after: str) -> bool:
    """스팬이 어절 중간에서 끝났는가 — 바로 뒤가 한글이면 어절이 밖으로 이어진다 (「[서른셋이]야」)."""
    return bool(after) and ("가" <= after[0] <= "힣" or after[0].isalnum())  # 「[서른셋]th」 도 이어진 것


def replace(text: str, new_core: str, after: str = "", *, copula_in: bool = False, loc: bool = False,
            hada: bool = False) -> str | None:
    """스팬 ``text`` 를 ``new_core`` 로 바꾼 스팬 문자열. 조사를 맞출 수 없으면 None (그 후보는 못 쓴다).

    - 스팬 안 꼬리: 조사를 새 말에 맞춰 다시 붙인다. 어절이 밖으로 이어지는데 형태가 바뀌어야 하면 None
    - 스팬 안에 조사가 없고 밖(``after``)에 짝 조사가 있으면: 밖은 못 고치므로 끝소리가 맞을 때만 허용
    """
    sp = split_tail(text, copula_in=copula_in, loc=loc)
    tail_wo_symbols = sp.tail[: len(sp.tail) - len(sp.symbols)] if sp.symbols else sp.tail
    if tail_wo_symbols:
        plural = tail_wo_symbols[: len(tail_wo_symbols) - len(sp.particle)] if sp.particle else tail_wo_symbols
        new_particle = fit(new_core + plural, sp.particle) if sp.particle else ""
        if new_particle is None:
            return None
        if continues_outside(after) and new_particle != sp.particle:
            return None  # 「[서른셋이]야」 → 「30대가야」 ✗ — 밖으로 이어진 어절은 못 고친다
        return new_core + plural + new_particle + sp.symbols
    if continues_outside(after) and not hada:  # 「하다」 자리(「출근하고」)는 호출부가 확인했다
        outside = leading_particle(after)
        if not outside:
            return None  # 스팬 뒤에 모르는 말이 붙어 있다 — 기권
        if outside in _CONS_FORM or outside in _VOW_FORM:
            return new_core + sp.symbols if fit(new_core, outside) == outside else None
    return new_core + sp.symbols


def fits_outside(new_core: str, after: str) -> bool:
    """스팬 밖 조사와 끝소리가 맞는가 (조사가 없거나 받침 무관 조사면 True)."""
    outside = leading_particle(after)
    if not outside or (outside not in _CONS_FORM and outside not in _VOW_FORM):
        return True
    return fit(new_core, outside) == outside
