"""스팬 등급(level)·주체(subject) 규칙 판정 — 1단 모델이 예측하지 않는 두 필드.

1단 BIO 모델은 21개 라벨(유형)만 예측한다. 지금까지 앱과 추론기는 모든 스팬에 ``implicit/self`` 임시값을
붙였고, 그래서 「본인 명시 단서」만 다루는 추천·바꿔 쓰기가 실제 앱에서는 한 번도 돌지 않았다.

정의는 label-schema §4-1 · §4-2 를 따른다.

- ``level``: 실무 판단 순서(§4-1 · IAA 파일럿 #200) — ① 수치·고유명사가 그대로 → explicit
  ② 표현 자체에 값이 거의 없음 → inferential ③ 나머지 → implicit. 유형마다 ①②를 가르는 표지를 둔다.
- ``subject``: **스팬이 속한 문장만** 본다(국소성 원칙). 문장이 단서를 타인에게 명시적으로 귀속시키면 other —
  「친구가 [화정에서] 공방 한다」 · 「[아홉 살] 아들은」 · 「[편의점 알바] 언니가」.

``resolve(texts, candidate)`` 는 ``experiments/exp06-finetune/infer.py`` 의 ``resolver`` 자리에 그대로 들어간다.
정밀도 우선: 타인 귀속이 분명하지 않으면 self(계약 기본값)로 둔다. ``unknown`` 은 내지 않는다.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

# ── 공통 ──────────────────────────────────────────────────────────────

_JOSA_TAIL = re.compile(
    r"(?:에서부터|에서는|에서도|에서|에게서|에게|한테|께서|으로는|으로도|으로|로는|로도|로|에는|에도|에|"
    r"이랑|랑|하고|과는|와는|과|와|이나|은|는|이|가|을|를|의|도|까지|부터|처럼|보다|쯤|인데|인디|이라서|라서|이고|이라고|라고)$")


def _core(text: str) -> str:
    """조사 하나만 뗀다 — 두 번 떼면 「작가로 → 작가 → 작」처럼 단어가 깎인다."""
    t = text.strip()
    m = _JOSA_TAIL.search(t)
    if m and len(t) - len(m.group(0)) >= 2:
        t = t[: m.start()].rstrip()
    return t


_NUM = re.compile(r"\d")
_NATIVE_NUM = re.compile(r"(?:열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)(?:하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉|한|두|세|네)?"
                         r"|(?<![가-힣])(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*(?:살|세)"
                         r"|[이삼사오육칠팔구]?십[일이삼사오육칠팔구]?\s*(?:살|세)")
_SINO_MONEY = re.compile(r"(?:[일이삼사오육칠팔구]?[십백천]|만|억)+\s*(?:만\s*)?원")

# ── level ─────────────────────────────────────────────────────────────

_FOREIGN = re.compile(r"호주|시드니|미국|뉴욕|캐나다|일본|도쿄|오사카|중국|상하이|베이징|베트남|하노이|태국|방콕|영국|런던|"
                      r"프랑스|파리|독일|해외|외국")
_AGE_IMPLICIT = re.compile(r"초등학생|중학생|고등학생|고딩|중딩|대학생|수능|고3|늙은이|환갑|칠순|팔순|정년|은퇴")

# 성별이 그대로 적힘. 배우자 호칭(남편·아내·할멈)은 관계로 성별을 「거의 확정」하므로 implicit (blind 25건 전부 implicit)
_SEX_EXPLICIT = re.compile(r"남성|여성|남자|여자")
_SEX_IMPLICIT = re.compile(r"남편|아내|와이프|마누라|할멈|영감|신랑|새댁|형|누나|언니|오빠|형님|군대|예비군|며느리|사위|"
                           r"친정|시댁|장모|장인|처가|시어머니|시아버지")

_FAM_SPECIFIC = re.compile(r"아들|딸|손주|손자|손녀|손지|며느리|사위|조카|누나|언니|오빠|형|남동생|여동생|동생|"
                           r"외?할아버지|외?할머니|첫째|둘째|셋째|막내|큰애|작은애|쌍둥이|식구|남편|아내|시어머니|시아버지|장모|장인")

_INCOME_IMPLICIT = re.compile(r"수당|정산|연금|결제|임대료|원고료|월급|급여|매출|인건비|용돈|반 토막")  # 활동비는 §4-1 의 inferential 예

# 노선·번호·역 이름이 그대로 — 「통근 셔틀 · 학원버스 · 지하철역」은 값이 없다
_COMMUTE_EXPLICIT = re.compile(r"\d+\s*번|호선|KTX|SRT|ITX|[가-힣]+선(?![가-힣])")
_GENERIC_STATION = ("지하철역", "전철역", "기차역", "버스역")


def _named_station(core: str) -> bool:
    """「매탄권선역」은 이름, 「지하철역」은 아니다."""
    return any(not w.endswith(_GENERIC_STATION) for w in re.findall(r"[가-힣]{2,}역(?![가-힣])", core))
_COMMUTE_IMPLICIT = re.compile(r"걸어서|카풀|차를|차 안|자전거|오토바이|운전|통근버스")

# 직업명이 그대로. 직급(팀장·과장)·호칭(사장님)만으로는 업종이 안 나온다
_JOB_EXPLICIT = re.compile(r"알바|선생님|교사|약사|간호사|의사|공방|[가-힣]+가게|식당|[가-힣]+ 사장님|건축주|건축가|"
                           r"기사|공무원|원장|강사|작가|일기$|개발자|프로그래머|엔지니어|디자이너|요리사|조리사|셰프|"
                           r"바리스타|제빵사|미용사|변호사|회계사|세무사|노무사|법무사|설계사|상담사|복지사|치료사|"
                           r"교수|연구원|기자|피디|PD|군인|경찰관?|소방관|농부|어부|목수|용접공|배달기사|택배기사|"
                           r"보육교사|유치원|학원 강사|과외")
_JOB_IMPLICIT = re.compile(r"교대|야간조|주간조|라인|원고료|마감|거래처|인보이스|단골 손님|손님|주방|설거지|"
                           r"장사|납품|출고|발주|결산|원단|염색|현장|시공|배포|코드|진료|수업")

_FACILITY_GENERIC = {
    "카페", "저수지", "우체국", "회관", "공장", "굴뚝", "방파제", "공단", "정문", "오일장", "항구", "방향", "마트", "공원",
    "도서관", "시장", "산책로", "편의점", "식당", "학교", "병원", "약국", "교회", "성당", "절", "경로당", "복지관",
    "복지회관", "체육관", "수영장", "헬스장", "학원", "터미널", "정류장", "버스정류장", "역", "주차장", "아파트",
    "단지", "상가", "골목", "강", "바다", "해변", "해수욕장", "산", "뒷산", "논", "밭", "과수원", "하우스", "창고",
    "놀이터", "키즈카페", "빵집", "꽃집", "미용실", "세탁소", "목욕탕", "사우나", "다리", "개천", "냇가", "둑", "저녁노을",
    "단골", "드립커피집", "동네", "근처", "앞", "옆", "뒤", "쪽", "까지", "부터", "에서", "집", "가게", "점심",
    "면사무소", "주민센터", "읍내", "시내", "마을회관", "보건소", "학원가",
}


_GENERIC_PREFIX = ("한인", "동네", "읍내", "단골", "작은", "큰", "새", "옛", "시립", "구립", "군립", "공립", "폐", "지하철", "전철")


def _generic_token(t: str) -> bool:
    if t in _FACILITY_GENERIC or len(t) <= 1:
        return True
    if re.search(r"(?:한|은|운|던|된)$", t) or (t.endswith("고") and len(t) >= 2 and t not in ("창고",)):
        return True  # 꾸미는 말 — 「아담한 공원」 「오래된 시장」
    return any(t.startswith(pre) and t[len(pre):] in _FACILITY_GENERIC | {"선길", "길"} for pre in _GENERIC_PREFIX)


def _facility_level(core: str) -> str:
    """시설: 고유 이름이 있으면 explicit, 흔한 시설 이름뿐이면 inferential (「한인마트 · 읍내 도서관」)."""
    toks = [_core(t) for t in re.split(r"\s+", core) if t]
    if any(re.search(r"[가-힣]{2,}역$", t) and not _generic_token(t) for t in toks):
        return "explicit"
    if all(_generic_token(t) for t in toks):
        return "inferential"
    return "explicit"


def level_of(stype: str, text: str) -> str:
    core = _core(text)
    if stype == "AGE":
        if _NUM.search(core) or _NATIVE_NUM.search(core):
            return "explicit"
        return "implicit" if _AGE_IMPLICIT.search(core) else "inferential"
    if stype == "LOC_ADMIN":
        # 국내 지명은 그대로 적힌 값. 해외 지명은 국내 인구표로 좁혀지지 않는다 (골드도 inferential)
        return "inferential" if _FOREIGN.search(core) else "explicit"
    if stype == "LOC_FACILITY":
        return _facility_level(core)
    if stype in ("REL_HOME", "REL_WORK"):
        return "inferential"  # 「집 · 옆집 · 회사」 — 다른 단서와 묶여야 좁혀진다
    if stype == "SEX":
        if _SEX_EXPLICIT.search(core):
            return "explicit"
        return "implicit" if _SEX_IMPLICIT.search(core) else "inferential"
    if stype == "FAM":
        return "implicit" if _FAM_SPECIFIC.search(core) else "inferential"
    if stype == "INCOME":
        if (_NUM.search(core) and ("원" in core or "만" in core)) or _SINO_MONEY.search(core):
            return "explicit"
        return "implicit" if _INCOME_IMPLICIT.search(core) else "inferential"
    if stype == "COMMUTE":
        if _COMMUTE_EXPLICIT.search(core) or _named_station(core):
            return "explicit"
        return "implicit" if _COMMUTE_IMPLICIT.search(core) else "inferential"
    if stype == "JOB":
        if _JOB_EXPLICIT.search(core):
            return "explicit"
        return "implicit" if _JOB_IMPLICIT.search(core) else "inferential"
    return "implicit"


# ── subject ───────────────────────────────────────────────────────────

# 타인을 가리키는 말 (가족 포함 — 가족의 거주지·나이·직업은 본인 것이 아니다)
_OTHERS = (r"(?:친한\s*|오랜\s*|대학\s*|고향\s*|동네\s*|전\s*직장\s*|같은\s*팀\s*|같이\s*일하던\s*|조리원\s*|군대\s*|동아리\s*)?"
           r"(?:친구|동창|동기|선배|후배|동료|지인|아는\s*(?:이|사람|분|언니|형)|이웃|옆집|앞집|윗집|아랫집|"
           r"시누이?|올케|형수|제수|매형|매부|처남|처제|동서|사촌|조카|"
           r"형님|형|누나|언니|오빠|남동생|여동생|동생|막내아들|막내딸|큰아들|작은아들|큰딸|작은딸|막내|큰애|작은애|"
           r"첫째|둘째|셋째|아들|딸|손주|손자|손녀|며느리|사위|남편|아내|와이프|신랑|"
           r"엄마|아빠|어머니|아버지|어머님|아버님|시어머니|시아버지|장모님?|장인어른|할머니|할아버지|"
           r"원장님|사장님|손님|양반|반장|선생님|아주머니|아저씨|이모|삼촌|고모|외삼촌|할매|할배|그분|걔|그 사람)")
# 「친구가」 「친구의 집은」 「형 나이는」 — 사람 또는 「사람 + 속성 명사」 주어
_ACTOR_BEFORE = re.compile(_OTHERS + r"(?:들)?(?:(?:이|가|은|는|도|께서|네|의)|(?:의)?\s+(?:나이|집|고향|직장|회사|직업|월급|연봉|동네|가게)"
                           r"(?:은|는|이|가|도))(?![가-힣])")
_FIRST_PERSON = re.compile(r"(?<![가-힣])(?:나는|난|내가|나도|저는|전|제가|저도|우리는|우린|우리가|우리도)(?![가-힣])")
_POSSESSIVE = re.compile(r"(?:내|제|나의|저의|우리)")


def _owned_by_me(before: str) -> bool:
    """「친구가 내 나이 [서른넷을]」 — 1인칭 소유가 스팬까지 명사 사슬로 이어질 때만 본인.

    「제 생일에 [마흔이]」 「내 동생이랑 [부산에]」처럼 사이에 조사가 붙은 말이나 사람이 끼면 아니다.
    """
    words = before.split()[-3:]
    for i in range(len(words) - 1, -1, -1):
        if _POSSESSIVE.fullmatch(words[i]):
            chain = words[i + 1:]
            return all((_core(w) == w or w.endswith("인")) and not re.fullmatch(_OTHERS, _core(w)) for w in chain)
    return False
# 스팬 바로 뒤가 사람을 꾸미는 자리 — 「[아홉 살] 아들」 「[편의점 알바] 언니」 「[동탄] 사는 친구」
_PERSON_AFTER = re.compile(r"^\s*(?:에\s*)?(?:사는|살던|사시는|있는|다니는|일하는|하는)?\s*" + _OTHERS
                           + r"(?:들|님)?(?:이|가|은|는|도|과|와|랑|이랑|하고|의|을|를|한테|에게|께)?(?![가-힣])")
# 스팬 자체가 타인 직업인 — 「[옆 반 선생님과]」 「[단골 건축주가]」(일의 의뢰인). 「단골 손님 · 사장님」은 내 일의 상대라 본인 직업 단서다
_OTHER_WORKER = re.compile(r"옆\s*반|건축주")
# 내 일·생활의 상대 — 이들이 주어여도 직업·통근·시설·가족 단서는 내 것이다 (「사장님이 [라떼아트]에 한마디」)
_COUNTERPART = re.compile(r"사장님|손님|아주머니|아저씨|양반|반장|할매|할배|이웃|옆집|앞집|윗집|아랫집|원장님|선생님")
# 문장 끝 — 문장부호·줄바꿈, 그리고 마침표 없는 SNS 종결(「갔다 」 「했음 」). 「동네 · 바다 · 마음」 같은 명사는 끊지 않는다
_SENTENCE = re.compile(r"[.!?…\n]")
_PAST = {chr(c) for c in range(0xAC00, 0xD7A4) if (c - 0xAC00) % 28 == 20}  # 받침 ㅆ — 갔·했·었
_END_PREV = set("는한된간산온본운인란난")
_CONCESSIVE = re.compile(r"\s*(?:해도|하더라도|하면서|하고|해서|면서|지만|는데)")


def _boundaries(left: str) -> list[int]:
    """문장부호·줄바꿈, 그리고 마침표 없는 SNS 종결 — 「갔다 」 「했음 」 「산대 」 「살아요 」.

    「바다 · 마음 · 동네」 같은 명사, 「웃는다 해도」 같은 이어짐, 문장 중간 「ㅋㅋ」는 끊지 않는다.
    """
    cuts = [m.end() for m in _SENTENCE.finditer(left)]
    for i in range(1, len(left) - 1):
        ch, prev = left[i], left[i - 1]
        if not left[i + 1].isspace():
            continue
        if (ch in "다음" and (prev in _PAST or prev in _END_PREV)) or (ch in "대래" and prev in _END_PREV | _PAST) \
                or (ch in "요죠" and "가" <= prev <= "힣"):
            if not _CONCESSIVE.match(left[i + 1:]):
                cuts.append(i + 1)
    return cuts


def _sentence_window(text: str, start: int, end: int) -> tuple[str, str]:
    """스팬이 속한 문장의 앞부분 · 뒷부분 (국소성 원칙)."""
    left = text[:start]
    cut = max(_boundaries(left), default=0)
    right = text[end:]
    m = re.search(r"[.!?…\n]", right)
    return left[cut:], right[: m.start()] if m else right


def subject_of(stype: str, text: str, channel_text: str | None, start: int | None, end: int | None) -> str:
    if channel_text is None or start is None or end is None:
        return "self"
    before, after = _sentence_window(channel_text, start, end)
    core = _core(text)
    if re.match(r"(?:내|제|나의|저의|우리)(?![가-힣])", text.strip()) or _owned_by_me(before):
        return "self"  # 1인칭 소유 — 「[우리 집에]」 「내 나이 [서른넷을]」
    # ① 스팬 바로 뒤가 타인 → 그 사람의 속성 — 「[아홉 살] 아들」 「[편의점 알바] 언니」 「[동탄] 사는 친구」
    #    관계·시설 단서(「[옆집] 아주머니」 「[이웃] 엄마들」)는 내 관계라 제외. 「[거래처] 사장님」은 내 일의 상대
    #    조사가 붙은 스팬은 사람을 꾸미지 않는다 — 「[역삼동에서] 친구를 만났다」(만난 곳) · 단 「[동탄에] 사는 친구」
    bare = _core(text) == text.strip()
    m = _PERSON_AFTER.match(after) if stype in ("AGE", "LOC_ADMIN", "JOB", "INCOME") else None
    if m and not bare and not re.match(r"^\s*(?:사는|살던|사시는|있는|다니는|일하는)", after):
        m = None
    if m and not (stype == "JOB" and _COUNTERPART.search(m.group(0))):
        return "other"
    # ② 스팬 자체가 타인 직업인
    if stype == "JOB" and _OTHER_WORKER.search(core) and not re.search(r"알바|일기", core) \
            and not _FIRST_PERSON.search(before):
        return "other"  # 「나는 [건축주로]」는 본인
    # ③ 같은 문장 앞에 타인 주어가 있고, 그 뒤로 1인칭 주어가 다시 나오지 않음
    actors = list(_ACTOR_BEFORE.finditer(before))
    if actors:
        last = actors[-1]
        if not _FIRST_PERSON.search(before[last.end():]):
            word = last.group(0)
            explicit_title = stype == "JOB" and level_of(stype, text) == "explicit"
            if _COUNTERPART.search(word) and stype in ("JOB", "COMMUTE", "LOC_FACILITY", "FAM") and not explicit_title:
                return "self"  # 단 「사장님이 [약사라서]」 — 직업명 자체는 그 사람 것
            if stype == "FAM" and not re.search(r"친구|동창|동기|선배|후배|동료|지인|아는|이웃|옆집|앞집|윗집|아랫집|원장|사장|손님|양반|반장|선생|아주머니|아저씨|그분|걔|그 사람", word):
                return "self"  # 「아내가 [아이] 데리러」 — 내 가족 구성이다
            if stype == "SEX" and re.search(r"남편|아내|와이프|신랑", word) and level_of(stype, text) != "explicit":
                return "self"  # 관계 호칭은 내 쪽 단서. 「남편은 [남자라서]」(성별이 그대로)는 남편 것  # 배우자가 주어여도 성별 단서는 관계(나의 배우자)다
            return "other"
    return "self"


def resolve(texts: Mapping[str, str], candidate: Mapping[str, Any]) -> dict[str, str]:
    """infer.py 의 resolver 자리 — {level, subject} 만 돌려준다."""
    stype = str(candidate.get("type", ""))
    text = str(candidate.get("text", ""))
    tid = str(candidate.get("text_id", ""))
    channel = tid if tid in texts else (tid.split(":", 1)[1] if ":" in tid else tid)  # 「body」 또는 「A01_b04:body」
    channel_text = texts.get(channel)
    start, end = candidate.get("start"), candidate.get("end")
    if channel_text is not None and isinstance(start, int) and isinstance(end, int) and channel_text[start:end] != text:
        channel_text = None  # 오프셋이 다른 기준이면 문맥을 쓰지 않는다
    return {"level": level_of(stype, text), "subject": subject_of(stype, text, channel_text, start, end)}
