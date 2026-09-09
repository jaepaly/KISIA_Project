"""1단 스팬 탐지 — 규칙 기반 스탑갭.

⚠️ B 의 KoELECTRA v1 이 나오기 전까지의 자리채움이다. `C1_MODEL_PATH` 가 설정돼 있으면
`kopl.c1_span.predict` (실제 모델) 로 넘기고, 없으면 여기 규칙을 쓴다.

출력 형식은 `docs/contracts/span.schema.json` 그대로다 — 스팬은 `span_id · text_id · start ·
end · text · type · level · subject (· score)` 만 갖는다. 계약에 없는 판단(시제로 걸러낸 과거
거주지, 이동 경로 언급)은 스팬 안이 아니라 별도 `notes` 로 낸다. 계약에 시제 축이 없다는
사실을 D05 인물 설계가 일부러 드러내고 있어서, 여기서도 계약을 늘리지 않고 밖에 둔다.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from .dialect import dialect_hits
from .specificity import place_lexicon

MODEL_VERSION = "demo-rules-0.1.0"

# ── 인물 마커 — 스팬 앞뒤에 있으면 subject=other ─────────────────────────
_OTHER_BEFORE = re.compile(
    r"(양반이|친구|동생|언니|형이|누나|오빠|이웃|아주머니|아저씨|며느리가|사위가|딸네|아들네|"
    r"처남|사장님|손님|그 집|옆집|동무|선배|후배|조카)[^\n]{0,14}$"
)
_OTHER_AFTER = re.compile(
    r"^[^\n]{0,12}?(아주머니|아저씨|양반|친구|동생|언니|형|누나|이웃|손님|사장님|조카|처남)"
)
# 과거 거주 — 시제 표지. 앞에 「예전에·옛날에」, 뒤에 「살 때·살았·살던」
_PAST_BEFORE = re.compile(r"(예전에|옛날에|전에|한때)[^\n]{0,10}$")
_PAST_AFTER = re.compile(r"^[^\n]{0,4}(살 때|살았|살던|살 적)")
# 이동 경로 언급 — 「X 쪽에서 온다는 버스」 「X 가는 버스」 「X행」
_TRANSIT_AFTER = re.compile(
    r"^[^\n]{0,6}?(쪽에서 온다는|에서 온다는|에서 오는|에서 왔다는|에서 온 |쪽으로 지나|쪽으로 가는|쪽으로 향하"
    r"|가는 버스|가는 차|행 버스|행 열차|행)"
)

# ── 한글 수사 나이 ───────────────────────────────────────────────────────
_TENS = {"열": 10, "스물": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60, "일흔": 70, "여든": 80, "아흔": 90}
_ONES = {"하나": 1, "한": 1, "둘": 2, "두": 2, "셋": 3, "세": 3, "넷": 4, "네": 4,
         "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}
_AGE_KO = re.compile(
    r"(열|스물|서른|마흔|쉰|예순|일흔|여든|아흔)(하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉)?"
    r"(?=\s*(살|인디|인데|이다|이네|이고|입니다|이라|이면|이 |$|,|\.))"
)
_AGE_NUM = re.compile(r"(?<![\d])(\d{2})\s*살(?![\d])")
_AGE_DECADE = re.compile(r"(\d)0대\s*(초반|중반|후반)?")


def parse_age(text: str) -> int | None:
    m = _AGE_KO.fullmatch(text.strip())
    if m:
        return _TENS[m.group(1)] + (_ONES.get(m.group(2) or "", 0))
    m = _AGE_NUM.search(text)
    if m:
        return int(m.group(1))
    return None


@dataclass
class Rule:
    pattern: str
    type_: str
    level: str
    note: str = ""
    rx: re.Pattern = field(init=False)

    def __post_init__(self) -> None:
        self.rx = re.compile(self.pattern)


# 유형 10종 — label-schema §3-2. 순서가 곧 우선순위다(최장 일치 후 먼저 온 규칙).
RULES: list[Rule] = [
    # 결합 단서 한 덩어리 — 인물 D05 clue_plan 의 문장 그대로 (지명 0개인데 면 단위를 준다)
    Rule(r"면사무소 앞에서[^\n]{0,20}?한 시간에 한 대라?", "LOC_FACILITY", "inferential", "admin_unit:면"),
    Rule(r"(읍|면)사무소", "LOC_FACILITY", "inferential", "admin_unit:읍면"),
    Rule(r"한 시간에 한 대|한 대 놓치면 [^\n]{0,4}시간|농어촌버스|마을버스가 [^\n]{0,6}(한|두) 대",
         "COMMUTE", "inferential", "rural_bus"),
    Rule(r"경로당", "AGE", "inferential", "age_min:65"),
    Rule(r"오일장|마을회관|우체국|저수지 둑길|저수지|정류장|면사무소|보건소|농협 앞|초등학교 앞",
         "LOC_FACILITY", "inferential", ""),
    Rule(r"집 근처|집 앞|우리 동네|동네 어귀", "REL_HOME", "inferential", ""),
    Rule(r"회사 앞|사무실 근처|공장에서|직장 근처|퇴근하고 바로", "REL_WORK", "inferential", ""),
    Rule(r"달마다 나오는 돈|연금|보조금|월세|시급|월급|정산|성과급|연봉", "INCOME", "implicit", ""),
    Rule(r"방학이라고 [^\n]{0,14}?간다길래|방학이라고 [^\n]{0,10}?온다", "FAM", "implicit", "ambiguous"),
    # 첫째·둘째 뒤에 「날」이 오면 여행 일차다 (둘째날 성산일출봉)
    Rule(r"손녀|손주|손자|며느리|사위|큰딸|작은딸|막내|첫째(?!\s?날)|둘째(?!\s?날)|우리 애|애들이|딸네|아들네",
         "FAM", "implicit", ""),
    Rule(r"남편|(?<![가-힣])아내|집사람|와이프|우리 영감|(?<![가-힣])할매|(?<![가-힣])아짐(?![가-힣])|임신|출산|군대 갔", "SEX", "implicit", ""),
    Rule(r"시골서 그냥 소일|소일한다|텃밭|밭일|출근|퇴근|교대 근무|야간 근무|알바|가게 문|손님",
         "JOB", "inferential", ""),
    Rule(r"\d호선|지하철|출퇴근|통근|자차로", "COMMUTE", "inferential", ""),
]

_SEX_VALUE = {"남편": "F", "우리 영감": "F", "할매": "F", "아짐": "F", "임신": "F", "출산": "F",
              "아내": "M", "집사람": "M", "와이프": "M", "군대 갔": "M"}


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text)


_HANGUL = re.compile(r"[가-힣]")
_ADMIN_SUFFIX = "시군구읍면동리"
# 접미사 없는 약칭(고양·부산·전주) 뒤에 올 수 있는 것 — 행정 접미사·역, 장소 조사, 또는 시설·지형 이름
# (기흥**호수공원**·순천**만**·동탄**신도시** — R1 사례처럼 낚시터·공원 이름이 곧 거주지 단서다).
# 「이·가」는 일부러 뺐다: 「고양이가」「전주가(노래 전주)」 가 지명이 되기 때문이다.
_LOC_NEXT = re.compile(
    r"^(?:[시군구읍면동리역]|에서|에|서|로|으로|까지|부터|쪽|행|발|은|는|도|의|랑|하고|만|과|와|살|사는"
    r"|호수|공원|저수지|시장|터미널|병원|대교|휴게소|해수욕장|항|산|천|강|성당|교회|학교|공단|산업단지|경기장|신도시|시내|읍내|장날)"
)


@lru_cache(maxsize=1)
def _place_rx() -> tuple[re.Pattern, dict[str, str]]:
    """사전 전체를 정규식 하나로 — 긴 표면형이 앞에 오게 정렬돼 있어 같은 자리에서는 긴 것이 이긴다.
    (표면형마다 finditer 를 돌리면 3,700개 × 채널 수만큼 컴파일 캐시가 밀려 스캔 한 번에 4초가 걸렸다)"""
    lex = dict(place_lexicon())
    rx = re.compile("|".join(re.escape(s) for s in lex))
    return rx, lex


def _place_candidates(text: str) -> list[tuple[int, int, str]]:
    """지명 사전(시도·시군구·읍면동)으로 명시 지명을 찾는다. (start, end, canonical)

    경계 규칙 — 코퍼스 실측 오탐(휴대**전화**·사**진도**·저**수지**·**고양**이)을 막는다:
      · 바로 앞에 한글이 붙어 있으면 지명이 아니다 (단어 안쪽 부분 일치)
      · 행정 접미사가 없는 약칭은 뒤에 접미사·역·장소 조사 중 하나가 와야 한다
    """
    rx, lex = _place_rx()
    out: list[tuple[int, int, str]] = []
    for m in rx.finditer(text):
        s, e = m.start(), m.end()
        surface = m.group(0)
        if s > 0 and _HANGUL.match(text[s - 1]):
            continue
        bare = surface[-1] not in _ADMIN_SUFFIX + "도"   # 시도 전체 이름은 시·도로 끝난다
        if bare and e < len(text) and _HANGUL.match(text[e]) and not _LOC_NEXT.match(text[e:e + 3]):
            continue
        out.append((s, e, lex[surface]))
    return out


_GAP = re.compile(r"[  ]{0,2}")


# 여행·출장 글 표지 — 글 안 지명을 방문지로 돌린다
_TRAVEL = re.compile(r"\d\s*박\s*\d\s*일|당일치기|여행|출장|관광|휴가|답사|숙소|호텔|펜션|게스트하우스|공항|기차표|비행기")
_LIVES_AFTER = re.compile(r"^\s*(?:에|에서|서)?\s*(?:사는|살|집|이사|거주|살아)")


def _merge_adjacent_places(text: str, cands: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """「김해시 진영읍」「서울 강남구 역삼동」처럼 공백만 사이에 둔 연속 지명을 스팬 하나로.

    합치는 조건은 «앞 지명을 맥락으로 뒤 지명이 유일하게 풀린다» 뿐이다 — 「부산 서울 왕복」은 안 합친다.
    덤으로 「중앙동」처럼 전국에 여럿인 이름이 앞 시군구로 확정되고, 「경기 광주시」의 동명 문제도 풀린다.
    """
    from kopl.c2_specificity.engine import _get_default_dictionary, resolve

    R = _get_default_dictionary().regions
    cands = sorted(cands)
    out: list[tuple[int, int, str]] = []
    ctx: list[str] = []            # 지금 합치고 있는 덩어리의 앞 지명 정본들
    for s, e, canon in cands:
        if out and _GAP.fullmatch(text[out[-1][1]:s]):
            ps, _pe, pcanon = out[-1]
            pieces = [c for c in (ctx or [pcanon]) if not c.startswith("광주 (")]
            codes = resolve(text[s:e], context=" ".join(pieces) or None)
            if len(codes) == 1:
                out[-1] = (ps, e, R[codes[0]]["full_name"])
                ctx = [*(ctx or [pcanon]), canon]
                continue
        out.append((s, e, canon))
        ctx = [canon]
    return out


def _dedupe_longest(cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cands = sorted(cands, key=lambda c: (-(c["end"] - c["start"]), c["start"]))
    kept: list[dict[str, Any]] = []
    for c in cands:
        if any(not (c["end"] <= k["start"] or c["start"] >= k["end"]) for k in kept):
            continue
        kept.append(c)
    return sorted(kept, key=lambda c: c["start"])


def detect_channel(text: str, text_id: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """채널 하나에서 스팬 후보와 메모(계약 밖 판단)를 낸다. span_id 는 아직 없다."""
    t = normalize(text)
    cands: list[dict[str, Any]] = []
    notes: dict[str, dict[str, Any]] = {}   # "start:end" → note (같은 start 의 짧은 규칙이 긴 규칙 메모를 덮지 않게)

    for s, e, canonical in _merge_adjacent_places(t, _place_candidates(t)):
        before, after = t[:s], t[e:]
        subject, level, note = "self", "explicit", {"place": canonical}
        if _OTHER_BEFORE.search(before) or _OTHER_AFTER.search(after):
            subject = "other"
            note["why"] = "다른 사람의 장소예요. 글쓴이 정보로 세지 않아요"
        elif _PAST_BEFORE.search(before) and _PAST_AFTER.search(after):
            note["exclude"] = "past_residence"
            note["why"] = "「예전에 … 살 때」처럼 과거 이야기예요. 지금 사는 곳으로 세지 않아요"
        elif _TRANSIT_AFTER.search(after):
            level = "inferential"
            note["exclude"] = "transit"
            note["why"] = "지나가는 길이나 오가는 버스 이야기예요. 사는 곳으로 세지 않아요"
        cands.append({"text_id": text_id, "start": s, "end": e, "text": t[s:e],
                      "type": "LOC_ADMIN", "level": level, "subject": subject, "score": 0.8})
        notes[f"{s}:{e}"] = note

    for m in _AGE_KO.finditer(t):
        age = parse_age(m.group(0))
        if age is None or age < 10:
            continue
        if m.group(0) == "열" and not re.match(r"\s*살", t[m.end():]):   # 「열이 나서」 — 열은 「열 살」 일 때만 나이다
            continue
        cands.append({"text_id": text_id, "start": m.start(), "end": m.end(), "text": m.group(0),
                      "type": "AGE", "level": "explicit", "subject": "self", "score": 0.9})
        notes[f"{m.start()}:{m.end()}"] = {"age": age}
    for m in _AGE_NUM.finditer(t):
        cands.append({"text_id": text_id, "start": m.start(), "end": m.end(), "text": m.group(0),
                      "type": "AGE", "level": "explicit", "subject": "self", "score": 0.9})
        notes[f"{m.start()}:{m.end()}"] = {"age": int(m.group(1))}
    for m in _AGE_DECADE.finditer(t):
        cands.append({"text_id": text_id, "start": m.start(), "end": m.end(), "text": m.group(0),
                      "type": "AGE", "level": "explicit", "subject": "self", "score": 0.85})
        notes[f"{m.start()}:{m.end()}"] = {"age_decade": int(m.group(1)) * 10}

    for rule in RULES:
        for m in rule.rx.finditer(t):
            s, e = m.start(), m.end()
            subject = "other" if _OTHER_BEFORE.search(t[:s]) else "self"
            c = {"text_id": text_id, "start": s, "end": e, "text": t[s:e],
                 "type": rule.type_, "level": rule.level, "subject": subject, "score": 0.75}
            cands.append(c)
            note: dict[str, Any] = {}
            if rule.note.startswith("admin_unit:"):
                note["admin_unit"] = rule.note.split(":", 1)[1]
            elif rule.note.startswith("age_min:"):
                note["age_min"] = int(rule.note.split(":", 1)[1])
            elif rule.note == "ambiguous":
                note["ambiguous"] = True
            if rule.type_ == "SEX":
                for k, v in _SEX_VALUE.items():
                    if k in c["text"]:
                        note["sex"] = v
            if subject == "other":
                note["why"] = "다른 사람 이야기예요. 글쓴이 정보로 세지 않아요"
            if note:
                notes.setdefault(f"{s}:{e}", {}).update(note)

    kept = _dedupe_longest(cands)
    kept_notes = {f"{text_id}:{c['start']}": notes.get(f"{c['start']}:{c['end']}", {}) for c in kept}
    return kept, kept_notes


def _channels_of(post: dict[str, Any]) -> dict[str, str]:
    ch: dict[str, str] = {}
    if post.get("title"):
        ch["title"] = post["title"]
    ch["body"] = post.get("body") or ""
    for i, ph in enumerate(post.get("photos") or []):
        if ph.get("caption"):
            ch[f"photo_caption:{i}"] = ph["caption"]
    return ch


def _use_real_model() -> bool:
    p = os.getenv("C1_MODEL_PATH")
    return bool(p and os.path.exists(p))


def detect_post(post: dict[str, Any]) -> dict[str, Any]:
    """export 의 글 하나 → span.schema.json 레코드 + notes.

    반환: {"record": <계약 레코드>, "notes": {span_id: {...}}, "texts": {text_id: text}}
    """
    from kopl.c1_span import format_span_id, sort_spans   # 계약 정렬·ID 규약은 B 의 코드를 쓴다

    pid = post["post_id"]
    texts = _channels_of(post)

    if _use_real_model():
        from kopl.c1_span import predict
        rec = predict({"post_id": pid, "texts": texts})
        rec.setdefault("flags", {})["dialect_hits"] = sum((dialect_hits(t) for t in texts.values()), [])
        return {"record": rec, "notes": {}, "texts": texts}

    raw: list[dict[str, Any]] = []
    notes_by_key: dict[str, dict[str, Any]] = {}
    for tid, txt in texts.items():
        spans, notes = detect_channel(txt, tid)
        raw.extend(spans)
        notes_by_key.update(notes)

    # 여행·출장 글의 지명은 방문지다 — 「사는·살·집」이 바로 뒤에 붙은 것만 거주지로 남긴다 (글 단위 판단, 2단 몫의 근사)
    travel = any(_TRAVEL.search(t) for t in texts.values())
    spans_out: list[dict[str, Any]] = []
    notes_out: dict[str, dict[str, Any]] = {}
    for i, sp in enumerate(sort_spans(raw), start=1):
        sid = format_span_id(pid, i, text_id=sp["text_id"])
        item = {"span_id": sid, **sp}
        spans_out.append(item)
        n = dict(notes_by_key.get(f"{sp['text_id']}:{sp['start']}") or {})
        if travel and sp["type"] == "LOC_ADMIN" and sp["subject"] == "self" and not n.get("exclude") \
                and not _LIVES_AFTER.match(texts[sp["text_id"]][sp["end"]:]):
            n["exclude"] = "travel"
            n["why"] = "여행이나 출장 글이라 다녀온 곳으로 봐요. 사는 곳으로 세지 않아요"
        if n:
            notes_out[sid] = n

    record = {
        "schema_version": "1.0",
        "model_version": MODEL_VERSION,
        "record_type": "post",
        "post_id": pid,
        "spans": spans_out,
        "flags": {
            "gen_signal": False,   # 세대 신호는 안 본다 — 스탑갭. 계약상 불리언이라 null 이 아니다
            "meme_hits": [],
            "dialect_hits": sum((dialect_hits(t) for t in texts.values()), []),
        },
    }
    return {"record": record, "notes": notes_out, "texts": texts}


def detect_profile(user_ref: str, bio: str | None) -> dict[str, Any]:
    from kopl.c1_span import format_span_id, sort_spans

    texts = {"profile_bio": bio or ""}
    if not bio:
        return {"record": None, "notes": {}, "texts": texts}
    spans, notes = detect_channel(bio, "profile_bio")
    out, notes_out = [], {}
    for i, sp in enumerate(sort_spans(spans), start=1):
        sid = format_span_id(None, i, text_id="profile_bio", persona_id=user_ref)
        out.append({"span_id": sid, **sp})
        n = notes.get(f"profile_bio:{sp['start']}")
        if n:
            notes_out[sid] = n
    record = {
        "schema_version": "1.0",
        "model_version": MODEL_VERSION,
        "record_type": "profile",
        "persona_id": user_ref,
        "spans": out,
        "flags": {"gen_signal": False, "meme_hits": [], "dialect_hits": dialect_hits(bio)},
    }
    return {"record": record, "notes": notes_out, "texts": texts}
