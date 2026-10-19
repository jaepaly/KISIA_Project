"""exp30 공용 — 셋 불러오기 · 교사 프롬프트 v3 · 판정 적용 (README §1 · §2).

셋: d1c(exp29 판정셋) · d4(교사 라벨 골드 300편) · pool(학습 풀 — 코퍼스 test 밖 − D2 − D3 − D4) · aug(함정 보강 합성 글)
"""
from __future__ import annotations

import glob
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP29 = ROOT / "experiments" / "exp29-media-place-rule"
LABELS = ("self", "other", "unknown", "drop")

TYPES = """(label-schema §3-2 — 무엇을 잡나 · 예)
- AGE: 나이 · 연령대 신호 (마흔여덟 / 서른넷 / 90년생)
- SEX: 성별 신호 (아내가 / 남편이 / 와이프)
- LOC_ADMIN: 행정구역명 (성수동 / 용인 / 기흥)
- LOC_FACILITY: 시설 · 랜드마크 · 상호 (신갈저수지 / 서울숲 / 성수역)
- REL_HOME: 거주 관계어 (집 근처 / 집 앞 / 동네 / 우리 동네)
- REL_WORK: 직장 관계어 (회사 앞 / 사무실 근처 / 공장에서)
- JOB: 직업 · 직무 · 업종 (생산관리 / 완성차 공장 / 카페 매니저)
- FAM: 가족 구성 · 생애단계 (첫째가 고등학교 배정 / 손주 돌잔치)
- COMMUTE: 교통수단 · 노선 · 통근 패턴 · 통근 관계어 (2호선 / 자차 출퇴근 / 퇴근길)
- INCOME: 소비 · 지출 수준 신호 (장비 값 / 회비 / 등급제)"""

# v2(exp28b)에서 계약과 어긋난 두 곳만 고쳤다 — subject 기본값 · 가족 호칭, 다녀온 곳 · 매체 속 장소 (README §1)
RULES = """단서의 정의 (label-schema §4-1 — 세 등급 모두 단서다):
- explicit: 값이 그대로 적힘 (마흔여덟 / 2호선)
- implicit: 값이 직접 안 적혔으나 문맥상 거의 확정 (완성차 공장 출장 / 원두 발주)
- inferential: 단독으로는 미확정이지만 다른 단서와 묶이면 좁혀짐 (신갈저수지 / 집 근처)
→ 값이 직접 적히지 않은 간접적인 말도 위 범주를 드러내면 단서다

후보마다 하나를 고른다 (그 후보가 속한 문장만 보고 정한다 — label-schema §4-2):
- self (기본): 문장이 남의 것이라고 밝히지 않았으면 self. 글쓴이가 사는 곳 · 일하는 곳 · 자주 가는 곳 · 직접 다녀온 곳은 모두 self
  · 배우자 · 형제 · 자녀 등 가족 호칭(아내가 · 남편 · 누나가 · 형이 · 아들)은 글쓴이의 성별 · 가족을 드러내므로 self
- other: 문장이 명시적으로 남에게 돌릴 때만 (친구가 사는 송도 · 언니가 은행원 · 옆집 아저씨 · 동료가 쉰 살)
  · 글쓴이의 부모를 가리키는 엄마 · 아빠 · 어머니 · 아버지가 성별(SEX) 후보로 잡혔으면 other
- unknown: 여행 · 놀러 · 휴가 · 관광 · 출장 같은 말이 직접 꾸미는 여행지 / 드라마 · 영화 · 뉴스 · 유튜브 등 매체 속 장소(글쓴이가 가지 않은 곳) / 그 밖에 문장만으로 누구 것인지 알 수 없을 때
- drop (좁게): 그 말이 글쓴이 · 다른 사람 누구에 대해서도 위 범주를 드러내지 않을 때만 — 유행어 · 평가말 · 농담처럼 쓰인 말, 고유명사가 아닌 일반어가 장소로 잡힌 것. 애매하면 drop 하지 않는다"""

SYSTEM = "너는 한국어 SNS 글에서 글쓴이를 특정할 수 있는 개인 단서를 검토하는 사람이다. 반드시 JSON 하나만 출력한다."


