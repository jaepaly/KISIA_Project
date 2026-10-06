"""바꿔 쓰기 후보 — 단서 구간을 덜 구체적인 말로 바꾸고, 뒤 조사를 새 말에 맞춘다 (stage2-io ``Rewrite``).

원칙 (exp15 표본 검토 · Codex 검토로 다듬었다)
1. **확신 못 하면 기권한다** — 후보가 없으면 화면은 「이 표현이 단서입니다」만 보여 준다. 뜻이 바뀌거나 어색한 후보보다 낫다
2. **지우기보다 넓히기, 관계는 그대로** — 지명은 상위 행정구역(역삼동 → 강남구 → 서울), 역은 「분당구의 한 역」(「역 근처」
   「3번 출구」 같은 관계를 남긴다), 나이는 5년·10년 단위(마흔여덟 → 40대 후반 → 40대)
3. **일반어는 표현 안 단어가 정확히 그 말일 때만** — 배우자 호칭 → 가족, 몇째 → 아이, 버스 번호 → 버스, 직업명 → 직군 …
   단어 하나만 바꿨는데 **다른 식별자(지명 · 숫자 · 관계어)가 남으면 기권**한다 (「대전 유성구 회사」 → 「대전 유성구 직장」 ✗)
4. **조사는 새 말에 맞춘다** (``josa``) — 맞출 수 없으면 그 후보는 버린다
5. **자리에 맞는 말만** — 「하다」 자리(출근**하고**)에는 「하다」가 붙는 말만, 따옴표 안의 이름(‘수원시’라는 글자)은 바꾸지 않는다

모델 호출 없음.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from . import josa

# ── 지역 사전 ────────────────────────────────────────────────────────────

_SIDO_SHORT = {  # 넓힌 결과로 보여 줄 시도 이름
    "서울특별시": "서울", "전남광주통합특별시": "광주·전남", "부산광역시": "부산", "대구광역시": "대구",
    "인천광역시": "인천", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기도",
    "강원특별자치도": "강원도", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북",
    "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주",
}
# 사람들이 쓰는 시도 약칭 → 정식 이름 (k_engine._Index.SIDO_SHORT 와 같게). 「광주」는 광주광역시·경기 광주시 둘이다
_SIDO_ALIASES = {
    "서울특별시": ("서울", "서울시"), "전남광주통합특별시": ("광주", "광주광역시", "전남", "전라남도"),
    "부산광역시": ("부산", "부산시"), "대구광역시": ("대구", "대구시"), "인천광역시": ("인천", "인천시"),
    "대전광역시": ("대전", "대전시"), "울산광역시": ("울산", "울산시"), "세종특별자치시": ("세종", "세종시"),
    "경기도": ("경기",), "강원특별자치도": ("강원", "강원도"), "충청북도": ("충북",), "충청남도": ("충남",),
    "전북특별자치도": ("전북", "전라북도"), "경상북도": ("경북",), "경상남도": ("경남",), "제주특별자치도": ("제주", "제주도"),
}

_dictionary = None
_short_codes: dict[str, list[str]] | None = None


def _dict():
    global _dictionary
    if _dictionary is None:
        from kopl.c2_specificity.engine import RegionDictionary

        _dictionary = RegionDictionary()
    return _dictionary


def _short_index() -> dict[str, list[str]]:
    global _short_codes
    if _short_codes is None:
        idx: dict[str, list[str]] = {}
        for code, r in _dict().regions.items():
            name = r["name"]
            if r["level"] == "sido":
                for short in _SIDO_ALIASES.get(name, ()):
                    idx.setdefault(short, []).append(code)
            elif r["level"] == "sigungu" and " " not in name and len(name) >= 3 and name[-1] in "시군구":
                idx.setdefault(name[:-1], []).append(code)
        _short_codes = idx
    return _short_codes


def _region_codes(text: str) -> list[str]:
    """약칭과 정식 이름을 둘 다 본다 — 「안동」은 안동시와 김해시 안동 둘 다 후보라 상위가 갈려 넓히지 않는다(기권).

    약칭만 보면 「울산 일산동」의 일산동이 고양시가 되고, 정식 이름만 보면 「안동」이 김해시가 된다 (Codex 검토 10/5).
    """
    t = unicodedata.normalize("NFC", text).strip()
    codes = list(_dict().resolve_info(t).get("codes") or [])
    return sorted(set(codes) | set(_short_index().get(t, ())))


def _is_place_word(word: str) -> bool:
    """지명으로 읽히는 말인가 (잔존 식별자 검사용)."""
    w = josa.split_tail(word, loc=True).core
    return len(w) >= 2 and bool(_region_codes(w))


def _starts_with_place(word: str) -> bool:
    """「원주시청 · 서울역 · 수원화성」처럼 지명으로 시작하는 말 (시도·시군구 약칭, 2글자 이상)."""
    idx = _short_index()
    return any(word.startswith(k) and len(k) >= 2 for k in (word[:n] for n in range(2, min(len(word), 5) + 1)) if k in idx)


def _neighbor_place(word: str) -> bool:
    """스팬 바로 앞 말이 지명인가 — 「일산」(일산동구·일산서구)처럼 방위 구의 앞부분만 쓰는 말까지 본다."""
    w = josa.split_tail(word, loc=True).core
    return _is_place_word(w) or _starts_with_place(w) or (
        len(w) >= 2 and any(_region_codes(w + d) for d in ("동구", "서구", "남구", "북구")))


def _ladder_from_full(toks: list[str], seen: set[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for n in range(len(toks) - 1, 0, -1):
        name = _SIDO_SHORT.get(toks[n - 1], toks[n - 1]) if n == 1 else toks[n - 1]
        if name not in seen:
            out.append((name, "시도까지만" if n == 1 else "시군구까지만"))
            seen.add(name)
    return out


def _region_ladder(core: str) -> list[tuple[str, str]]:
    """지명 → [(더 넓은 이름, 설명)]. 동 → 시군구 → 시도 (정식 전체 이름의 상위 단계). 동명이 여러 곳이면 []."""
    codes = _region_codes(core)
    if not codes:
        return []
    d = _dict()
    fulls = [(d.regions[c].get("full_name") or d.regions[c]["name"]).split() for c in codes]
    if len({tuple(x[:-1]) for x in fulls}) != 1:
        return []
    return _ladder_from_full(fulls[0], {core})


def _station_ladder(core: str) -> list[tuple[str, str]]:
    """역 → 「강남구의 한 역」 「서울의 한 역」 — 역이라는 관계(근처 · 출구 · 내리다)를 남기고 위치만 넓힌다."""
    from kopl.c2_specificity.facilities import station_lookup

    if not core.endswith("역"):
        return []  # 「체육공원」 같은 시설을 같은 이름의 역으로 오인하지 않게
    hit = station_lookup(core)
    if hit is None or hit.ambiguous or not hit.emd:
        return []
    r = _dict().regions.get(hit.emd)
    if not r:
        return []
    toks = (r.get("full_name") or r["name"]).split()
    return [(f"{name}의 한 역", "역 이름 대신 " + why.replace("까지만", "")) for name, why in _ladder_from_full(toks, {core})]


# ── 나이 ────────────────────────────────────────────────────────────────

_NATIVE_TENS = {"열": 10, "스물": 20, "스무": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60, "일흔": 70, "여든": 80, "아흔": 90}
_NATIVE_UNITS = {"하나": 1, "한": 1, "둘": 2, "두": 2, "셋": 3, "세": 3, "넷": 4, "네": 4, "다섯": 5, "여섯": 6,
                 "일곱": 7, "여덟": 8, "아홉": 9}
_SINO = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_AGE_NATIVE = re.compile(r"(열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)(하나|다섯|여섯|일곱|여덟|아홉|한|둘|두|셋|세|넷|네)?(?:\s*(?:살|세))?")
_AGE_SINO = re.compile(r"([이삼사오육칠팔구])?십([일이삼사오육칠팔구])?(?:\s*(?:살|세))?")
_AGE_ARABIC = re.compile(r"(\d{1,2})\s*(?:살|세)?")


def _age_value(core: str) -> int | None:
    """나이 표현 **전체**를 읽는다 — 다 읽지 못하면 None (「서른셋 무렵」 같은 덧말이 있으면 기권)."""
    t = core.strip()
    m = _AGE_NATIVE.fullmatch(t)
    if m:
        return _NATIVE_TENS[m.group(1)] + _NATIVE_UNITS.get(m.group(2) or "", 0)
    m = _AGE_SINO.fullmatch(t)
    if m:
        return _SINO.get(m.group(1) or "", 1) * 10 + _SINO.get(m.group(2) or "", 0)
    m = _AGE_ARABIC.fullmatch(t)
    if m:
        return int(m.group(1))
    return None


def _age_ladder(core: str) -> list[tuple[str, str]]:
    age = _age_value(core)
    if age is None or age < 10 or age >= 100:
        return []
    d = age // 10 * 10
    out = [(f"{d}대 {'초반' if age % 10 < 5 else '후반'}", "5년 단위로"), (f"{d}대", "10년 단위로")]
    if 40 <= age < 60:
        out.append(("중년", "세대로만"))
    return out


# ── 일반어 — 확실한 경우만 ───────────────────────────────────────────────
_B = r"(?<![가-힣])"   # 단어 앞 경계
_E = r"(?![가-힣])"    # 단어 뒤 경계 (조사는 split_tail 로 이미 떼었다)
# (유형들, 단어 패턴, [(바꿀 말, 설명)])
_TOKEN_RULES: list[tuple[tuple[str, ...], re.Pattern, list[tuple[str, str]]]] = [
    (("SEX", "FAM"), re.compile(_B + r"(?:남편|신랑|아내|와이프|집사람|영감|할멈)" + _E),
     [("가족", "배우자 지움"), ("식구", "배우자 지움")]),
    (("FAM",), re.compile(_B + r"(?:(?:큰|작은|막내|외)?(?:아들|딸)애?|첫째|둘째|셋째|막내|큰애|작은애|쌍둥이)" + _E
                          + r"(?!\s*(?:딸내미|딸|아들|동생|여동생|남동생|아이|애|손주|손자|손녀|조카|형|누나|언니|오빠))"),
     [("아이", "몇째·성별 지움")]),
    (("FAM",), re.compile(_B + r"(?:손주|손자|손녀)" + _E), [("아이", "관계 지움")]),
    (("SEX", "FAM"), re.compile(_B + r"(?:처남|시누이?)" + _E), [("가족", "관계 지움")]),  # 반드시 가족이다 — 「지인」은 뜻이 바뀐다 (#304 리뷰)
    (("SEX", "FAM"), re.compile(_B + r"(?:언니|누나|오빠|형님)" + _E), [("지인", "관계 지움")]),  # 남을 부르는 말로도 쓴다
    (("COMMUTE",), re.compile(_B + r"(?:\d+\s*번\s*버스|마을버스|광역버스|시내버스|통근버스|셔틀버스)" + _E),
     [("버스", "노선 지움")]),
    (("COMMUTE",), re.compile(r"\d+\s*호선(?:\s*지하철)?" + _E), [("지하철", "노선 지움")]),
    (("COMMUTE",), re.compile(_B + r"(?:출근길|퇴근길|통근길)$"), [("오가는 길", "통근 지움")]),
    (("INCOME",), re.compile(_B + r"(?:월급|연봉|연금|알바비|급여|수당)" + _E), [("수입", "종류 지움")]),
    (("REL_WORK",), re.compile(_B + r"(?:회사|사무실|공장)" + _E), [("직장", "직장 종류 지움")]),
]
# 관계어 앞 수식이 관계를 특정하면 바꾸지 않는다 — 「친정 언니 → 친정 지인」 ✗
_KIN_CONTEXT = re.compile(r"친정|시댁|처가|외가|본가|시가")
# 직업명 → 직군. 표현 **전체**가 직업명일 때만 (「간호사」 ○ · 「분기 부가세」 ✗)
_OCCUPATIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?:간호|약|의|치과의|물리치료|방사선)사|간호조무사|요양보호사"), "의료직"),
    (re.compile(r"(?:초등|중등|고등|유치원)?\s*교사|선생님?|강사|교수"), "교육직"),
    (re.compile(r"회사원|직장인|사무원|공무원|은행원"), "사무직"),
    (re.compile(r"(?:택시|버스|화물|트럭)?\s*기사|운전사|배달원|택배기사"), "운수업"),
    (re.compile(r"자영업자|점주|가게 주인"), "자영업"),
    (re.compile(r"농부|농민|어부|어민"), "농어업"),
    (re.compile(r"(?:생산|현장|공장)\s*(?:직|직원|노동자)|용접공|정비사"), "생산직"),
]
# 시설 이름 끝의 일반 명사 — 「한라수목원 → 한 수목원」 (「동네 수목원」은 생활권이라는 근거 없는 뜻이 생긴다)
_FACILITY_HEADS = ("수목원", "도서관", "운동장", "터미널", "주민센터", "경로당", "산책로", "유원지", "해수욕장",
                   "공원", "시장", "병원", "마트", "구청", "시청", "보건소", "회관", "성당", "교회", "카페")
_PROXIMITY = re.compile(r"^(?:근처|인근|부근|주변|가까이|옆|앞)")
_HADA_AFTER = re.compile(r"^\s?(?:하[고는면다기던려며]?|한|할|해[서요도]?|했[다고는어지]?|합니다|함)(?![가-힣])")
# 「하다」 자리 — 표현마다 뜻이 맞는 말 하나 (퇴근은 「외출」이 아니라 「귀가」)
_HADA_MAP = {"출근": "외출", "등교": "외출", "통근": "이동", "퇴근": "귀가", "하교": "귀가",
             "야근": "근무", "당직": "근무", "교대근무": "근무"}
# 지명이 기관·표지·행사 이름의 일부일 때 — 시도까지 넓히면 다른 기관처럼 읽힌다 (「경북 보건소」 「충북 행사」)
_INSTITUTION_NEXT = {"보건소", "보건지소", "시청", "군청", "구청", "도청", "주민센터", "행정복지센터", "경찰서", "소방서",
                     "우체국", "농협", "안내판", "표지판", "행사", "축제", "터미널", "버스", "시내버스", "교육청", "법원"}
# 넓힌 지명 뒤에 오면 어색한 말 — 시도까지는 넓히지 않는다 (「서울 쪽 고시촌」 「울산 읍내」)
_SCOPE_NEXT = {"쪽", "방면", "읍내", "시내", "외곽", "토박이"}
# 회사 뒤 물리적 장소 — 「직장 옆자리」는 어색하다
_PLACE_NEXT = {"옆자리", "자리", "건물", "옥상", "식당", "주차장", "앞", "근처", "로비", "엘리베이터"}
# 역 이름 뒤에 와도 되는 말 — 그 밖의 명사를 꾸미는 역 이름(「OO역 상가거리」)은 넓히지 않는다
_STATION_OK_NEXT = {"근처", "인근", "부근", "앞", "뒤", "옆", "쪽", "출구", "방향", "주변"}
# 수 뒤 단위 — 나이가 아니라 기간·횟수 (exp06 rules._DURATION_FOLLOWERS 와 같은 목록 · 뒤가 조사·끝일 때만)
_UNIT_AFTER = re.compile(
    r"^\s*(?:번|개|명|분|마리|원|장|그릇|잔|해|날|년|달|주|일|시간|가지|곳|군데|권|벌|채|그루|송이|칸|층|평|켤레|통)"
    r"(?=$|[^가-힣]|(?:보다|동안|이나|나|만|도|은|는|이|가|을|를|에|째|쯤|씩|간|의|하고|까지|부터)(?:$|[^가-힣]))")
_KIN_NOUNS = {"딸내미", "딸", "아들", "동생", "여동생", "남동생", "아이", "애", "손주", "손자", "손녀", "조카", "형", "누나", "언니", "오빠"}
_QUOTES = "‘’'\"“”「」『』《》<>"


def _residual_identifier(rest: str) -> bool:
    """단어 하나를 바꾼 뒤 남은 말에 다른 식별자가 있는가 — 지명 · 숫자 · 다른 관계어."""
    if re.search(r"\d", rest):
        return True
    for raw in rest.split():
        w = josa.split_tail(raw, loc=True).core  # 「딸과」 → 「딸」
        if _is_place_word(w) or _KIN_CONTEXT.search(w):
            return True
        if any(rx.search(w) for _, rx, _ in _TOKEN_RULES):
            return True
    return False


def _generic(stype: str, core: str, hada: bool, particle: str) -> list[tuple[str, str, bool]]:
    """확실한 일반어 → [(바꿀 말, 설명, 남은 말이 있음)]. 없으면 []."""
    if hada:
        return []  # 「퇴근했다 → 귀가했다」 — 활동을 바꾸면 사실이 바뀔 수 있다 (Codex 3차). 화면은 단서 표시만
    out: list[tuple[str, str, bool]] = []
    for types, rx, items in _TOKEN_RULES:
        if stype not in types:
            continue
        m = rx.search(core)
        if not m:
            continue
        rest = (core[: m.start()] + " " + core[m.end():]).strip()
        if rest and _residual_identifier(rest):
            return []  # 다른 식별자가 남는다 — 기권
        for word, note in items:
            out.append((core[: m.start()] + word + core[m.end():], note, bool(rest)))
        break
    if stype == "JOB":
        for rx, group in _OCCUPATIONS:
            if rx.fullmatch(core.strip()):
                out.append((f"{group} 종사자", "직업을 직군으로", False))  # 사람을 가리킨다 — 「간호사를 만났다」
                break
    if stype == "LOC_FACILITY":
        head = next((h for h in _FACILITY_HEADS if core.endswith(h) and core != h), None)
        if head and not _residual_identifier(core[: -len(head)]):
            out.append((f"한 {head}", "시설 이름 지움", False))  # 「근처 X」는 원문에 없는 가까움을 더한다
    return out


def _first_word(text: str) -> str:
    s = text.lstrip()
    w = re.split(r"[\s,.!?…]", s, maxsplit=1)[0] if s else ""
    return josa.split_tail(w).core if w else ""


def _last_word(text: str) -> str:
    s = text.rstrip()
    w = re.split(r"[\s,.!?…]", s)[-1] if s else ""
    return josa.split_tail(w).core if w else ""


# ── 공개 API ────────────────────────────────────────────────────────────

def suggest(span: Mapping[str, Any], channel_text: str | None = None, *, limit: int = 3) -> list[dict[str, Any]]:
    """스팬 하나의 바꿔 쓰기 후보 → [{suggestion, core, note, kind, residual}] (넓히기 먼저). 확신이 없으면 [].

    ``suggestion`` 은 스팬 구간을 대신할 문자열(조사 맞춤 포함). ``channel_text`` 가 있으면 스팬 앞뒤 글자로
    밖에 붙은 조사 · 「하다」 자리 · 따옴표 · 앞뒤 말 중복을 확인한다.
    """
    text = unicodedata.normalize("NFC", str(span.get("text", "")))
    stype = str(span.get("type", ""))
    after = before = ""
    if channel_text is not None and span.get("end") is not None:
        after = channel_text[int(span["end"]):]
        before = channel_text[: int(span.get("start", 0))]
    left, right = before.rstrip()[-1:], after.lstrip()[:1]
    if (left and left in _QUOTES) or (right and right in _QUOTES):
        return []  # 인용된 이름은 바꾸지 않는다 — 「‘수원시’라는 글자」
    copula_in, loc = stype == "AGE", stype in ("LOC_ADMIN", "LOC_FACILITY")
    sp = josa.split_tail(text, copula_in=copula_in, loc=loc)
    core = sp.core
    has_tail = bool(sp.tail[: len(sp.tail) - len(sp.symbols)] if sp.symbols else sp.tail)
    hada_slot = not has_tail and bool(_HADA_AFTER.match(after))

    ladder: list[tuple[str, str]] = []
    if not hada_slot:
        if stype == "LOC_ADMIN":
            ladder = _region_ladder(core)
        elif stype == "LOC_FACILITY":
            ladder = _station_ladder(core)
        elif stype == "AGE":
            ladder = _age_ladder(core)
    cands = [(w, n, "widen", True) for w, n in ladder]
    cands += [(w, n, "generic", rest) for w, n, rest in _generic(stype, core, hada_slot, sp.particle)]

    nxt, prv = _first_word(after), _last_word(before)
    if stype == "AGE" and (re.match(r"^\s*(?:살|세)(?![가-힣])", after) or re.match(r"^\s*(?:나\s*)?먹", after)
                           or sp.particle in ("이나", "나") and re.match(r"^\s*먹", after)):
        return []  # 「삼십구 살 때」(단위가 밖) · 「서른셋 먹고도」(나이를 먹다) — 구간 밖을 고쳐야 자연스럽다
    if stype == "AGE" and not sp.particle and _UNIT_AFTER.match(after):
        return []  # 「서른 해보다」 「쉰 날」 — 뒤에 단위가 오면 나이가 아니라 수량이다 (1단 규칙 오탐 · 인스턴스 10/5)
    window = before[-20:]
    place_before = any(_is_place_word(w) or _starts_with_place(w) for w in re.split(r"[\s,.!?…]+", window) if w)
    if stype == "FAM" and nxt in _KIN_NOUNS:
        return []  # 「막내 동생」 — 몇째가 뒤 관계어를 꾸민다
    modifier_slot = not has_tail and bool(re.match(r"^\s+[가-힣]", after)) and not _HADA_AFTER.match(after)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for word, note, kind, residual in cands:
        if word == core or word in seen:
            continue
        if stype == "LOC_ADMIN" and kind == "widen":
            if nxt in _INSTITUTION_NEXT:
                continue  # 지명이 기관·표지 이름의 일부
            if place_before:
                continue  # 앞에 이미 지명이 있다 — 「원주시청 뒤편 원주시 근린공원」
            if note == "시도까지만" and nxt in _SCOPE_NEXT:
                continue  # 「서울 쪽 고시촌」 「울산 읍내」
        if stype == "LOC_FACILITY" and kind == "widen" and not has_tail and nxt and nxt not in _STATION_OK_NEXT \
                and not re.match(r"\d+\s*번", after.lstrip()):
            continue  # 「OO역 상가거리」 — 역 이름이 다른 명사를 꾸민다
        if stype == "REL_WORK" and nxt in _PLACE_NEXT:
            continue  # 「회사 옆자리」 → 「직장 옆자리」 ✗
        if word == "중년" and "나이" in after[:12]:
            continue  # 「중년이라는 나이」
        if (nxt and word.split()[-1] == nxt) or (prv and word.split()[0] == prv):
            continue  # 앞뒤 말과 겹친다 — 「근처 근처 공원」
        if word.startswith("근처") and (_PROXIMITY.match(after.lstrip()) or prv in ("근처", "인근")):
            continue  # 「근처 역 인근」
        if modifier_slot and "오가는 길" in word:
            continue  # 「출근길 자전거」 → 「오가는 길 자전거」 — 관형절 일반어는 꾸미는 자리에 어색하다
        new = josa.replace(text, word, after, copula_in=copula_in, loc=loc, hada=hada_slot)
        if new is None or new == text:
            continue
        if kind == "widen" and stype == "LOC_ADMIN" and re.match(re.escape(word) + r"도(?![가-힣])", new) \
                and (word in _SIDO_SHORT.values() or word in {a for al in _SIDO_ALIASES.values() for a in al})                 and not word.endswith("도"):
            continue  # 「전주도 → 전북도」 — 조사 「도」가 붙어 도 이름(전라북도)처럼 읽힌다
        words = new.split()
        if any(a == b or josa.split_tail(b).core == a for a, b in zip(words, words[1:])):
            continue  # 「아이 아이가」
        seen.add(word)
        if prv and stype in ("LOC_FACILITY", "COMMUTE") and _neighbor_place(prv):
            # 장소·통근 단서만 — 「수영 [강사로]」의 수영은 운동이다 (Codex 10/6)
            residual = True  # 바로 앞 지명이 남는다 — 「일산 [한 공원]」은 단서가 약해질 뿐 사라지지 않는다 (#304 리뷰)
        out.append({"suggestion": new, "core": word, "note": note, "kind": kind, "residual": residual})
        if len(out) >= limit:
            break
    return out


def rewrites_for(posts: Sequence[Mapping[str, Any]], *, levels: tuple[str, ...] = ("explicit",),
                 limit: int = 3) -> list[dict[str, Any]]:
    """글 목록 → stage2-io ``rewrites`` 배열. 본인(self) 스팬 중 ``levels`` 만 (기본: 명시 단서 — 추천 엔진 리라이트와 같은 대상).

    같은 span_id 로 후보를 여러 개 낸다 (계약의 suggestion 이 단수라 항목을 나눈다). 넓히기와 남은 말이 있는 단어 교체는
    단서가 일부 남으므로 ``residual_risk: partial``, 표현 전체를 일반어로 바꾼 것만 ``none``.
    """
    out: list[dict[str, Any]] = []
    for p in posts:
        texts = p.get("texts") or {}
        for s in p.get("spans") or []:
            if s.get("subject") != "self" or s.get("level") not in levels:
                continue
            for c in suggest(s, texts.get(s.get("text_id")), limit=limit):
                out.append({"post_id": p["post_id"], "span_id": s["span_id"], "suggestion": c["suggestion"][:200],
                            "semantic_similarity": None,
                            "residual_risk": "partial" if c["residual"] else "none"})
    return out
