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

# 성별이 그대로 적힘. 배우자 호칭(남편·아내·할멈)은 관계로 성별을 「거의 확정」하므로 implicit (blind 배우자 호칭 9건 전부 implicit · 계약 §4-1 「오빠인 나」)
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
_MODIFIER = r"(?:사는|살던|사시는|살고\s*있는|있는|다니는|일하는|하는|된|먹은|짜리|인|이던|였던)"  # 「난」은 1인칭(나는)과 겹쳐 뺀다
_PERSON_AFTER = re.compile(r"^\s*(?:에\s*)?" + _MODIFIER + r"?\s*" + _OTHERS
                           + r"(?:들|님)?(?:이|가|은|는|도|과|와|랑|이랑|하고|의|을|를|한테|에게|께)?(?![가-힣])")
_COPULA_AFTER = re.compile(r"(?:들)?(?:야|이야|예요|이에요|입니다|이고|인데요|인데|임|이다|이었어|였어|이거든|거든|라서|이라서|이라|라)(?![가-힣])")
# 스팬 뒤 술어가 주어 자신의 속성을 말하면(살다·일하다·출근하다·다니다) 단서는 그 주어의 것 — 상대 호칭 예외를 쓰지 않는다
# (#306 리뷰: 「사장님은 [부산역] 앞에 산다」 「손님은 [야간조로] 일한다」 「사장님은 [2호선으로] 출근한다」)
_OWN_VERB = (r"(?:산다|사는|삽니다|사신다|사십니다|사셔|살아|살고|살면서|살더라"
             r"|일한다|일해|일하고|일하는|일합니다|일하신다|일하십니다|일했|일하며"
             r"|(?:출근|퇴근|근무|통근|운영)(?:한다|해|하고|하는|합니다|하신다|하십니다|했|하며)"
             r"|다닌다|다니는|다닙니다|다니신다|다녀|다니고)")  # 「-세요」는 명령과 높임이 갈리지 않아 뺀다
# 스팬 **바로 뒤**의 술어만 — 사이에는 위치 말(앞에·근처에·쪽으로…)만 허용한다.
# 「사장님은 [부산역] 앞에 산다」 ○ · 「사장님이 [라떼아트에] 한마디 해줘서 일하고 왔다」 ✗ (바로 뒤가 「한마디」)
_OWN_PREDICATE = re.compile(
    r"^\s*(?:(?:앞|뒤|옆|근처|쪽|동네|근방|인근|부근)(?:에서|에|으로|로)?\s*)?(?:에서|에|으로|로)?\s*" + _OWN_VERB
    + r"(?![가-힣]*[표길])")


# 술어가 1인칭을 꾸미면(「일하는 나를」) 그 속성은 나 · 시키거나 옮긴 말이면(「일해 보라고」 「출근하라고」) 주어 것이 아니다
_ME_AFTER = re.compile(r"\s*(?:있는\s*)?(?:나|내|저|제)(?:를|게|가|는|의|한테|에게)?(?![가-힣])")
_DIRECTIVE_AFTER = re.compile(r"\s*(?:보라|봐|봐라|라고|래|하라|하고\s*말|고\s*했|달라)")


_HOUSEHOLD = re.compile(r"^[가-힣]{1,3}네(?:는|가|를|도|에|에서|로|서|집|집에|집으로)?$")
# 「X네」 뒤 술어 — 그 집이 어디 있다 · 주어가 그 집에 가다·살다·다녀오다. 사이에는 부사만 허용 (Codex 10/6)
_HOUSEHOLD_ADVERB = (r"(?:자주|가끔|종종|또|다시|먼저|늘|매일|매번|매주|매달|매년|날마다|주말마다|주말에|명절마다|명절에"
                     r"|요즘|잠깐|잠시|이번에|얼른|곧잘|한동안|아예|금방)")
_HOUSEHOLD_PRED = re.compile(
    r"^\s*(?:" + _HOUSEHOLD_ADVERB + r"\s+)?"
    r"(?:있[가-힣]*|살[았아고면며]|산다|사는|삽니다|사세요|사신|사셔|사시"
    r"|가(?:요|서|고|는|야|려|면|자|셨|시|신|십)|간다|갑니다|갔|다녀|놀러|들르|들렀|들러)")
