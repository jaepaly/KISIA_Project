"""조건 목록 전체 → 후보 모집단 k (#302).

한 사용자의 **모든 글**에서 나온 condition 을 한꺼번에 받아 k 를 낸다. C-specificity.md §4 의 네 규칙을 그대로 따른다.

1. 축 안에서는 곱하지 않는다 — 위치는 **교집합**, 나머지 축은 가장 구체적인 단서 하나
2. 지역 × 연령 × 성별은 주민등록 교차표에서 **직접** 조회한다
3. 직업·가족·통근·소득은 ``q = 1 − c·(1 − p)`` 를 ``q ** α`` 로 감쇠해 곱한다 (계약 step ``ratio_damped``)
4. k < 1 이면 1 로 막고 ``floor_applied`` 를 남긴다

위치를 교집합하는 이유 — 데모 체험 피드백 「여러 글을 써도 엮어서 좁혀지지 않는다」의 원인이 「가장 좁은 지명 하나만 쓴다」였다.
글 A 의 「강남구」와 글 B 의 「선릉역 근처」는 포함 관계가 아니라 **겹치는 동네**를 가리킨다. 둘 다 사실이면 사는 곳은 그 겹침 안이다.

``risk`` · ``risk_by_axis`` 는 기존 ``engine.risk_total`` 그대로다 — 이 모듈은 k 만 새로 계산한다 (exp10 · exp11 · 추천 엔진 수치 유지).
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from .dicts import pop_lookup
from .engine import (
    RegionDictionary,
    _get_default_dictionary,
    _get_default_population,
    classify_k,
    risk_by_axis,
    risk_total,
)
from .facilities import DEFAULT_STATIONS_PATH
from .model import AGE_BAND_VALUES

ENGINE_VERSION = "c2-k-0.1.0"
REFERENCE_YEAR = 2026  # 「88년생」 → 나이. 측정 연도와 맞춘다
STRONG_CONFIDENCE = 0.8  # explicit 1.0 · implicit 0.8 은 직접 좁힌다. 그보다 낮으면 비율로만 반영
DEFAULT_PRIORS_PATH = Path(__file__).resolve().parents[3] / "data" / "dict" / "priors" / "priors.json"
RATIO_AXES = ("occupation", "family", "commute", "income")
_BANDS = sorted((b for b in AGE_BAND_VALUES if b != "100+"), key=lambda b: int(b.split("-")[0])) + ["100+"]


# ── 사전 ────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_priors(path: str = str(DEFAULT_PRIORS_PATH)) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    alpha = float(doc["alpha"])
    if not 0 < alpha <= 1:
        raise ValueError("priors alpha 는 (0, 1]")
    for axis in RATIO_AXES:
        for res, item in doc["axes"][axis].items():
            if not 0 < float(item["p"]) <= 1:
                raise ValueError(f"priors {axis}.{res}.p 는 (0, 1]")
    return doc


_JOSA_RE = re.compile(r"(?:에서는|에서도|에서|으로는|으로|로는|로|에는|에도|에|까지|부터|이랑|랑|하고|은|는|이|가|을|를|도|의|쪽|근처|앞|옆)$")
_STEM_SUFFIX_RE = re.compile(r"(?:제?\d*(?:동|읍|면|가|리))$|(?:[시군구])$")


def _stem(name: str) -> str:
    """「송도1동 → 송도 · 일산동구 → 일산 · 덕진구 → 덕진 · 첨단2동 → 첨단」."""
    prev = None
    s = name
    while s != prev and len(s) > 2:
        prev = s
        s = _STEM_SUFFIX_RE.sub("", s)
    return s


_JOSA_SINGLE = set("이가은는을를도의")


def _candidates(t: str) -> list[tuple[str, bool]]:
    """(후보, 추정 허용) — 조사 뗀 꼴과 띄어쓰기 앞 토큰. 「신촌에서 → 신촌」 「세종 면 소재지로 → 세종」.

    한 글자 조사(이·가·은·는…)를 뗀 꼴은 이름 끝일 수 있다(「상하이 → 상하」). 그런 후보는 정식 이름·약칭·역으로
    정확히 맞을 때만 받고 어간·앞머리 추정에는 쓰지 않는다 (추정 허용 False).
    """
    out: list[tuple[str, bool]] = []
    for base in (t, t.split()[0] if " " in t else None):
        if not base:
            continue
        s, loose = base, True
        for _ in range(3):
            m = _JOSA_RE.search(s)
            if not m or len(s) - len(m.group(0)) < 2:
                break
            if m.group(0) in _JOSA_SINGLE:
                loose = False
            s = s[: m.start()].strip()
            out.append((s, loose))
        if base != t:
            out.append((base, True))
    seen: dict[str, bool] = {}
    for cand, loose in out:
        if cand != t:
            seen[cand] = seen.get(cand, True) and loose
    return list(seen.items())


def _station(t: str) -> str | None:
    from .facilities import station_lookup

    if "역" not in t:
        return None  # 「체육공원」 같은 시설을 같은 이름의 역(체육공원역)으로 오인하지 않게 — 「역」이 들어간 표현만
    for cand in (t,):
        hit = station_lookup(cand)
        if hit is not None and not hit.ambiguous and hit.emd:
            return hit.emd
    return None


class _Index:
    """읍면동 자손 · 역 둘레 · 약칭 색인. 사전 하나당 한 번 만든다."""

    # 사전 정식 이름 → 사람들이 실제로 쓰는 약칭 (사전 aliases 에 없다)
    SIDO_SHORT = {
        "서울특별시": ("서울", "서울시"),
        "전남광주통합특별시": ("광주", "광주광역시", "전남", "전라남도"),
        "부산광역시": ("부산", "부산시"),
        "대구광역시": ("대구", "대구시"),
        "인천광역시": ("인천", "인천시"),
        "대전광역시": ("대전", "대전시"),
        "울산광역시": ("울산", "울산시"),
        "세종특별자치시": ("세종", "세종시"),
        "경기도": ("경기",),
        "강원특별자치도": ("강원", "강원도"),
        "충청북도": ("충북",),
        "충청남도": ("충남",),
        "전북특별자치도": ("전북", "전라북도"),
        "경상북도": ("경북",),
        "경상남도": ("경남",),
        "제주특별자치도": ("제주", "제주도"),
    }

    def __init__(self, dictionary: RegionDictionary, population: Mapping[str, Any]) -> None:
        self.d = dictionary
        self.population = population
        regions = dictionary.regions
        self.emd_under: dict[str, set[str]] = defaultdict(set)
        for code, r in regions.items():
            if r["level"] != "emd":
                continue
            self.emd_under[code].add(code)
            parent = r.get("parent")
            seen: set[str] = set()
            while parent and parent not in seen:  # 구가 있는 시는 읍면동의 직계 부모가 구다 — 사슬 전부에 등록
                seen.add(parent)
                self.emd_under[parent].add(code)
                parent = regions.get(parent, {}).get("parent")
        # 구가 있는 시(천안시 → 동남구·서북구)는 사전에서 구의 부모가 시가 아니라 도로 이어진다 — 정식 전체 이름으로 한 번 더 잇는다
        by_full = {r.get("full_name"): c for c, r in regions.items() if r["level"] in ("sido", "sigungu") and r.get("full_name")}
        for code, r in regions.items():
            if r["level"] != "emd" or not r.get("full_name"):
                continue
            toks = r["full_name"].split()
            for n in range(1, len(toks)):
                anc = by_full.get(" ".join(toks[:n]))
                if anc:
                    self.emd_under[anc].add(code)
        self.all_emd = tuple(sorted(c for c in self.emd_under if regions[c]["level"] == "emd" and c in population))

        self.short: dict[str, list[str]] = defaultdict(list)
        by_name = {r["name"]: c for c, r in regions.items() if r["level"] == "sido"}
        for name, shorts in self.SIDO_SHORT.items():
            if name in by_name:
                for s in shorts:
                    self.short[s].append(by_name[name])
        for code, r in regions.items():
            name = r["name"]
            if r["level"] == "sigungu" and " " not in name and len(name) >= 3 and name[-1] in "시군구":
                self.short[name[:-1]].append(code)

        # 어간 — 행정구역 이름에서 숫자·「제」·끝의 시군구·동읍면가를 뗀 것. 사람들이 쓰는 「일산 · 송도 · 첨단 · 덕진 · 신촌」
        self.stem: dict[str, list[str]] = defaultdict(list)
        for code, r in regions.items():
            if r["level"] not in ("sigungu", "emd") or " " in r["name"]:
                continue
            stem = _stem(r["name"])
            if len(stem) >= 2 and stem != r["name"]:
                self.stem[stem].append(code)

        # 시군구 이름의 앞부분 — 「마산 → 마산합포구·마산회원구」 「일산 → 일산동구·일산서구」
        self.sigungu_head: dict[str, list[str]] = defaultdict(list)
        for code, r in regions.items():
            name = r["name"]
            if r["level"] == "sigungu" and " " not in name:
                for n in range(2, len(name) - 1):
                    self.sigungu_head[name[:n]].append(code)

        self._pop_cache: dict[tuple, int] = {}
        self.station_near: dict[str, set[str]] = defaultdict(set)
        try:
            stations = json.loads(Path(DEFAULT_STATIONS_PATH).read_text(encoding="utf-8"))["stations"]
        except FileNotFoundError:
            stations = []
        for st in stations:
            if st.get("ambiguous") or not st.get("emd"):
                continue
            self.station_near[st["emd"]].update(st.get("near") or [])

    def emds(self, code: str) -> set[str]:
        return {c for c in self.emd_under.get(code, ()) if c in self.population}

    def pop(self, codes: Iterable[str], sex: str | None = None, bands: Sequence[str] | None = None) -> int:
        """읍면동 집합 × 성별 × 연령 구간 인구 합. 같은 질의가 LOO 에서 수백 번 반복되므로 캐시한다."""
        key = (frozenset(codes), sex, tuple(bands) if bands else None)
        hit = self._pop_cache.get(key)
        if hit is None:
            hit = sum(pop_lookup(self.population, geo_code=c, sex=sex, age_bands=list(bands) if bands else None,
                                 default=0) or 0 for c in key[0])
            if len(self._pop_cache) > 50_000:
                self._pop_cache.clear()
            self._pop_cache[key] = hit
        return hit

    def _lookup(self, t: str) -> tuple[list[str], str]:
        # 시군구·시도 약칭과 같은 이름의 읍면동이 7개(성동·강동·남동·일산동·영동·안동·하동) 있다. 「안동」은 안동시일 수도
        # 김해시 안동일 수도 있어 한쪽으로 단정하지 않고 **둘 다** 후보로 둔다 — 한 동으로 좁히지도(k 과소) 엉뚱한 시로
        # 옮기지도 않는다. 「울산 일산동」처럼 앞 단어가 있으면 _resolve_tokens 의 교집합이 맞는 쪽을 고른다
        info = self.d.resolve_info(t)
        codes = list(info.get("codes") or [])
        if t in self.short:
            short = list(self.short[t])
            if codes and set(codes) != set(short):
                return sorted(set(codes) | set(short)), "short_alias_homonym"
            return short, "short_alias" if len(short) == 1 else "short_alias_homonym"
        if codes:
            return codes, str(info.get("resolution"))
        if t in self.short:
            codes = list(self.short[t])
            return codes, "short_alias" if len(codes) == 1 else "short_alias_homonym"
        return [], "not_found"

    def resolve_text(self, text: str, *, fuzzy: bool = True, facility: bool = False) -> tuple[set[str], str]:
        """지명 문자열 → 읍면동 집합. 동명이면 후보 전부의 합집합 (사는 곳은 그중 하나).

        정확한 이름 → 약칭 → (fuzzy) 조사 뗀 이름 → 어간 · 역 → 앞머리 순으로 찾는다. 장소 스팬(``facility``)은 역을
        어간보다 먼저, 지명 스팬은 어간을 먼저 본다 — 「일산」은 지명이면 일산동·서구, 장소면 일산역이다.
        ``how`` 가 어느 단계에서 찾았는지 알려 준다 — stem·prefix 는 추정이라 호출부가 신뢰도를 낮춘다.
        """
        t = unicodedata.normalize("NFC", text).strip()
        codes, how = self._lookup(t)
        if not codes and fuzzy and " " in t:
            multi = self._resolve_tokens(t, facility=facility)
            if multi is not None:
                return multi
        if not codes and fuzzy:
            cands = [(t, True), *_candidates(t)]
            for cand, loose in cands:
                codes, how = self._lookup(cand)
                if codes:
                    how = "josa"
                    break
                hit = _station(cand) if facility else None
                if hit is not None:
                    codes, how = [hit], "station"
                    break
                # 장소 스팬에는 동 어간을 쓰지 않는다 — 「탄천(하천) → 탄천면」 같은 오탐
                if loose and not facility and (cand in self.stem or cand in self.sigungu_head):
                    codes, how = sorted(set(self.stem.get(cand, ())) | set(self.sigungu_head.get(cand, ()))), "stem"
                    break
                hit = None if facility else _station(cand)
                if hit is not None:
                    codes, how = [hit], "station"
                    break
            else:
                for cand, loose in cands:
                    pre = self._prefix(cand) if loose else []
                    if pre:
                        codes, how = pre, "prefix"
                        break
        out: set[str] = set()
        for c in codes:
            out |= self.emds(c)
            if how == "station":
                out |= {n for n in self.station_near.get(c, ()) if n in self.population}
        return out, how

    def is_short_collision(self, text: str) -> bool:
        """「안동 · 안동에서」 — 시군구·시도 약칭과 같은 이름의 읍면동이 있어 한쪽으로 단정할 수 없는 말인가."""
        t = unicodedata.normalize("NFC", text).strip()
        for cand in [t, *(c for c, _ in _candidates(t))]:
            if cand in self.short:
                codes = set(self.d.resolve_info(cand).get("codes") or [])
                if codes and codes != set(self.short[cand]):
                    return True
        return False

    def _resolve_tokens(self, t: str, *, facility: bool) -> tuple[set[str], str] | None:
        """「수원 영통구에 · 대전 유성구 전민동」 — 단어마다 해석해 교집합. 첫 단어만 보면 수원 전체(44개 동)가 된다.

        해석되지 않는 단어(「쪽 · 근처 · 1번 출구」)는 건너뛴다. 앞 단어와 겹치지 않는 단어는 무시한다 —
        서로 다른 곳을 나열한 말일 수 있어 좁히지 않는다. ``how`` 는 마지막으로 좁힌 단어의 단계 (추정이면 추정).
        """
        cur: set[str] | None = None
        how = "not_found"
        for tok in t.split():
            got, h = self.resolve_text(tok, facility=facility)
            if not got:
                continue
            if cur is not None and h in ("stem", "prefix"):
                continue  # 뒤 단어의 어간·앞머리 추정은 쓰지 않는다 — 「서울 중앙」의 「중앙」이 관악구 중앙동 하나가 된다
            if cur is None:
                cur, how = got, h
            elif cur & got:
                cur, how = cur & got, h
        if cur is None:
            return None
        return cur, how

    def _prefix(self, t: str) -> list[str]:
        """「천안고속터미널 · 순천만 · 전주천」 — 앞머리가 시도·시군구 약칭인 장소. 가장 긴 앞머리 하나.

        읍면동 어간은 쓰지 않는다 — 「호수공원 → 호수동 · 중앙공원 → 중앙동 · 상하이 → 상하동」 같은 오탐이 난다.
        """
        for n in range(min(len(t) - 1, 6), 1, -1):
            head = t[:n]
            if head in self.short:
                return list(self.short[head])
        return []


@lru_cache(maxsize=4)
def _index_for(dictionary_id: int) -> _Index:  # pragma: no cover - 캐시 껍데기
    raise RuntimeError


_INDEX: _Index | None = None


def _default_index() -> _Index:
    global _INDEX
    if _INDEX is None:
        _INDEX = _Index(_get_default_dictionary(), _get_default_population())
    return _INDEX




# ── 해석 — 나이 · 성별 ──────────────────────────────────────────────────

_NATIVE_TENS = {"열": 10, "스물": 20, "스무": 20, "서른": 30, "마흔": 40, "쉰": 50,
                "예순": 60, "일흔": 70, "여든": 80, "아흔": 90}
_NATIVE_UNITS = {"한": 1, "하나": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4,
                 "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}
_SINO_DIGITS = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_NATIVE_RE = re.compile(r"(열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)\s*"
                        r"(하나|다섯|여섯|일곱|여덟|아홉|한|두|둘|세|셋|네|넷)?")
_NATIVE_UNIT_ONLY_RE = re.compile(r"(?<![가-힣])(하나|다섯|여섯|일곱|여덟|아홉|한|두|세|네)\s*(?:살|세)")
_SINO_RE = re.compile(r"([일이삼사오육칠팔구])?십([일이삼사오육칠팔구])?\s*(?:살|세)")
_ARABIC_RE = re.compile(r"(?<!\d)(\d{1,3})\s*(?:살|세)(?!\d)")
_BARE_NUMBER_RE = re.compile(r"([1-9][0-9]?)\s*(?:에는|에|때|입니다|이에요|이고|인데|이야|이지|이라|임|은|는|이|가|도|만|이었다|였다)?")
_BIRTH_RE = re.compile(r"(?<!\d)(\d{4}|\d{2})\s*년생")
_MAN_RE = re.compile(r"만\s*\d|만\s*(?:열|스물|서른|마흔|쉰|예순|일흔|여든|아흔)")
_DECADE_RE = re.compile(r"(?<!\d)(\d{1,2})0\s*대")
_RANGE_RE = re.compile(r"(\d{1,3})\s*[~∼\-]\s*(\d{1,3})\s*(?:살|세)")
_NATIVE_DECADE_RE = re.compile(r"(스물|서른|마흔|쉰|예순|일흔|여든|아흔)\s*(?:대|줄)")
_MAX_TWO_DIGIT_YEAR_AGE = 95  # 「27년생」 → 1927 년생 99세? 2027 년생? — 둘 다 이상하면 해석하지 않는다


def band_of(age: int) -> str | None:
    if age < 0:
        return None
    if age >= 100:
        return "100+"
    lo = (age // 5) * 5
    band = f"{lo}-{lo + 4}"
    return band if band in AGE_BAND_VALUES else None


def _bands_for_ages(ages: Iterable[int]) -> list[str]:
    out = {b for a in ages if (b := band_of(a))}
    return [b for b in _BANDS if b in out]


def _exact_age(text: str) -> tuple[int, bool] | None:
    """(나이, 만 나이 확정 여부). 해석 못 하면 None."""
    man = bool(_MAN_RE.search(text))
    m = _BIRTH_RE.search(text)
    if m:
        y = int(m.group(1))
        if y < 100:
            y += 2000 if y <= REFERENCE_YEAR % 100 else 1900
            if REFERENCE_YEAR - y > _MAX_TWO_DIGIT_YEAR_AGE:
                return None
        age = REFERENCE_YEAR - y
        return (age, False) if 0 <= age <= 120 else None
    m = _ARABIC_RE.search(text)
    if m:
        return int(m.group(1)), man
    m = _BARE_NUMBER_RE.fullmatch(text.strip())
    if m:  # 「나이 48에」의 「48에」 — 나이 스팬이 수(+조사)뿐이면 그 수가 나이다
        return int(m.group(1)), man
    m = _SINO_RE.search(text)
    if m:
        return _SINO_DIGITS.get(m.group(1), 1) * 10 + _SINO_DIGITS.get(m.group(2) or "", 0), man
    m = _NATIVE_RE.search(text)
    if m:
        return _NATIVE_TENS[m.group(1)] + _NATIVE_UNITS.get(m.group(2) or "", 0), man
    m = _NATIVE_UNIT_ONLY_RE.search(text)
    if m:
        return _NATIVE_UNITS[m.group(1)], man
    return None


def age_bands(condition: Mapping[str, Any]) -> list[str] | None:
    """age condition → 5세 구간 목록. 해석이 안 되면 None (그 단서로는 좁히지 않는다).

    정확한 나이는 만 나이·세는 나이가 섞여 쓰이므로 (나이, 나이−1) 두 값의 구간을 함께 쓴다 — 경계에서 엉뚱한 구간 하나로
    단정하지 않게. 「만 40세」처럼 만 나이가 명시되면 그 나이 하나만 쓴다.
    """
    kind = condition.get("kind")
    value = unicodedata.normalize("NFC", str(condition.get("value") or ""))
    if kind == "age_band" and value in AGE_BAND_VALUES:
        return [value]
    if kind != "age_exact":
        m = _RANGE_RE.search(value)
        if m:
            lo, hi = sorted((int(m.group(1)), int(m.group(2))))
            return _bands_for_ages(range(lo, hi + 1)) or None
        m = _DECADE_RE.search(value)
        if m:
            d = int(m.group(1)) * 10
            return _bands_for_ages(range(d, d + 10)) or None
        m = _NATIVE_DECADE_RE.search(value)
        if m:
            d = _NATIVE_TENS[m.group(1)]
            return _bands_for_ages(range(d, d + 10)) or None
    exact = _exact_age(value)
    if exact is None:
        return None
    age, man = exact
    return _bands_for_ages((age,) if man else (age, age - 1)) or None


# 본인 성별을 가리키는 표현 — 스팬 **전체**가 이 말(+조사)일 때만 쓴다. 「여자친구 · 남자친구 · 엄마가 해 준 밥」처럼
# 다른 사람을 가리키는 긴 표현은 쓰지 않는다. 배우자 호칭은 그 배우자가 있는 사람이라 반대 성별이다 (이성 혼인 가정 — assumptions).
_SEX_TERMS = {
    "F": ("여자", "여성", "엄마", "아줌마", "워킹맘", "새댁", "며느리", "남편", "신랑"),
    "M": ("남자", "남성", "아빠", "아저씨", "아내", "와이프", "집사람", "처남"),
}
_SEX_JOSA = r"(?:이|가|은|는|을|를|도|의|로|로서|으로서|랑|이랑|하고|한테|와|과|예요|이에요|입니다|이고|고)?"
_SEX_RE = {sex: re.compile(r"(?:" + "|".join(terms) + r")" + _SEX_JOSA) for sex, terms in _SEX_TERMS.items()}


def sex_of(condition: Mapping[str, Any]) -> str | None:
    text = unicodedata.normalize("NFC", str(condition.get("value") or "")).strip()
    hits = {sex for sex, rx in _SEX_RE.items() if rx.fullmatch(text)}
    return hits.pop() if len(hits) == 1 else None


# ── 조건 만들기 (기존 build_conditions 가 버리는 지명 보완) ────────────────

# 어간·앞머리로 찾은 위치는 추정이다 — 신뢰도를 깎는다 (명시 1.0 → 0.8 은 여전히 직접 좁히고, 암묵 0.8 → 0.64 는 비율로만)
GUESS_PENALTY = {"stem": 0.8, "prefix": 0.8}


def location_condition_from_text(text: str, post_id: str, confidence: float, *,
                                 facility: bool = False) -> dict[str, Any] | None:
    """사전 정식 이름이 아닌 지명(약칭 · 조사 붙은 꼴 · 어간 · 지명이 앞에 붙은 장소)도 위치 condition 으로 만든다.

    장소 스팬은 ``kind: facility`` 로 남겨 계산 때도 같은 해석 경로(역 우선)를 탄다.
    """
    idx = _default_index()
    codes, how = idx.resolve_text(text, facility=facility)
    if not codes:
        return None
    conf = confidence * GUESS_PENALTY.get(how, 1.0)
    resolution = 1 if len(codes) > 300 else 2 if len(codes) > 3 else 3
    return {"axis": "location", "kind": "facility" if facility else "administrative_area", "value": text,
            "resolution": resolution, "confidence": round(conf, 2), "source_post_ids": [post_id]}


def geo_tag_condition(tag: str, post_id: str) -> dict[str, Any] | None:
    """위치태그 → location condition (사용자가 붙인 메타라 신뢰도 1.0)."""
    idx = _default_index()
    codes, _ = idx.resolve_text(tag)
    if not codes:
        return None
    return {"axis": "location", "kind": "administrative_area", "value": tag,
            "resolution": 2, "confidence": 1.0, "source_post_ids": [post_id]}


def conditions_from_posts(posts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """[{post_id, spans, geo_tag?}] → condition 목록. 기존 ``build_conditions`` 에 세 가지를 더한다.

    - 사전 정식 이름이 아닌 지명·장소를 위치 condition 으로 살린다 — 실제 사람들이 쓰는 말이다
    - 장소(역·시설) 단서는 **관계 불명**이면 신뢰도를 절반으로 — 「선릉역에서 친구를 만났다」는 사는 곳 단서가 아니다.
      같은 글에 본인의 거주 표지(REL_HOME · 「집 근처」)가 있으면 그대로 둔다. 여러 글에서 반복되면 합산으로 다시 강해진다
    - 위치태그를 위치 condition 으로 넣는다

    신뢰도만 바꾸므로 ``risk_total`` (해상도 기반)은 그대로다.
    """
    from .clues import build_conditions  # 순환 import 회피
    from .model import LEVEL_CONFIDENCE

    d = _default_index().d
    out: list[dict[str, Any]] = []
    for post in posts:
        pid = str(post["post_id"])
        spans = list(post.get("spans") or [])
        home = any(s.get("type") == "REL_HOME" and s.get("subject") == "self" for s in spans)
        idx = _default_index()
        # 「안동」 — 약칭과 같은 이름의 동이 있는 지명은 build_conditions 가 동 코드(김해시 안동) 하나로 고정한다.
        # 이 스팬들은 빼고 아래 해석기(약칭·동 둘 다 후보)로 보낸다
        collision = {id(s) for s in spans if s.get("type") in ("LOC_ADMIN", "LOC_FACILITY")
                     and idx.is_short_collision(str(s.get("text", "")))}
        conds = list(build_conditions([s for s in spans if id(s) not in collision], pid, dictionary=d))
        for s in spans:
            if s.get("type") not in ("LOC_ADMIN", "LOC_FACILITY") or s.get("subject") == "other":
                continue
            if id(s) not in collision and build_conditions([s], pid, dictionary=d):
                continue  # build_conditions 가 이미 조건으로 만든 위치 스팬
            level = str(s.get("level"))
            if level not in LEVEL_CONFIDENCE:
                continue
            conf = LEVEL_CONFIDENCE[level] * (0.5 if s.get("subject") == "unknown" else 1.0)
            c = location_condition_from_text(str(s.get("text", "")), pid, conf,
                                             facility=s.get("type") == "LOC_FACILITY")
            if c:
                conds.append(c)
        if not home:
            for c in conds:
                if c.get("axis") == "location" and c.get("kind") == "facility":
                    c["confidence"] = round(float(c["confidence"]) * FACILITY_RELATION_PENALTY, 4)
        out.extend(conds)
        if post.get("geo_tag"):
            c = geo_tag_condition(str(post["geo_tag"]), pid)
            if c:
                out.append(c)
    return out


# ── 계산 ────────────────────────────────────────────────────────────────

FACILITY_RELATION_PENALTY = 0.5
_MAX_STATES = 20000  # 서로 다른 교집합 상태 수 상한 (실제 데이터에서는 수십 개). 넘으면 인구가 작은 상태부터 남기고 기록한다 —
# 상한에 걸리면 단조성 보장이 깨질 수 있다 (README 한계)
_LEGAL_HOWS = ("legal_expansion", "admin_group_expansion")


def _location_set(cond: Mapping[str, Any], idx: _Index) -> tuple[set[str], str]:
    code = cond.get("geo_code")
    if code:
        codes = idx.emds(str(code))
        if cond.get("kind") == "facility":  # 역 — 걸어서 닿는 이웃 동까지
            codes = codes | {c for c in idx.station_near.get(str(code), ()) if c in idx.population}
        return codes, "geo_code"
    return idx.resolve_text(str(cond.get("value") or ""), facility=cond.get("kind") == "facility")


def _describe(cond: Mapping[str, Any]) -> str:
    v = cond.get("value") or cond.get("geo_code") or cond.get("kind")
    return f"{cond['axis']}:{cond.get('kind')} «{v}»"


class _Clue:
    """같은 값 집합을 가리키는 단서 묶음 하나 (서로 다른 글의 뒷받침을 합친 것)."""

    __slots__ = ("values", "conf", "posts", "label", "legal")

    def __init__(self, values: frozenset, conf: float, posts: tuple[str, ...], label: str, legal: bool) -> None:
        self.values, self.conf, self.posts, self.label, self.legal = values, conf, posts, label, legal


def _group(items: Sequence[tuple[Mapping[str, Any], frozenset, bool]], assumptions: list[str], what: str) -> list[_Clue]:
    """같은 값 집합끼리 묶고 **서로 다른 글**의 신뢰도를 noisy-OR(1 − Π(1 − c))로 합친다. 같은 글 안의 반복은 합치지 않는다.

    법정동 확장(legal) 여부는 묶음의 어느 단서든 그렇게 해석됐으면 남긴다 — 「역삼동」과 「역삼동에서」가 같은 뜻으로 묶여도
    최소값 규칙이 사라지지 않게.
    """
    groups: dict[frozenset, list[tuple[Mapping[str, Any], frozenset, bool]]] = defaultdict(list)
    for item in items:
        groups[item[1]].append(item)
    out = []
    for values, grp in groups.items():
        best: dict[str, float] = {}
        for c, _, _ in grp:
            for pid in c.get("source_post_ids") or ["?"]:
                best[pid] = max(best.get(pid, 0.0), float(c["confidence"]))
        conf = min(1.0, 1 - math.prod(1 - v for v in best.values()))
        head = max(grp, key=lambda x: float(x[0]["confidence"]))[0]
        if len(best) > 1 and conf > float(head["confidence"]) + 1e-9:
            assumptions.append(f"같은 {what} 단서가 글 {len(best)}편에 있어 신뢰도를 합쳤다 — {_describe(head)} → {conf:.2f}")
        out.append(_Clue(values, conf, tuple(sorted(best)), _describe(head), any(x[2] for x in grp)))
    return out


def _states(clues: Sequence[_Clue], assumptions: list[str], what: str, size=len) -> dict[frozenset, tuple[str, ...]]:
    """강한 단서들로 만들 수 있는 **서로 다른 교집합 상태** 전부 → 그 상태를 만든 단서 이름들.

    부분집합(2^n)이 아니라 상태를 모으므로 같은 단서가 40번 나와도 상태는 하나다.
    """
    states: dict[frozenset, tuple[str, ...]] = {}
    for c in clues:
        new = {c.values: (c.label,)}
        for st, labels in states.items():
            inter = st & c.values
            if inter and inter not in states and inter not in new:
                new[inter] = labels + (c.label,)
        states.update({k: v for k, v in new.items() if k not in states})
        if len(states) > _MAX_STATES:
            keep = sorted(states, key=size)[:_MAX_STATES]
            states = {k: states[k] for k in keep}
            assumptions.append(f"{what} 교집합 상태가 {_MAX_STATES}개를 넘어 가장 좁은 상태들만 남겼다")
    return states


def _damped(p: float, conf: float, alpha: float) -> float:
    p = min(max(p, 0.0), 1.0)
    return (1 - conf * (1 - p)) ** alpha


def estimate_k(conditions: Sequence[Mapping[str, Any]], *, priors_path: str | None = None) -> dict[str, Any]:
    """condition 목록 → specificity.schema.json 의 ``output`` 객체."""
    return estimate_k_trace(conditions, priors_path=priors_path)[0]


def estimate_k_trace(conditions: Sequence[Mapping[str, Any]], *,
                     priors_path: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """``estimate_k`` + 검증용 추적 정보. 추적은 계약 출력에 넣지 않는다.

    결합 원칙 — **최종 k 의 방어적 최소**.
      가설 = (위치 교집합 상태 × 연령 교집합 상태 × 성별). 가설마다 약한 단서·비율 축까지 **다 적용한 최종 k** 를 계산하고
      가장 작은 값을 쓴다 (공격자는 어느 해석이든 고를 수 있다 — C 의 법정동 k_min 과 같은 원칙).
      모든 단서는 강하든 약하든 **비율 후보로도** 남는다. 단서를 더하면 가설이나 후보가 늘기만 하므로 k 는 커지지 않는다.
      축마다 비율은 하나만 곱한다 (규칙 1) — 그 축에서 감쇠가 가장 큰 후보 하나.
    """
    idx = _default_index()
    priors = load_priors(priors_path or str(DEFAULT_PRIORS_PATH))
    alpha = float(priors["alpha"])
    assumptions: list[str] = [
        f"직업·가족·통근·소득은 서로 독립이고 지역·연령·성별과도 독립이라고 가정한다 — 상관 중복은 감쇠 α={alpha} 로 흡수",
        f"비율 p 는 해상도별 대표값이다 ({priors['version']} · {priors['status']})",
        "가능한 해석 중 후보가 가장 적은 해석을 쓴다 (방어적 최소 — 공격자가 고를 수 있는 가장 좁은 해석)",
    ]

    # ── 위치 ──
    loc_items = []
    for c in conditions:
        if c.get("axis") != "location":
            continue
        codes, how = _location_set(c, idx)
        if codes:
            loc_items.append((c, frozenset(codes), how in _LEGAL_HOWS))
            if how in ("homonym_unresolved", "short_alias_homonym"):
                assumptions.append("동명 지명은 후보 전체의 합집합으로 시작한다 — 다른 위치 단서와 겹치는 곳만 남는다")
        else:
            assumptions.append(f"위치 단서 해석 불가 — {_describe(c)}")
    loc = _group(loc_items, assumptions, "위치")
    loc_strong = [c for c in loc if c.conf >= STRONG_CONFIDENCE]
    loc_states = _states(loc_strong, assumptions, "위치", size=lambda st: idx.pop(st))
    legal_sets = {c.values for c in loc_strong if c.legal}
    nation = frozenset(idx.all_emd)
    # 가설 목록 — 「제한 없음」은 항상 남긴다 (강한 단서가 처음 생겨도 기존 해석이 사라지지 않게).
    # 법정동 확장 상태는 후보 동 하나하나를 각각의 가설로 펼친다 — 「후보 동 중 최소」(specificity_l1 의 k_min)를
    # 「가설 중 최소」와 같은 틀로 다루고, 비율의 분모도 그 동 자신이 되게.
    loc_hyps: list[tuple[frozenset, tuple[str, ...], frozenset | None]] = [(nation, (), None)]
    for st, labels in loc_states.items():
        loc_hyps.append((st, labels, None))
        if st in legal_sets and len(st) > 1:
            loc_hyps.extend((frozenset({c}), labels, st) for c in sorted(st))

    # ── 연령 ──
    age_items = [(c, frozenset(b), False) for c in conditions if c.get("axis") == "age" and (b := age_bands(c))]
    age = _group(age_items, assumptions, "연령")
    age_states = _states([c for c in age if c.conf >= STRONG_CONFIDENCE], assumptions, "연령")
    all_bands = frozenset(_BANDS)
    age_states = {all_bands: (), **age_states}

    # ── 성별 ──
    sex_items = [(c, frozenset({s}), False) for c in conditions if c.get("axis") == "sex" and (s := sex_of(c))]
    sex = _group(sex_items, assumptions, "성별")
    sex_states = {frozenset({"M", "F"}): (), **{c.values: (c.label,) for c in sex if c.conf >= STRONG_CONFIDENCE}}
    if sex_items:
        assumptions.append("배우자 호칭으로 본인 성별을 정할 때 이성 혼인을 가정한다")
    if len({v for c in sex for v in c.values}) > 1:
        assumptions.append("본인 성별 단서가 서로 엇갈린다 — 후보가 적은 쪽을 쓴다 (방어적 최소)")

    # ── 나머지 축: 축마다 감쇠가 가장 큰 단서 하나 (가설과 무관) ──
    ratio_axes: list[tuple[str, str, float, float, float]] = []  # (axis, 설명, p, conf, 감쇠)
    for axis in RATIO_AXES:
        table = priors["axes"][axis]
        top = max(int(k) for k in table)
        best = None
        for c in conditions:
            if c.get("axis") != axis or int(c.get("resolution", 0)) <= 0:
                continue
            p = float(table[str(min(int(c["resolution"]), top))]["p"])
            f = _damped(p, float(c["confidence"]), alpha)
            if best is None or f < best[4]:
                best = (axis, _describe(c), p, float(c["confidence"]), f)
        if best:
            ratio_axes.append(best)
    ratio_mult = math.prod(x[4] for x in ratio_axes)

    def sexes(state: frozenset) -> list[str] | None:
        return None if state == frozenset({"M", "F"}) else sorted(state)

    def pop(codes: frozenset, sx: frozenset, bands: frozenset) -> int:
        s = sexes(sx)
        b = None if bands == all_bands else [x for x in _BANDS if x in bands]
        if s is None:
            return idx.pop(codes, None, b)
        return sum(idx.pop(codes, one, b) for one in s)

    def weak_best(clues: Sequence[_Clue], cur, make_sub, base: int):
        """그 축의 모든 단서 중 지금 가설을 더 좁히는 것 → 감쇠가 가장 큰 하나 (p, conf, 감쇠, 이름)."""
        best = None
        for c in clues:
            sub = make_sub(c.values)
            if sub is None or not base:
                continue
            p = sub / base
            if p >= 1.0:
                continue
            f = _damped(p, c.conf, alpha)
            if best is None or f < best[2]:
                best = (p, c.conf, f, c.label)
        return best

    best_h = None
    for lcodes, llabels, legal_parent in loc_hyps:
        for bands, alabels in age_states.items():
            for sx, slabels in sex_states.items():
                base = pop(lcodes, sx, bands)
                n0 = float(base)
                wl = weak_best(loc, lcodes, lambda v: pop(lcodes & v, sx, bands) if lcodes & v else None, base)
                wa = weak_best(age, bands, lambda v: pop(lcodes, sx, bands & v) if bands & v else None, base)
                ws = weak_best(sex, sx, lambda v: pop(lcodes, sx & v, bands) if sx & v else None, base)
                n = n0 * math.prod(w[2] for w in (wl, wa, ws) if w) * ratio_mult
                if best_h is None or n < best_h[0]:
                    best_h = (n, lcodes, llabels, legal_parent, bands, alabels, sx, slabels, base, n0, wl, wa, ws)
    n, lcodes, llabels, legal_parent, bands, alabels, sx, slabels, base, n0, wl, wa, ws = best_h
    legal = legal_parent is not None

    # ── 계산 추적 (steps) ──
    steps: list[dict[str, Any]] = [{"axis": "location", "condition": "전 국민 (주민등록)",
                                    "n_after": idx.pop(nation), "method": "population_lookup"}]
    applied = False
    if llabels:
        applied = True
        shown = legal_parent if legal else lcodes
        steps.append({"axis": "location", "condition": " ∩ ".join(llabels) + f" → 읍면동 {len(shown)}곳",
                      "n_after": idx.pop(shown), "method": "population_lookup"})
    if alabels:
        applied = True
        steps.append({"axis": "age", "condition": " ∩ ".join(alabels) + " → " + ", ".join(x for x in _BANDS if x in bands),
                      "n_after": pop(lcodes, frozenset({"M", "F"}), bands), "method": "crosstab_lookup"})
    if slabels:
        applied = True
        steps.append({"axis": "sex", "condition": " · ".join(slabels) + f" → {'·'.join(sorted(sx))}",
                      "n_after": base, "method": "crosstab_lookup"})
    extra: dict[str, Any] = {}
    if legal:
        per = {c: pop(frozenset({c}), sx, bands) for c in sorted(legal_parent)}
        steps.append({"axis": "location", "condition": "법정동이 여러 행정동에 걸친다 — 후보 동 중 가장 좁은 해석",
                      "n_after": n0, "method": "legal_dong_expansion_min"})
        extra = {"resolution": "legal_expansion", "codes": sorted(legal_parent), "populations": per,
                 "k_union": max(1, sum(per.values())), "k_min": max(1, min(per.values()))}
        assumptions.append("법정동 하나가 여러 행정동에 걸치면 후보 동 중 최소 인구를 쓴다 (specificity_l1 과 같은 방어적 규칙)")
    if any(not (a.values & b.values) for i, a in enumerate(loc_strong) for b in loc_strong[i + 1:]):
        assumptions.append("서로 겹치지 않는 위치 단서가 있다 (이사·직장·여행지 가능) — 후보가 가장 적은 해석을 썼다")
    running = n0
    for axis, w in (("location", wl), ("age", wa), ("sex", ws)):
        if w:
            running *= w[2]
            applied = True
            steps.append({"axis": axis, "condition": w[3], "n_after": round(running, 4), "method": "ratio_damped",
                          "p": round(w[0], 6), "confidence": round(w[1], 4), "q_damped": round(w[2], 6)})
    for axis, desc, p, conf, f in ratio_axes:
        running *= f
        applied = True
        steps.append({"axis": axis, "condition": desc, "n_after": round(running, 4), "method": "ratio_damped",
                      "p": round(p, 6), "confidence": round(conf, 4), "q_damped": round(f, 6)})

    if applied and math.isfinite(n):
        k: float | None = round(max(1.0, n), 2)
        floor = n < 1
    else:
        k, floor = None, False
        if conditions:
            assumptions.append("적용할 수 있는 조건이 없다 — k 를 산출하지 않는다 (전 국민으로 두지 않는다)")
    out: dict[str, Any] = {
        "k": k,
        "k_level": classify_k(k) if k is not None else "UNKNOWN",
        "basis": {"source": "행정안전부 주민등록 인구통계", "as_of": idx.d.population_as_of},
        "risk": round(risk_total(conditions), 2),
        "risk_by_axis": risk_by_axis(conditions),
        "floor_applied": bool(floor),
        "steps": steps,
        "assumptions": list(dict.fromkeys(assumptions)),
        **extra,
    }
    support = max(loc_strong, key=lambda c: (c.conf, len(c.posts), -len(c.values)), default=None)
    trace = {"codes": (legal_parent if legal else lcodes) if llabels else frozenset(),
             "most_supported_codes": support.values if support else frozenset(),
             "location_states": len(loc_states) if llabels else 0}
    return out, trace


def specificity_document(user_ref: str, conditions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """specificity.schema.json 문서 전체 (input + output)."""
    dict_version = json.loads(Path(_default_index().d.path).read_text(encoding="utf-8"))["dict_version"]
    return {
        "schema_version": "1.0",
        "engine_version": ENGINE_VERSION,
        "dict_version": dict_version,
        "input": {"user_ref": user_ref, "conditions": [dict(c) for c in conditions]},
        "output": estimate_k(conditions),
    }


# ── 글별 기여 — 「이 글을 내리면 후보가 몇 명이 되나」 ─────────────────────────

def k_by_post(posts: Sequence[Mapping[str, Any]], *, max_unpublish: int = 3) -> dict[str, Any]:
    """[{post_id, spans, geo_tag?}] → 글별 「내렸을 때 k」 + 내리는 순서(greedy).

    ``estimate_k`` 는 조건을 빼도 k 가 줄지 않으므로(방어적 최소 · 단조) 글을 빼면 k 는 같거나 커진다.
    - ``per_post``: 그 글 하나만 내렸을 때의 k (클수록 그 글이 사람을 많이 좁히고 있다)
    - ``greedy``: k 를 가장 많이 늘리는 글부터 하나씩 내린 경로 (최대 ``max_unpublish`` 편, 최소 1편은 공개로 남김)
    화면 문구 예: 「이 글 3편을 비공개하면 후보가 312명 → 4,210명」
    """
    ids = [str(p["post_id"]) for p in posts]
    by_id = {str(p["post_id"]): p for p in posts}
    conds = {pid: conditions_from_posts([by_id[pid]]) for pid in ids}

    def k_of(keep: Sequence[str]) -> float | None:
        return estimate_k([c for pid in keep for c in conds[pid]])["k"]

    base = k_of(ids)
    per_post = []
    for pid in ids:
        without = k_of([x for x in ids if x != pid])
        per_post.append({"post_id": pid, "k_without": without,
                         "gain": None if (base is None or without is None) else round(without / base, 4)})
    per_post.sort(key=lambda r: -(r["gain"] or 0))

    keep = list(ids)
    current = base
    greedy = []
    limit = min(max_unpublish, max(0, len(ids) - 1))
    while len(greedy) < limit and current is not None:
        cands = [(k_of([x for x in keep if x != pid]), pid) for pid in keep]
        cands = [(k, pid) for k, pid in cands if k is not None and k > current * (1 + 1e-9)]
        if not cands:
            break
        k_next, pid = max(cands, key=lambda x: (x[0], x[1]))
        keep.remove(pid)
        current = k_next
        greedy.append({"remove": pid, "k_after": k_next})
    return {"k": base, "per_post": per_post, "greedy": greedy}
