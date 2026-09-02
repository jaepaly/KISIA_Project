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
_TRANSIT_AFTER = re.compile(r"^[^\n]{0,6}?(쪽에서 온다는|에서 온다는|에서 오는|가는 버스|가는 차|행 버스|행 열차|행)")

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
    Rule(r"손녀|손주|손자|며느리|사위|큰딸|작은딸|막내|첫째|둘째|우리 애|애들이|딸네|아들네",
         "FAM", "implicit", ""),
    Rule(r"남편|아내|집사람|와이프|우리 영감|할매|아짐|임신|출산|군대 갔", "SEX", "implicit", ""),
    Rule(r"시골서 그냥 소일|소일한다|텃밭|밭일|출근|퇴근|교대 근무|야간 근무|알바|가게 문|손님이",
         "JOB", "inferential", ""),
    Rule(r"\d호선|지하철|출퇴근|통근|자차로", "COMMUTE", "inferential", ""),
]

_SEX_VALUE = {"남편": "F", "우리 영감": "F", "할매": "F", "아짐": "F", "임신": "F", "출산": "F",
              "아내": "M", "집사람": "M", "와이프": "M", "군대 갔": "M"}


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _place_candidates(text: str) -> list[tuple[int, int, str]]:
    """지명 사전(시도·시군구·읍면동)으로 명시 지명을 찾는다. (start, end, canonical)"""
    out: list[tuple[int, int, str]] = []
    for surface, canonical in place_lexicon():
        for m in re.finditer(re.escape(surface), text):
            out.append((m.start(), m.end(), canonical))
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

    for s, e, canonical in _place_candidates(t):
        before, after = t[:s], t[e:]
        subject, level, note = "self", "explicit", {"place": canonical}
        if _OTHER_BEFORE.search(before) or _OTHER_AFTER.search(after):
            subject = "other"
            note["why"] = "타인의 장소 — §4-2 귀속으로 제외"
        elif _PAST_BEFORE.search(before) and _PAST_AFTER.search(after):
            note["exclude"] = "past_residence"
            note["why"] = "「예전에 … 살 때」 — 시제 표지로 과거 거주지 판정, 현 거주지 추정에서 제외"
        elif _TRANSIT_AFTER.search(after):
            level = "inferential"
            note["exclude"] = "transit"
            note["why"] = "이동 경로 언급 — 거주지가 아니라 생활권 힌트. k 계산에 안 넣는다(결합 추론은 2단 몫)"
        cands.append({"text_id": text_id, "start": s, "end": e, "text": t[s:e],
                      "type": "LOC_ADMIN", "level": level, "subject": subject, "score": 0.8})
        notes[f"{s}:{e}"] = note

    for m in _AGE_KO.finditer(t):
        age = parse_age(m.group(0))
        if age is None or age < 10:
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
                note["why"] = "타인에 관한 표현 — §4-2 귀속으로 제외"
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

    spans_out: list[dict[str, Any]] = []
    notes_out: dict[str, dict[str, Any]] = {}
    for i, sp in enumerate(sort_spans(raw), start=1):
        sid = format_span_id(pid, i, text_id=sp["text_id"])
        item = {"span_id": sid, **sp}
        spans_out.append(item)
        n = notes_by_key.get(f"{sp['text_id']}:{sp['start']}")
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