# 「사장님이 [언니네] 있는 나를 · [언니네로] 가려는 나를 데려다주셨다」 — 술어 어절이 1인칭을 꾸미면 내 쪽 말이다
_HOUSEHOLD_ME_AFTER = re.compile(r"^[가-힣]*\s*(?:나|저|내|제)(?:를|을|에게|한테|의|가|는|도)?(?![가-힣])")


def _household_modifies_me(after: str, end: int) -> bool:
    """술어 어절이 관형형(…는 · …은 · …던)이고 바로 뒤가 1인칭인가 — 「있는 나를」 「가려는 나를」.
    「가셨는데 나를 보고」(연결어미 뒤 다른 절)는 아니다 (Codex 10/6)."""
    m = re.match(r"[가-힣]*", after[end:])
    word = after[:end].split()[-1] + m.group(0)
    return bool(re.search(r"(?:는|은|던|간|산|온)$", word)) and bool(_HOUSEHOLD_ME_AFTER.match(after[end:]))


def _own_predicate(after: str) -> bool:
    """스팬 바로 뒤의 술어가 주어 자신의 속성(살다·일하다·출근하다·다니다)인가 (#306 리뷰)."""
    m = _OWN_PREDICATE.match(after)
    if not m:
        return False
    rest = after[m.end():]
    return not (_ME_AFTER.match(rest) or _DIRECTIVE_AFTER.match(rest))


_RESIDENT_AFTER = re.compile(r"^\s*(?:에\s*)?(?:사는|살던|사시는|살고\s*있는)\s*" + _OTHERS
                             + r"(?=(?:들|님)?(?:이|가|은|는|을|를|과|와|랑|이랑|하고|에게|한테|께|의|도|만|야|이야|예요|이에요|입니다"
                             r"|이고|인데요|인데|임|이다|이었어|였어|이거든|거든|라서|이라서|이라|라)?(?![가-힣]))")
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


def _person_end(after: str, m: "re.Match[str]") -> int:
    """_PERSON_AFTER 매치에서 사람 명사가 끝나는 자리 (붙은 조사 앞) — 자기소개(이다) 판정용."""
    rm = _RESIDENT_AFTER.match(after)
    if rm:
        return rm.end()
    body = re.match(r"^\s*(?:에\s*)?" + _MODIFIER + r"?\s*" + _OTHERS, after)
    return body.end() if body else m.end()


# 성별 단서로 잡힌 홑 부모 호칭(「아빠가」 「엄마는」) — 아빠 · 엄마 블로거는 자기를 「아빠의 시간」처럼 부른다(골드 A23).
# 자녀 입장의 글(「엄마아빠가 혼자는 안 된대」 「엄마랑 나랑」 · 자녀 표지 없음)이면 글쓴이의 부모라 그 사람의 성별이다 (실제 글 시험 10/16).
# 같은 문단에 자녀 · 가족 표지가 있고 자녀 입장 표지가 없을 때만 본인 — 다른 문단의 「부모님」으로 뒤집히지 않게(Codex).
# 문장 앞에 1인칭이 있으면(「나는 아빠가 됐다」) 자기소개라 본인. 복수 · 겸칭(「엄마들」 「엄마이자」)은 이 규칙 밖
_PARENT_TERM = re.compile(r"(?:엄마|아빠|어머니|아버지|엄빠)(?:가|는|의|도|를|한테|랑|이랑|하고|께서|은|이)?")
_KID_JOSA = r"(?:들)?(?:이|가|은|는|을|를|도|의|만|과|와|랑|이랑|하고|한테|에게|래|아|네)?(?![가-힣])"   # 「아이들이」도 (Codex)
# 「아이참」(감탄사) · 「딸기」는 거른다 · 「하원」은 「미국 하원」과 갈려 뺀다 (Codex)
_PARENT_OF_CHILD = re.compile(r"(?<![가-힣])(?:(?:아이|아들|딸|애들)" + _KID_JOSA
                              + r"|우리\s*애|첫째|둘째|어린이집|유치원|육아|기저귀|이유식|가족|식구)")
