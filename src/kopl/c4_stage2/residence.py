"""해외 거주 판별 — 글쓴이 본인이 해외에 사는 것으로 보이는가 (PM 결정 10/26).

후보 수(k)는 국내 주민등록 인구로 센다. 해외에 사는 사람의 글에서 「미국」 「시카고」는 국내 사전에 없어 빠지고,
지명과 글자가 같은 일반 낱말(「예산」 「음성」)만 남아 사는 곳을 「한국의 어느 읍면동」으로 정해 버린다.
그래서 해외 거주로 보이면 **사는 곳은 추정하지 않는다** — 분석 앱이 위치 단서를 k · 위험도 · 2단 location 판정에서 뺀다.
나이 · 성별 · 가족 · 직업 등 나머지는 그대로 센다.

판별은 보수적으로 한다 — 해외로 잘못 보면 국내 거주자의 사는 곳 단서를 통째로 놓친다.

    거주 표현(R) — 외국 지명 + 거주 술어 : 「미국에서 지내다 보니」 「미국생활」 「캐나다에 살고 있다」 「일본 온 지 3년」
                   지명 없는 거주 낱말   : 「주재원」 「이민 온」 「워홀」 「해외 생활」 「외국살이」
                   지명 + 「n주차 · n개월차」 : 「시드니 4주차」 (여행은 「n일차」로 세서 넣지 않았다)
        같은 문장에 여행 · 출장 표현(「여행」 「다녀왔다」 「출장」 「2박」 …)이 있으면 세지 않는다
        과거 · 바람 · 가정(「살았을 때」 「유학 시절」 「살아 보고 싶다」 「이민 가고 싶다」)은 세지 않는다
        남이 주어(「동생이 미국에 산다」 「친구는 캐나다에서 지낸다」)면 세지 않는다
        「미국 와서」 「일본 온 뒤」 처럼 도착만 말하는 표현은 그 글 어디에도 여행 · 출장 표현이 없을 때만 센다
    반복(F)     — 거주 표현과 같은 나라의 지명이 여행 표현 없는 문장으로 다른 글에도 나온다
    국내 거주(K) — 국내 지명(1단 본인 위치 스팬 · 「한국」) + 현재 거주 술어 : 「망원동에 산 지 5년」 「한국에 살고 있다」 · 「귀국했다」

    해외 = (R 글 2편 이상  또는  R 글 1편 + 같은 나라를 말한 다른 글 2편 이상)  그리고  R 글 수 > K 글 수

글 한 편만으로는 해외로 보지 않는다(실시간 글쓰기 점검 · 여행기 한 편). 지명이 나오기만 하는 것(뉴스 · 「미국 주식」 · 여행기)은
거주 표현이 없으므로 아무리 반복돼도 해외가 아니다.

    from kopl.c4_stage2.residence import find_residence
    find_residence({"p1": {"title": "...", "body": "..."}}, {"p1": [span, ...]})
    → {"overseas": bool, "country": "미국" | "해외" | None, "posts": {...}, "evidence": [...], "korea_evidence": [...]}

외국 지명 목록은 여기서만 쓰는 작은 목록이다(나라 · 미국 주 · 주요 도시). 지명 사전(geo-dictionary)과 무관하다.
글자가 일반 낱말과 겹치는 이름(「인도」 보도 · 「파리」 곤충 · 「조지아」 나라/주)은 넣지 않았다.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

# ── 외국 지명 → 나라 ────────────────────────────────────────────────────
_PLACES: dict[str, tuple[str, ...]] = {
    "미국": (
        "미국", "뉴욕", "엘에이", "로스앤젤레스", "샌프란시스코", "시카고", "시애틀", "보스턴", "애틀랜타", "휴스턴",
        "댈러스", "달라스", "라스베이거스", "샌디에이고", "필라델피아", "포틀랜드", "덴버", "마이애미", "호놀룰루",
        "실리콘밸리", "어바인", "오스틴", "피츠버그", "디트로이트", "새너제이", "산호세",
        "캘리포니아", "텍사스", "뉴저지", "일리노이", "플로리다", "버지니아", "메릴랜드", "매사추세츠", "펜실베이니아",
        "오하이오", "미시간", "하와이", "알래스카", "애리조나", "콜로라도", "오리건", "오레곤", "네바다", "미네소타",
        "위스콘신", "인디애나", "노스캐롤라이나", "사우스캐롤라이나", "테네시", "켄터키", "미주리", "아이오와", "캔자스",
        "유타", "코네티컷", "앨라배마", "루이지애나", "오클라호마", "워싱턴주",
    ),
    "캐나다": ("캐나다", "토론토", "밴쿠버", "몬트리올", "캘거리", "오타와", "에드먼턴"),
    "일본": ("일본", "도쿄", "오사카", "교토", "후쿠오카", "삿포로", "요코하마", "나고야", "오키나와"),
    "중국": ("중국", "베이징", "상하이", "칭다오", "광저우", "선전시"),
    "대만": ("대만", "타이베이", "타이완"),
    "홍콩": ("홍콩",),
    "싱가포르": ("싱가포르", "싱가폴"),
    "베트남": ("베트남", "하노이", "호치민", "다낭"),
    "태국": ("태국", "방콕", "치앙마이"),
    "필리핀": ("필리핀", "마닐라"),
    "인도네시아": ("인도네시아", "자카르타", "발리"),
    "말레이시아": ("말레이시아", "쿠알라룸푸르"),
    "호주": ("호주", "시드니", "멜버른", "멜번", "브리즈번"),
    "뉴질랜드": ("뉴질랜드",),
    "영국": ("영국", "런던", "맨체스터", "에든버러"),
    "프랑스": ("프랑스",),
    "독일": ("독일", "베를린", "뮌헨", "프랑크푸르트", "함부르크"),
    "스페인": ("스페인", "바르셀로나", "마드리드"),
    "이탈리아": ("이탈리아", "밀라노"),
    "네덜란드": ("네덜란드", "암스테르담"),
    "스위스": ("스위스", "취리히"),
    "유럽": ("오스트리아", "스웨덴", "덴마크", "노르웨이", "핀란드", "아일랜드", "더블린", "체코", "프라하", "벨기에",
            "포르투갈", "폴란드", "헝가리"),
    "러시아": ("러시아", "모스크바"),
    "중남미": ("멕시코", "브라질", "아르헨티나", "칠레", "페루"),
    "중동": ("두바이", "아랍에미리트", "사우디", "카타르", "이스라엘", "튀르키예", "터키", "이스탄불"),
    "아시아": ("몽골", "카자흐스탄", "우즈베키스탄", "캄보디아", "라오스", "미얀마", "네팔"),
    "해외": ("해외", "외국", "타국", "이국"),   # 나라를 말하지 않은 해외 — 거주 표현에만 쓴다
}
_COUNTRY = {name: country for country, names in _PLACES.items() for name in names}
_LATIN = {"LA": "미국", "NYC": "미국"}   # 영문 약칭 — 앞뒤가 영문자가 아니고 「LA갈비」가 아닐 때만

# 지명 바로 뒤에 붙어도 지명으로 보는 말 — 조사 · 「생활 · 살이 · 일상」. 그 밖의 한글이 붙으면 다른 낱말이다
# (「미국산」 「일본어」 「중국집」 「대만족」 「호주머니」 「미국인」 「독일식」 「캐나다구스」)
_PARTICLE = r"(?:에서는|에서도|에서의|에서|에선|에는|에도|에|으로|로|은|는|이|가|도|의|엔)"
_NOUN_TAIL = r"(?:생활|살이|일상|거주|교포|교민|이민|정착)"
_HANGUL = "가-힣"

_names = sorted(_COUNTRY, key=len, reverse=True)
_PLACE_RE = re.compile(
    rf"(?<![{_HANGUL}])(?P<place>{'|'.join(map(re.escape, _names))})(?=$|[^{_HANGUL}]|{_PARTICLE}|{_NOUN_TAIL})"
    rf"|(?<![A-Za-z])(?P<latin>LA|NYC)(?![A-Za-z]|\s*갈비)"
)

# ── 거주 술어 (지명 + 조사 뒤) ──────────────────────────────────────────
_ADV = r"(?:\s*(?:지금|현재|이제|벌써|계속|직접|아직|여기|이곳|이렇게|오래)\s*)?"
# 강한 거주 — 사는 것 자체를 말한다
_STRONG_PRED = re.compile(
    r"\s*" + _PARTICLE + r"?" + _ADV + r"\s*"
    r"(?P<pred>(?:생활|살이|일상)"                                   # 미국생활 · 미국 생활 · 미국살이 · 미국일상
    r"|살(?:고|아|면서|다\s*보|면|게\s*된|기\s*시작|림)"                # 살고 있다 · 살아요 · 살면서 · 살다 보니
    r"|삽니다|산다|산\s*지|산지"
    r"|\d+\s*(?:주|개월|달|년)\s*차"                                  # 시드니 4주차 — 여행은 「n일차」로 센다
    r"|사는\s*(?:중|동안|곳)"
    r"|지내(?:고|다\s*보|면서|는\s*중|요)|지냅니다|지낸\s*지"
    r"|거주|정착)"
)
# 도착 — 「미국 와서」 「일본 온 지 3년」. 여행 첫날에도 쓰는 말이라 글에 여행 표현이 없을 때만 센다(「온 지 + 기간」은 강하게)
_ARRIVE_PRED = re.compile(   # 「미국에서 와서」(거기서 왔다)는 거꾸로라 조사는 에 · 로만
    r"\s*(?:에|으로|로)?" + _ADV + r"\s*"
    r"(?P<pred>(?:와서|온\s*뒤|온\s*후|오고\s*나서|건너와|건너온|이사\s*와|이사\s*온|이사왔|넘어와|넘어온|왔을\s*때"
    r"|온\s*지|온지))"
)
_SINCE_DURATION = re.compile(r"\s*(?:\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|몇|반)\s*(?:년|해|달|개월|주)")
# 지명 없이도 해외 거주를 말하는 낱말
_STANDALONE = re.compile(
    r"(?P<pred>주재원"
    r"|이민\s*(?:와|온|와서|생활|간\s*지|1세대|2세대)|워홀|워킹\s*홀리데이"
    r"|해외\s*(?:생활|살이|거주|이주)|외국\s*(?:생활|살이)|타국\s*(?:생활|살이))"
)

# 문장 안에 있으면 그 표현을 세지 않는 말
_TRAVEL = re.compile(
    r"여행|관광|출장|휴가|놀러|다녀\s*(?:왔|온|오|갔)|갔다\s*(?:왔|온)|갔다왔|신혼|\d+\s*박|박\s*\d+\s*일|일정|투어|여행지"
    r"|호텔|숙소|비행기|공항|입국|출국|며칠|당일치기|경유|면세"
)
_TRAVEL_POST = re.compile(r"여행|관광|출장|휴가|놀러|다녀\s*(?:왔|온)|\d+\s*박|박\s*\d+\s*일|호텔|숙소|당일치기")
# 술어 바로 뒤 — 과거 · 바람 · 가정 · 계획
_AFTER_BAD = re.compile(
    r"^\s*(?:때|당시|갔|가기|가려|가서|준비|비자)|^.{0,10}?(?:았|었|던|했던|했을|할\s*때|하던|시절|싶|보고\s*싶|면\s*좋|려고|려면|예정|계획|준비|까\s*고민|게\s*되면|된다면|본다면"
    r"|봤|본\s*적|볼까|보기로|가고\s*싶|좋겠|좋을)"
)
# 술어 앞(같은 문장) — 남이 주어 · 가정 · 과거 시점
_OTHER_SUBJ = re.compile(
    r"(?:동생|형|누나|언니|오빠|친구|아들|딸|자녀|부모님|엄마|아빠|어머니|아버지|사촌|이모|고모|삼촌|외삼촌|지인|선배|후배|조카"
    r"|친척|이웃|동료|그분|그 사람|걔|쟤|분들|사람들)(?:이|가|은|는|도|네|분|께서|들은|들이)(?:\s|$)"
)
_BEFORE_BAD = re.compile(r"언젠가|나중에|만약|혹시|꿈|로망|예전에|옛날에|어릴\s*때|대학\s*때|학생\s*때|유학\s*시절|그때|당시")

# ── 국내 거주 ──────────────────────────────────────────────────────────
_KOREA_PRED = re.compile(
    r"^\s*" + _PARTICLE + r"?" + _ADV + r"\s*"
    r"(?P<pred>살고\s*있|살고|살아요|살아서|살면서|삽니다|산다|산\s*지|산지|사는\s*(?:중|동안|곳|동네|집)"
    r"|거주\s*중|거주하|거주합|이사\s*와|이사\s*온|이사왔|정착)"
)
_KOREA_TEXT = re.compile(r"(?<![가-힣])(?P<place>한국|국내|우리나라)(?=에|에서)")
# 「한국」은 해외 거주자도 지난 시절로 많이 말한다(「한국에 살면서는 몰랐다」) — 지금 산다는 말만
_KOREA_TEXT_PRED = re.compile(r"^\s*(?:에서|에)\s*(?:지금\s*|현재\s*)?(?P<pred>살고\s*있|삽니다|산다|사는\s*중|거주\s*중|거주하고)")
_RETURNED = re.compile(r"(?P<pred>귀국\s*(?:했|한\s*지|한지|하고\s*나서|후|한\s*뒤|해서))")
_LOC_TYPES = ("LOC_ADMIN", "LOC_FACILITY", "REL_HOME")

_SENT_END = re.compile(r"[.!?\n。…~]|ㅋㅋ|ㅎㅎ|ㅠㅠ")


def _sentence(text: str, start: int, end: int) -> tuple[str, str]:
    """매치 앞뒤의 같은 문장 조각 (앞 최대 40자 · 뒤 최대 30자)."""
    lo = max(0, start - 40)
    before = text[lo:start]
    cut = [m.end() for m in _SENT_END.finditer(before)]
    if cut:
        before = before[cut[-1]:]
    after = text[end:end + 30]
    m = _SENT_END.search(after)
    if m:
        after = after[:m.start()]
    return before, after


def _ok_context(text: str, start: int, end: int) -> bool:
    before, after = _sentence(text, start, end)
    if _TRAVEL.search(before) or _TRAVEL.search(after) or _TRAVEL.search(text[start:end]):
        return False
    if _OTHER_SUBJ.search(before) or _BEFORE_BAD.search(before):
        return False
    if _AFTER_BAD.search(after):
        return False
    return True


def _hit(post_id: str, text_id: str, text: str, start: int, end: int, kind: str, country: str | None) -> dict[str, Any]:
    return {"post_id": post_id, "text_id": text_id, "start": start, "end": end, "value": text[start:end],
            "kind": kind, "country": country}


def _abroad_hits(post_id: str, texts: Mapping[str, str]) -> tuple[list[dict], list[dict]]:
    """→ (거주 표현, 지명 언급). 지명 언급은 여행 표현 없는 문장만."""
    travel_post = any(_TRAVEL_POST.search(t) for t in texts.values())
    residence, mentions = [], []
    for tid, text in texts.items():
        for m in _PLACE_RE.finditer(text):
            name = m.group("place") or m.group("latin")
            country = _COUNTRY.get(name) or _LATIN.get(name)
            s, e = m.start(), m.end()
            rest = text[e:]
            strong = _STRONG_PRED.match(rest)
            arrive = None if strong else _ARRIVE_PRED.match(rest)
            if strong or arrive:
                pm = strong or arrive
                pe = e + pm.end()
                since = arrive is not None and arrive.group("pred").replace(" ", "") in ("온지",)
                if since and not _SINCE_DURATION.match(text[pe:]):
                    since = False
                if _ok_context(text, s, pe) and (strong or since or not travel_post):
                    residence.append(_hit(post_id, tid, text, s, pe, "residence", country))
                    continue
            if country != "해외":
                before, after = _sentence(text, s, e)
                if not (_TRAVEL.search(before) or _TRAVEL.search(after)):
                    mentions.append(_hit(post_id, tid, text, s, e, "mention", country))
        for m in _STANDALONE.finditer(text):
            if _ok_context(text, m.start(), m.end()):
                residence.append(_hit(post_id, tid, text, m.start(), m.end(), "residence", "해외"))
    return residence, mentions


def _korea_hits(post_id: str, texts: Mapping[str, str], spans: Sequence[Mapping[str, Any]]) -> list[dict]:
    """국내 지명 + 현재 거주 술어 · 「귀국했다」. 국내 지명은 1단 본인 위치 스팬(외국 지명이 아닌 것)과 「한국」."""
    out = []
    places: list[tuple] = []   # (text_id, start, end[, 술어 정규식])
    for s in spans:
        if s.get("type") not in _LOC_TYPES or s.get("subject") == "other":
            continue
        tid, st, en = s.get("text_id"), s.get("start"), s.get("end")
        text = texts.get(tid) if isinstance(tid, str) else None
        if text is None or not isinstance(st, int) or not isinstance(en, int):
            continue
        if _PLACE_RE.search(text[st:en]):     # 1단이 외국 지명을 LOC_ADMIN 으로 잡은 것 — 국내 단서가 아니다
            continue
        places.append((tid, st, en))
    for tid, text in texts.items():
        places.extend((tid, m.start(), m.end(), _KOREA_TEXT_PRED) for m in _KOREA_TEXT.finditer(text))
    seen = set()
    for tid, st, en, *pred in places:
        text = texts[tid]
        m = (pred[0] if pred else _KOREA_PRED).match(text[en:])
        if not m or (tid, st) in seen:
            continue
        pe = en + m.end()
        if _ok_context(text, st, pe):
            seen.add((tid, st))
            out.append(_hit(post_id, tid, text, st, pe, "korea_residence", "한국"))
    for tid, text in texts.items():
        for m in _RETURNED.finditer(text):
            if _ok_context(text, m.start(), m.end()):
                out.append(_hit(post_id, tid, text, m.start(), m.end(), "returned", "한국"))
    return out


def find_residence(posts: Mapping[str, Mapping[str, str]],
                   spans_by_post: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                   *, max_evidence: int = 5) -> dict[str, Any]:
    """``posts``: {post_id: {text_id: 원문}} · ``spans_by_post``: {post_id: [1단 스팬]} (국내 거주 단서용 · 없어도 된다).

    오프셋은 NFC 로 맞춘 원문 기준(1단 스팬과 같다).
    """
    spans_by_post = spans_by_post or {}
    abroad: dict[str, list[dict]] = {}
    mention: dict[str, list[dict]] = {}
    korea: dict[str, list[dict]] = {}
    for pid, raw in posts.items():
        texts = {k: unicodedata.normalize("NFC", v) for k, v in (raw or {}).items() if isinstance(v, str) and v}
        r, f = _abroad_hits(pid, texts)
        k = _korea_hits(pid, texts, list(spans_by_post.get(pid) or []))
        if r:
            abroad[pid] = r
        if f:
            mention[pid] = f
        if k:
            korea[pid] = k
    # 나라 — 거주 표현이 가장 많은 글에 걸친 나라 (「해외」는 나라가 없을 때만)
    by_country = Counter(h["country"] for hs in abroad.values() for h in {h["country"]: h for h in hs}.values()
                         if h["country"] != "해외")
    country = by_country.most_common(1)[0][0] if by_country else ("해외" if abroad else None)
    same = {pid for pid, hs in mention.items()
            if pid not in abroad and any(country in (None, "해외") or h["country"] == country for h in hs)}
    n_r, n_f, n_k = len(abroad), len(same), len(korea)
    overseas = (n_r >= 2 or (n_r >= 1 and n_f >= 2)) and n_r > n_k
    if not overseas:
        rule = ("거주 표현 없음" if n_r == 0 else
                "국내 거주 단서가 같거나 더 많음" if n_r <= n_k else "거주 표현이 글 1편뿐")
    else:
        rule = "거주 표현 글 2편 이상" if n_r >= 2 else "거주 표현 1편 + 같은 나라 반복"
    return {
        "overseas": overseas,
        "country": country if overseas else None,
        "rule": rule,
        "posts": {"residence": sorted(abroad), "mention": sorted(same), "korea": sorted(korea)},
        "evidence": [h for pid in sorted(abroad) for h in abroad[pid]][:max_evidence],
        "korea_evidence": [h for pid in sorted(korea) for h in korea[pid]][:max_evidence],
    }
