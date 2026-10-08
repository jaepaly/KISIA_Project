"""W7 명시 AGE·LOC_ADMIN 보강 후보를 찾는다.

규칙은 골드나 test 결과를 받지 않는다. 반환값은 문자 오프셋과 유형이며,
모델 후보와의 무겹침 병합·평가는 별도 단계에서 수행한다.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from kopl.c2_specificity.engine import RegionDictionary
from prepare_bio import channel_sort_key
import train


_TENS = r"(?:스무|스물|서른|마흔|쉰|예순|일흔|여든|아흔)"
_ONES = r"(?:다섯|여섯|일곱|여덟|아홉|하나|둘|셋|넷|한|두|세|네)"
# 나이 뒤 조사·어미 — 「마흔여덟에 퇴직」 「마흔여덟이다」 「서른셋이었다」 「스물다섯인 동생」 (#322 ②).
# 「에서 · 부터 · 까지」는 뺀다 — 「(나무를 세다) 스물셋에서 그만뒀다」 「하나부터 스물까지」처럼 셈에 더 자주 붙는다 (Codex 10/8).
# 정규식 대안은 앞에서부터 맞으므로 **긴 것부터** 둔다 — 「이」가 먼저 맞으면 「이다」의 「다」에서 단어 경계에 걸려 통째로 버려진다
_AGE_ENDINGS = sorted({
    "입니다", "이에요", "이었다", "이었고", "이었는데", "이었지", "였다", "였고", "였는데", "이다", "이고", "인데", "이야",
    "이지", "이라", "이던", "에는", "에도", "즈음", "쯤", "에", "인", "임", "은", "는", "이", "가",
    "도", "만"}, key=lambda e: (-len(e), e))
_AGE_ENDING = r"(?:" + "|".join(_AGE_ENDINGS) + r")?"
_AGE_PATTERNS = (
    re.compile(r"(?<![가-힣A-Za-z0-9])(?:[1-9][0-9]?\s*(?:살|세)|[0-9]{2}년생)" + _AGE_ENDING),
    re.compile(r"(?<![가-힣A-Za-z0-9])" + _TENS + r"(?:\s*" + _ONES + r")?(?:\s*(?:살|세))?" + _AGE_ENDING),
    re.compile(r"(?<![가-힣A-Za-z0-9])" + _ONES + r"(?:\s*살|\s+세)" + _AGE_ENDING),
)
# 수 뒤에 단위가 오면 나이가 아니다 — 「서른 번」 「마흔 명에게」 「스무 개짜리」. 줄바꿈은 건너지 않는다 —
# 「나이는 서른⏎개발자로」의 「개」는 다음 줄 첫 글자다 (Codex 10/6)
_QUANTITY_FOLLOWERS = re.compile(r"[ \t]*(?:번|개월|개|명|분|마리|원|장|그릇|잔)")
# 기간·횟수 단위도 같다 — 「서른 해보다」(근속 30년) 「쉰 날」(쉬다 + 날) 「스무 해 동안」 「스물세 권이나」 (인스턴스 테스트 10/5).
# 단위 글자가 다른 말의 첫 글자일 수 있어(「벌써」 「해서」 「주고」) 뒤가 조사·끝일 때만 단위로 본다
_DURATION_FOLLOWERS = re.compile(
    r"\s*(?:해|날|년|달|주|일|시간|가지|곳|군데|권|벌|채|그루|송이|칸|층|평|켤레|통)"  # 「줄」은 뺀다 — 「서른 줄에 접어들다」는 나이
    r"(?=$|[^가-힣]|(?:보다|동안|이나|나|만|도|은|는|이|가|을|를|에|째|쯤|씩|간|의|하고|까지|부터|이나마)(?:$|[^가-힣]))")
# 「나이 48에」 — 숫자 나이는 「살·세」가 없으면 위 패턴이 못 잡는다. 「나이」 바로 뒤의 두 자리 수만 (스팬은 수 + 어미)
_AGE_AFTER_NAI = re.compile(r"(?<![가-힣A-Za-z0-9])나이(?:는|가|도)?\s*(?P<age>[1-9][0-9]"
                            r"(?:에는|에|때|입니다|이에요|이고|인데|이야|이지|이라|임|은|는|이|가|도|만)?)(?![0-9가-힣])")
# 소득 금액 — 금액은 물건값과 섞이므로 같은 문장에 수입을 뜻하는 말이 있을 때만 (「월급 삼백이십만 원」 「연금 백사십만 원」)
_KNUM = r"(?:[일이삼사오육칠팔구]?천)?(?:[일이삼사오육칠팔구]?백)?(?:[일이삼사오육칠팔구]?십)?[일이삼사오육칠팔구]?"
_AMOUNT = re.compile(r"(?<![가-힣A-Za-z0-9])(?:(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|" + _KNUM + r")\s*(?:만|억)\s*원?"
                     r"|\d{1,3}(?:,\d{3}){2,}\s*원)")
# 수입 명사와 「벌다」만 — 「받다·들어오다」는 택배·월세·대출 문장에도 와서 뺀다 (Codex 검토 10/5)
_INCOME_CONTEXT = re.compile(r"월급|연봉|급여|실수령|월수입|수입|시급|일당|벌이|벌어|번다|벌었|연금|수당|매출|순수익|정산|"
                             r"인센티브|성과급|보너스|알바비|원고료|강사료|강의료|출연료|상여금|사례비|품삯|용돈|월세 수입")  # 「보수·상여」는 뜻이 갈려 뺀다
_SENTENCE = re.compile(r"(?:[^.!?\n]|(?<=\d)\.(?=\d))+")  # 「300.5만 원」의 점은 문장 끝이 아니다
_WORD = re.compile(r"[가-힣]+")
_REGION_SUFFIXES = ("특별자치시", "특별자치도", "특별시", "광역시", "도", "시", "군", "구")
_PARTICLES = tuple(sorted({"으로부터", "에서부터", "에게서는", "에게서", "에서는", "으로", "에서",
                           "부터", "까지", "이라서", "이라고", "이며", "이라", "이고", "에는",
                           "으로는", "로는", "에는", "은", "는", "이", "가", "을", "를",
                           "에", "도", "만", "로", "와", "과", "랑"}, key=len, reverse=True))
# train 검수 골드 331편에서 일반 명사·동사로 쓰여 불일치한 행정구역명/약칭.
# 실제 지명으로도 쓰일 수 있어 v1+규칙 결과의 한계로 기록한다.
TRAIN_AMBIGUOUS_TERMS = frozenset({"동안", "고양", "내면", "동작", "이동", "서면", "경기", "전주",
                                   "수정", "도면", "상하", "상하면"})  # 「수정 요청」 「도면 계획」 「(음식이) 상하면」 — 지명보다 일반어로 훨씬 자주 쓴다 (#322 ②)
# 지명과 같은 꼴의 일반 명사 — 단어째 빼면 「진도에 놀러 갔다」 「구미에서 일한다」까지 놓치므로, **바로 뒤가 관용 표현일 때만** 거른다 (#322 ②).
# pattern.match(text, pos) 로 쓰므로 ^ 를 붙이지 않는다 — ^ 는 pos 가 아니라 문자열 맨 앞에서만 맞는다.
# 바로 앞이 도 이름이면(「경기도 화성」 「경북 구미」 「전남 진도」) 거르지 않는다 (Codex 10/8)
_PROVINCE_BEFORE = re.compile(r"(?:경기도?|강원도?|충청[남북]도|충[남북]|전라[남북]도|전[남북]|경상[남북]도|경[남북]|제주도?|"
                              r"[가-힣]+특별자치도)\s*$")
_SIDO_SHORT = {"경북": "경상북도", "경남": "경상남도", "충북": "충청북도", "충남": "충청남도", "전남": "전남광주통합특별시"}
# 일반어로 훨씬 자주 쓰는 지명 — 거꾸로 「지명 문맥이 있을 때만」 지명으로 본다 (실제 글 시험 10/8 · #322 ②).
# 「업무 진도는」 「공부 진도가 밀렸다」 「목표 달성을」은 지명이 아니다. 뒤에 「군·대교·여행」이나 이동·거주 말이 오거나,
# 앞에 도·광역시 이름이 오면(「전남 진도」 「대구 달성」) 지명
_PLACE_MOVE = r"(?:에|에서|로|으로)\s*(?:가|갔|간|갈|놀러|여행|살|사는|산다|살아|내려|이사|왔|와|오|있|도착|들러|들렀|출장|발령|근무)"
_CONTEXT_ONLY_PLACES = {
    "진도": re.compile(r"(?:군|항)|\s*(?:대교|여행|아리랑|개(?![가-힣]))|" + _PLACE_MOVE),  # 「진도 항상」은 「항」 앞 띄어쓰기를 안 받아 거른다
    "달성": re.compile(r"군|\s*(?:공원|습지)|" + _PLACE_MOVE),
}
_PACE_BEFORE = re.compile(r"(?:^|[^가-힣])(?:이|그|저|지금|이런|그런|요즘)\s*$")  # 「이 진도로 가면」 — 속도 이야기
_CITY_BEFORE = re.compile(r"(?:대구|대구시|대구광역시)\s*$")
_HOMONYM_IDIOM = {
    "구미": re.compile(r"(?:가|를|도|는)?\s*(?:당기|당겨|당긴|당길|당김|당겼|돋|안\s*당)|에\s*맞(?:는|게|다|아|지|춰|추)"),
    "화성": re.compile(r"\s*(?:탐사|착륙|궤도|이주|로버|탐험)|의\s*(?:대기|위성|궤도)"  # 우주 탐사 말만 — 「화성 토양」은 화성시일 수 있다
                     r"|을\s*(?:탐사|탐험)|에\s*(?:착륙|가는\s*로켓|사람을)"),
}


_AGE_CLOSED = re.compile(r"살|년생|\d\s*세|\s세|(?:" + "|".join(_AGE_ENDINGS) + r")$")


def _is_bare_number(matched: str) -> bool:
    """「서른」 「쉰」처럼 단위·어미 없이 수만 있나. 「스물세」의 「세」는 수(3)라 맨몸이다."""
    return not _AGE_CLOSED.search(matched)


_HAS_AGE_UNIT = re.compile(r"살|세|년생")
# 「스물에 한 번 당첨」 — 뒤에 빈도가 오면 나이가 아니다
_FREQUENCY_AFTER = re.compile(r"\s*(?:한|두|세|네|몇|여러)\s*(?:번|차례)")
# 「총개수는 스물이다」 「점수는 마흔이다」 — 개수·점수를 말하는 말 바로 뒤의 수는 나이가 아니다
_COUNT_BEFORE = re.compile(r"(?:개수|갯수|총|합계|합이|점수|등수|숫자|번호|순위|인원|횟수|회차|페이지|쪽수|몇\s*개)"
                           r"\s*(?:는|은|가|이|도|만|로|으로)?\s*$")


def age_spans(text: str) -> set[tuple[int, int, str]]:
    """나이 표현을 찾되 수량 표현과 긴 단어의 일부는 버린다."""
    found: set[tuple[int, int, str]] = set()
    for pattern in _AGE_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if end < len(text) and re.match(r"[가-힣A-Za-z0-9]", text[end]):
                continue
            if _QUANTITY_FOLLOWERS.match(text, end):
                continue
            if _is_bare_number(text[start:end]) and _DURATION_FOLLOWERS.match(text, end):
                continue  # 「서른 해」 「쉰 날」만 — 「23살이고 일을」 「서른 살이고 해가」는 나이가 이미 끝났다 (#309 리뷰)
            if not _HAS_AGE_UNIT.search(text[start:end]) and (
                    _FREQUENCY_AFTER.match(text, end) or _COUNT_BEFORE.search(text[max(0, start - 12):start])):
                continue  # 「스물에 한 번」 「총개수는 스물이다」 — 「살·세」가 붙은 「총 마흔 살」은 나이 그대로 (#322 ② · Codex 10/8)
            found.add((start, end, "AGE"))
    for match in _AGE_AFTER_NAI.finditer(text):
        found.add((match.start("age"), match.end("age"), "AGE"))
    return found


def income_spans(text: str) -> set[tuple[int, int, str]]:
    """수입을 뜻하는 말이 있는 문장 안의 금액 — 「월급 삼백이십만 원」. 물건값(「커피 4,500원」)은 문장에 수입 말이 없어 빠진다."""
    found: set[tuple[int, int, str]] = set()
    for sentence in _SENTENCE.finditer(text):
        if not _INCOME_CONTEXT.search(sentence.group()):
            continue
        for match in _AMOUNT.finditer(sentence.group()):
            value = match.group().rstrip()
            if value.strip() in ("만", "억", "만 원", "억 원", "만원", "억원"):
                continue
            start = sentence.start() + match.start()
            found.add((start, start + len(value), "INCOME"))
    return found


class ExplicitRules:
    """행정구역 사전을 재사용하며 채널별 명시 단서 후보를 반환한다."""

    def __init__(self, dictionary: RegionDictionary | None = None,
                 excluded_aliases: Iterable[str] = ()) -> None:
        self.dictionary = dictionary or RegionDictionary()
        self.excluded_aliases = TRAIN_AMBIGUOUS_TERMS | frozenset(excluded_aliases)
        self.names: set[str] = set()
        self.aliases: set[str] = set()
        for region in self.dictionary.regions.values():
            names = {region["name"], *region.get("aliases", [])}
            self.names.update(name for name in names if len(name) >= 2 and name not in self.excluded_aliases)
            if region["level"] not in {"sido", "sigungu"}:
                continue
            for name in names:
                for suffix in _REGION_SUFFIXES:
                    if name.endswith(suffix):
                        alias = name[:-len(suffix)]
                        if len(alias) >= 2 and alias not in self.excluded_aliases:
                            self.aliases.add(alias)
                        break
        # 도 약칭 — 「경상북도」에서 「도」만 떼면 「경상북」이 돼 「경북」이 안 생긴다 (#322 ②). 사전에 그 도가 있을 때만 넣는다
        sido = {region["name"] for region in self.dictionary.regions.values() if region["level"] == "sido"}
        for short, full in _SIDO_SHORT.items():
            if full in sido and short not in self.excluded_aliases:
                self.aliases.add(short)

    def location_spans(self, text: str) -> set[tuple[int, int, str]]:
        found: set[tuple[int, int, str]] = set()
        for match in _WORD.finditer(text):
            word = match.group()
            for particle in ("", *_PARTICLES):
                if particle and not word.endswith(particle):
                    continue
                name = word[:-len(particle)] if particle else word
                place_ctx = _CONTEXT_ONLY_PLACES.get(name)
                if place_ctx is not None:
                    window = text[max(0, match.start() - 10):match.start()]
                    if _PACE_BEFORE.search(window) or not (place_ctx.match(text, match.start() + len(name))
                                                           or _PROVINCE_BEFORE.search(window) or _CITY_BEFORE.search(window)):
                        break  # 「업무 진도는」 「목표 달성을」 — 지명 문맥이 없으면 일반어
                idiom = _HOMONYM_IDIOM.get(name)
                if idiom and idiom.match(text, match.start() + len(name)) \
                        and not _PROVINCE_BEFORE.search(text[max(0, match.start() - 10):match.start()]):
                    break  # 「진도가 안 나간다」 「구미가 당기는」 「화성 탐사」 — 지명이 아니다
                if name in self.names and self.dictionary.resolve(name):
                    found.add((match.start(), match.end(), "LOC_ADMIN"))
                    break
                if name in self.aliases:
                    found.add((match.start(), match.end(), "LOC_ADMIN"))
                    break
                # 법정동 이름 — 「봉천동 · 망원동」은 행정동 목록(names)에 없지만 사전이 해석한다 (#322 ② · exp17 놓침 6/12).
                # 세 글자 이상 · 「~동 · ~읍」만 — 「~리 · ~면 · ~가」는 「모서리 · 목소리」처럼 일반어와 같은 마을 이름이 많아
                # 오탐이 5→75 로 늘었다. 「판교」처럼 「동」 없는 줄임말도 일반어 오탐(「방학이」)이 커서 넣지 않는다
                if len(name) >= 3 and name[-1] in "동읍" and name not in self.excluded_aliases \
                        and self.dictionary.resolve(name):
                    found.add((match.start(), match.end(), "LOC_ADMIN"))
                    break
        return found

    def predict_channel(self, text: str) -> set[tuple[int, int, str]]:
        return age_spans(text) | self.location_spans(text) | income_spans(text)


_NUMERAL = r"(?:\d{1,3}|" + _TENS + r"(?:\s*" + _ONES + r")?|" + _ONES + r")"
_UNIT_WORD = r"(?:번|개|명|분|마리|원|장|그릇|잔|해|날|년|달|주|일|시간|가지|곳|군데|권|벌|채|그루|송이|칸|층|평|켤레|통)"
# 스팬 끝에 붙은 조사·어미까지 — 「스무 해에」 「스무 해였다」 「쉰 날간」 (Codex 10/6). 아무 글자나 열면 「스물 일곱」을
# 「스물 + 일(단위) + 곱」으로 읽으므로 목록만 허용한다
_UNIT_TAIL = (r"(?:동안|넘게|째|쯤|씩|이나|나|만|도|은|는|이|가|을|를|의|에|에는|에서|에도|간|간의|보다|까지|부터|하고|어치"
              r"|였다|였고|였는데|였지|이었다|이었고|이다|이고|이라|인데|째인)")
_NUMERAL_WITH_UNIT = re.compile(_NUMERAL + r"\s*" + _UNIT_WORD + r"(?:\s*" + _UNIT_TAIL + r")?")


def is_quantity_age(text: str, start: int, end: int) -> bool:
    """모델이 AGE 로 낸 스팬이 실은 수량·기간인가 — 「스무 해」(스팬에 단위) · 「서른」+「 해 동안」(뒤에 단위).

    규칙 후보는 age_spans 가 이미 거른다. 재학습 모델은 이 거름이 없어 exp17 숫자 함정 7/15 를 나이로 잡았다.
    """
    span = text[start:end].strip()
    if re.fullmatch(_NUMERAL, span):  # 수만 — 「스물 일곱」은 여기서 나이로 읽힌다(단위 「일」로 보지 않음)
        return bool(_QUANTITY_FOLLOWERS.match(text, end) or _DURATION_FOLLOWERS.match(text, end))
    return bool(_NUMERAL_WITH_UNIT.fullmatch(span))  # 「스무 해」 「스무 해에」 — 그 밖(「서른 살이고」)은 나이


def merge_with_model(
    post_id: str,
    texts: dict[str, str],
    model_candidates: list[dict],
    detector: ExplicitRules,
) -> tuple[list[dict], dict[str, int]]:
    """모델·규칙 후보를 같은 최장 우선 무겹침 정책으로 채널별 병합한다.

    후보의 출처는 계약 스팬에 넣지 않고 별도 통계로만 반환한다. 규칙 후보에는
    모델 확률이 없으므로 score를 만들어 붙이지 않는다. 원본 모델 후보도 바꾸지 않는다.
    """
    if not isinstance(post_id, str) or not post_id:
        raise ValueError("post_id가 필요합니다.")
    by_channel: dict[str, dict[tuple[int, int, str], dict]] = {tid: {} for tid in texts}
    model_keys: set[tuple[str, int, int, str]] = set()
    quantity_dropped = 0
    for candidate in model_candidates:
        tid, start, end, kind = (candidate[key] for key in ("text_id", "start", "end", "type"))
        if (tid not in texts or not isinstance(start, int) or not isinstance(end, int)
                or not 0 <= start < end <= len(texts[tid])
                or texts[tid][start:end] != candidate.get("text")):
            raise ValueError(f"모델 후보의 채널·문자 경계가 잘못됐습니다: {post_id}/{tid}")
        key = (tid, start, end, kind)
        if key in model_keys:
            raise ValueError(f"모델 후보가 중복됐습니다: {post_id}/{tid}")
        if kind == "AGE" and is_quantity_age(texts[tid], start, end):
            quantity_dropped += 1  # 「서른 해 동안」 — 나이가 아니라 기간
            continue
        model_keys.add(key)
        span = {"start": start, "end": end, "text": candidate["text"], "type": kind}
        if "score" in candidate:
            span["score"] = candidate["score"]
        by_channel[tid][(start, end, kind)] = span

    rule_keys: set[tuple[str, int, int, str]] = set()
    for tid, text in texts.items():
        for start, end, kind in detector.predict_channel(text):
            if not 0 <= start < end <= len(text):
                raise ValueError(f"규칙 후보의 문자 경계가 잘못됐습니다: {post_id}/{tid}")
            rule_keys.add((tid, start, end, kind))
            by_channel[tid].setdefault((start, end, kind),
                                       {"start": start, "end": end, "text": text[start:end], "type": kind})

    output: list[dict] = []
    selected_keys: set[tuple[str, int, int, str]] = set()
    for tid in sorted(texts, key=channel_sort_key):
        selected = train.resolve_overlapping_spans(by_channel[tid])
        for start, end, kind in sorted(selected):
            selected_keys.add((tid, start, end, kind))
            output.append({**by_channel[tid][(start, end, kind)], "text_id": tid,
                           "span_id": f"{post_id}_s{len(output) + 1:02d}"})
    stats = {
        "model_input": len(model_keys),
        "rule_proposed": len(rule_keys),
        "union_unique": len(model_keys | rule_keys),
        "selected": len(selected_keys),
        "selected_model_only": len(selected_keys & (model_keys - rule_keys)),
        "selected_rule_only": len(selected_keys & (rule_keys - model_keys)),
        "selected_both": len(selected_keys & model_keys & rule_keys),
        "suppressed_by_overlap": len(model_keys | rule_keys) - len(selected_keys),
        "model_age_quantity_dropped": quantity_dropped,
    }
    return output, stats