_CHILD_VIEW = re.compile(r"엄마\s*아빠|아빠\s*엄마|엄빠|부모님|엄마랑\s*나|아빠랑\s*나|엄마와\s*나|우리\s*엄마|우리\s*아빠|효도")
# 명백한 여행 표현이 붙은 지명 — 골드(test 제외 2,281편)에서 이 꼴은 1개이고 self 가 아니다(「대전 놀러 갔다가」 · 10/16).
# 「들러 · 갔다 · 다녀왔다 · 내려가면」 같은 이동 말은 넣지 않는다 — 동네 볼일 · 본가 · 이사(「농협에 들러」 「본가인 창원에 내려가면」
# 「제주 내려와 살면서」)라 골드에서 본인 거주 단서다(27/28).
# 같은 줄에서 지명을 꾸미는 꼴만 — 「[제주] 여행」 「[부산] 놀러」 「[일본에] 디자인 여행이나」. 「[서울에서] 살며 여행」(사이에 술어) ·
# 「[부산에서] 여행사를 운영」(에서 = 활동 장소 · 여행사) · 「[서울]⏎휴가 끝나고」(다음 줄) · 「[한국관광공사]」는 아니다 (Codex)
_TRAVEL_WORD = (r"(?:여행|놀러|관광|나들이|당일치기|투어|출장|휴가(?!철)(?![ \t]*(?:끝|복귀|내고|중에도)))"   # 「제주 휴가」 ○ · 「휴가 끝나고 · 휴가철」 ✗ (Codex)
                r"(?!사|객|공사|업|지도)")
_SELF_INTRO_AFTER = re.compile(r"\s*(?:됐|되었|된\s*지|돼|되고|되면|되어|였|이었|이다|예요|이에요|입니다|로서|라서|인데|이고"
                               r"|(?:다|야|이야|고|자|이자)(?=$|[^가-힣]|요(?![가-힣])))")
# 「나는 아빠였다」 「나는 엄마이고 직장인이다」 「나는 엄마로서는」 (Codex). 짧은 어미(다 · 야 · 고 · 자 …)는 낱말이 끝나야 한다 —
# 「아빠가 자랑스럽다」 「엄마가 다쳤다」 「엄마 이야기」는 자기소개가 아니다 (B · #378)
_TRAVEL_IN = re.compile(_TRAVEL_WORD + r"(?:지|길)?(?:에서|에|으로|로|을|를|이|가)?$")   # 스팬이 여행 말로 끝날 때만
_TRAVEL_AFTER = re.compile(r"[ \t]*(?:에|로|으로)?[ \t]*(?:[가-힣]{1,4}(?<![며고서면는다던])[ \t]+)?" + _TRAVEL_WORD)


def _paragraph(text: str, start: int, end: int) -> str:
    """스팬이 속한 문단(빈 줄로 나뉜 덩어리) — 부모 호칭 판정은 다른 문단 문맥을 쓰지 않는다 (Codex)."""
    a = text.rfind("\n\n", 0, start)
    b = text.find("\n\n", end)
    return text[a + 2 if a >= 0 else 0: b if b >= 0 else len(text)]