def prompt(batch: list[tuple[str, str, list[dict]]]) -> str:
    """batch = [(키, 본문, 후보)] — 후보의 subject 는 보여 주지 않는다(받은 값을 되풀이하지 않게)."""
    parts = []
    for key, body, spans in batch:
        listed = "\n".join(f"{i}. 「{s['text']}」 {s['type']}" for i, s in enumerate(spans, 1))
        parts.append(f"[글 {key}]\n{body}\n\n[글 {key} 의 후보]\n{listed}")
    keys = ", ".join(f'"{k}": {{"1": "self|other|unknown|drop", …}}' for k, _, _ in batch)
    return (f"단서 유형:\n{TYPES}\n\n{RULES}\n\n" + "\n\n".join(parts)
            + f"\n\n할 일: 글마다 모든 후보 번호에 self · other · unknown · drop 중 하나를 정하라.\n출력 형식: {{{keys}}}")


PROMPT_HASH = hashlib.sha256((SYSTEM + TYPES + RULES + prompt([("X", "X", [{"text": "X", "type": "AGE"}])])).encode()).hexdigest()[:12]


def parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        return None


def decisions(v: dict | None, key: str, n: int) -> list[str] | None:
    """후보 n 개의 판정. 하나라도 빠지거나 값이 이상하면 None (그 글은 학습 · 채점에서 파싱 실패로 센다)."""
    if not isinstance(v, dict) or not isinstance(v.get(key), dict):
        return None
    d = v[key]
    out = [d.get(str(i)) for i in range(1, n + 1)]
    return out if all(x in LABELS for x in out) else None


def apply(spans: list[dict], dec: list[str] | None) -> list[dict]:
    if dec is None:
        return spans
    return [dict(s, subject=d) for s, d in zip(spans, dec) if d != "drop"]


def _test() -> set[str]:
    t = set(json.load(open(ROOT / "data/corpus/v0/splits/test_post_ids.json", encoding="utf-8"))["post_ids"])
    assert len(t) == 255
    return t


def _ids(name: str) -> set[str]:
    return set(json.load(open(HERE / "data" / f"{name}_post_ids.json", encoding="utf-8"))["post_ids"])


def _gold_rows() -> dict[str, dict]:
    rows = {}
    for f in sorted(glob.glob(str(ROOT / "data/corpus/v0/gold/*_spans.jsonl"))):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            if d.get("post_id") and "spans" in d:
                rows[d["post_id"]] = d
    return rows


def load(name: str) -> list[dict]:
    """[{post_id, body}] — body 만 쓴다."""
    if name == "d1c":
        rows = [json.loads(l) for l in open(EXP29 / "data" / "posts.jsonl", encoding="utf-8")]
        return [{"post_id": r["post_id"], "body": r["texts"]["body"]} for r in rows if not r.get("excluded")]
    if name == "aug":
        rows = [json.loads(l) for l in open(HERE / "data" / "aug_posts.jsonl", encoding="utf-8")]
        return [{"post_id": r["post_id"], "body": r["texts"]["body"]} for r in rows if not r.get("excluded")]
    if name == "d4":
        want, gold = _ids("d4"), _gold_rows()
        rows = [{"post_id": p, "body": gold[p]["texts"]["body"]} for p in sorted(want)]
        assert len(rows) == 300
        return rows
    if name == "pool":
        test, gold = _test(), _gold_rows()
        d2 = {p for p, d in gold.items() if d.get("reviewed")}
        out = test | d2 | _ids("d3") | _ids("d4")
        rows = []
        for f in sorted(glob.glob(str(ROOT / "data/corpus/v0/posts/*.jsonl"))):
            for line in open(f, encoding="utf-8"):
                d = json.loads(line)
                body = d.get("texts", {}).get("body")
                if d["post_id"] not in out and body:
                    rows.append({"post_id": d["post_id"], "body": body})
        return rows
    raise ValueError(name)


def gold_d4() -> dict[str, list[dict]]:
    want, gold = _ids("d4"), _gold_rows()
    return {p: [s for s in gold[p]["spans"] if s["text_id"] == "body"] for p in want}