def subject_of(stype: str, text: str, channel_text: str | None, start: int | None, end: int | None) -> str:
    if channel_text is None or start is None or end is None:
        return "self"
    if stype == "SEX" and _PARENT_TERM.fullmatch(text.strip()):
        para = _paragraph(channel_text, start, end)
        before_s, after_s = _sentence_window(channel_text, start, end)
        # 자기소개 — 1인칭이 앞에 있고 뒤가 「됐다 · 이다 · 예요 · 로서」(「나는 아빠가 됐다」). 「나는 아빠가 싫다」는 글쓴이의 아버지 (Codex)
        intro = _FIRST_PERSON.search(before_s) and _SELF_INTRO_AFTER.match(after_s)
        if not intro \
                and (_CHILD_VIEW.search(para) or not _PARENT_OF_CHILD.search(para)):
            return "other"   # 글쓴이의 부모 — 「아빠가 진짜 싫다고 해서 엄마랑 나랑 옴」. 「나는 아빠가 됐다」(1인칭)는 그대로
    who = _subject_in_sentence(stype, text, channel_text, start, end)
    if who == "self" and stype in ("LOC_ADMIN", "LOC_FACILITY") \
            and (_TRAVEL_IN.search(text.strip()) or _TRAVEL_AFTER.match(channel_text[end:])):
        return "unknown"  # 여행지는 사는 곳이 아니다 — 「일본에 디자인 여행」. 동네 볼일(「농협에 들러」)은 그대로 본인 · 남의 것은 남의 것
    return who


def _subject_in_sentence(stype: str, text: str, channel_text: str, start: int, end: int) -> str:
    before, after = _sentence_window(channel_text, start, end)
    core = _core(text)
    if re.match(r"(?:내|제|나의|저의|우리)(?![가-힣])", text.strip()) or _owned_by_me(before):
        return "self"  # 1인칭 소유 — 「[우리 집에]」 「내 나이 [서른넷을]」
    # ① 스팬 바로 뒤가 타인 → 그 사람의 속성 — 「[아홉 살] 아들」 「[편의점 알바] 언니」 「[동탄] 사는 친구」
    #    관계·시설 단서(「[옆집] 아주머니」 「[이웃] 엄마들」)는 내 관계라 제외. 「[거래처] 사장님」은 내 일의 상대
    #    조사가 붙은 스팬은 사람을 꾸미지 않는다 — 「[역삼동에서] 친구를 만났다」(만난 곳) · 단 「[동탄에] 사는 친구」
    # 1단이 꾸밈말까지 스팬에 넣으면(「[동탄 사는] 친구가」 「[아홉 살 된] 아들」) 꾸밈말을 떼고 같은 규칙을 쓴다
    mod = re.search(r"\s*" + _MODIFIER + r"$", text.strip())
    if mod and len(text.strip()) - len(mod.group(0)) >= 2:
        after = mod.group(0) + after
        text = text.strip()[: len(text.strip()) - len(mod.group(0))]
        core = _core(text)
    bare = _core(text) == text.strip()
    m = _PERSON_AFTER.match(after) if stype in ("AGE", "LOC_ADMIN", "JOB", "INCOME") else None
    if m and not bare and not re.match(r"^\s*" + _MODIFIER, after):
        m = None
    if m and _FIRST_PERSON.search(before) and _COPULA_AFTER.match(after[_person_end(after, m):]):
        m = None  # 「나는 동탄 사는 아빠야」 — 자기소개 (시설 규칙과 같은 예외)
    if m and not (stype == "JOB" and _COUNTERPART.search(m.group(0))):
        return "other"
    # 장소 단서도 「사는 · 살던 + 사람」이 바로 뒤면 그 사람의 거주지 — 1단이 「동탄」을 시설로 잡아도.
    # 「[단골 카페] 사장님」(거주 동사 없음)과 「[옆집] 사는 언니」(옆집 = 내 집 기준 관계)는 본인 단서로 둔다
    rm = _RESIDENT_AFTER.match(after) if stype == "LOC_FACILITY" else None
    # 「나는 동탄 사는 아빠야」(자기소개 — 사람 명사 뒤가 이다)는 본인. 「나는 동탄 사는 친구를 만났다」는 친구의 거주지
    if rm and not (_FIRST_PERSON.search(before) and _COPULA_AFTER.match(after[rm.end():])):
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
            own_predicate = _own_predicate(after)
            # 「양반이 [딸네] 있는 여수로」 「아주머니가 [딸네는] 자주 가셨다」 — 「X네」(그 집)에 주어가 가거나 그 집이
            # 어디 있다는 술어가 오면 주어 쪽 사람의 가족이다 (#308 리뷰). 「사장님이 [언니네] 데려다주셔서」는 내 언니 —
            # 술어가 주어 자신의 이동·거주가 아니면 그대로 둔다 (Codex 10/6). 「우리 딸네」처럼 1인칭이 바로 앞이면 내 것
            hp = _HOUSEHOLD_PRED.match(after) if stype == "FAM" and _HOUSEHOLD.match(text) else None
            if hp and not _household_modifies_me(after, hp.end()) \
                    and not re.search(r"(?:우리|내|제|저희)\s*$", before):
                own_predicate = True
            if _COUNTERPART.search(word) and stype in ("JOB", "COMMUTE", "LOC_FACILITY", "FAM") and not explicit_title \
                    and not own_predicate:
                return "self"  # 단 「사장님이 [약사라서]」 — 직업명 자체는 그 사람 것 · 「사장님은 [2호선으로] 출근한다」는 그 사람 것
            if stype == "FAM" and not re.search(r"친구|동창|동기|선배|후배|동료|지인|아는|이웃|옆집|앞집|윗집|아랫집|원장|사장|손님|양반|반장|선생|아주머니|아저씨|그분|걔|그 사람", word):
                return "self"  # 「아내가 [아이] 데리러」 — 내 가족 구성이다
            if stype == "SEX" and re.search(r"남편|아내|와이프|신랑", word) and level_of(stype, text) != "explicit":
                return "self"  # 관계 호칭은 내 쪽 단서. 「남편은 [남자라서]」(성별이 그대로)는 남편 것  # 배우자가 주어여도 성별 단서는 관계(나의 배우자)다
            return "other"
    return "self"


# 1단이 COMMUTE 로 잘라 잡은 조각 — 어절이 모두 때 말 · 휴가 · 이동 동사 조각 · 조사뿐(「오늘」 「갔다가」 「매일 타는」 「의」).
# 교통 말을 열거하지 않는다 — 목록 밖 새 교통 이름(「GTX로」)이 해를 입지 않게 (exp37 · 38 → exp39). 버리지 않고 unknown(점선)으로만
_RULE_C2 = True
_FRAG_J = r"(?:이|가|은|는|을|를|도|에|에는|에서|로|으로|만|이면|엔|마다|부터|까지|이라|라|인데)?"
_FRAG_W = (r"오늘|내일|어제|모레|매일|매번|평일|주말|아침|저녁|점심|새벽|낮|밤|요즘|오후|오전|당일치기|휴가|여름휴가|휴가철|여행|나들이|답사|일정|일도|"
           r"직장인|체력|월급날|월급|날|목적지|업무|연차|시내|"
           r"갔다가|가서|가기|가는|갈|가|오는|오니|오는데|다니는|다니며|지나가는|돌아가는|돌아오는|타고|타는|타서|탄|나가서|나가는|들어오자마자|"
           r"들어오는|와서|나와|나오는|살고|멀어서|서둘러|이동하기|쓰고|때|길|해서|간|가던|손에|근무|"
           r"의|에|에서|에서도|서|서는|로|으로|고|다|데|대|시|이|은|는|을|를|도|만|와|과|랑|하고|까지|부터|요|죠|첫|낡은")
_FRAG_TOKEN = re.compile(r"(?:" + _FRAG_W + r")" + _FRAG_J)


_FRAG_HABIT = re.compile(r"^(?:매일|매번|평일|주말|요즘)|마다")


def _commute_fragment(text: str) -> bool:
    toks = text.strip().split()
    if not toks or len(toks) > 2 or not all(_FRAG_TOKEN.fullmatch(t) for t in toks):
        return False
    # 어절이 늘면 조각끼리 모여 통근 패턴이 된다(「평일마다 새벽에 나가서 밤에 돌아오는」 · Codex 검토) — 한 어절은 낮추고, 두 어절은 반복 말이 없을 때만
    return len(toks) == 1 or not any(_FRAG_HABIT.search(t) for t in toks)


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
    who = subject_of(stype, text, channel_text, start, end)
    if _RULE_C2 and who == "self" and stype == "COMMUTE" and _commute_fragment(text):
        who = "unknown"
    return {"level": level_of(stype, text), "subject": who}
