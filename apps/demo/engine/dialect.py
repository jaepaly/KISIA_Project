"""방언 사전 매칭 — 글 단위 플래그 `flags.dialect_hits` 를 낸다.

label-schema §7 · stage2-io `DocFlags.dialect_hits` 의 스탑갭이다.
정본 사전은 A 소유 `data/dict/signatures/dialect.json` 인데 아직 없다.
그때까지 인물 설계서(D05 voice.방언)에 못 박힌 «널리 쓰이는 어휘» 만 쓴다.

⚠️ 어휘 단위 매칭이다. 문장 전체 문체는 보지 않는다 — 스팬화가 되는 건 어휘뿐이다.
"""

from __future__ import annotations

import re

# 권역 → (표기, 정규식). 정규식은 어미가 붙는 형태를 허용한다.
_LEXICON: dict[str, list[tuple[str, str]]] = {
    "호남": [
        ("어매", r"어매"),
        ("시방", r"시방"),
        ("겁나", r"겁나"),
        ("뭣이", r"뭣이"),
        ("그라제", r"그라제"),
        ("~는디", r"[가-힣]는디"),
        ("~드라고", r"드라고"),
        ("~부텀", r"[가-힣]부텀"),
        ("~당께", r"당께"),
        ("~겄다", r"겄[다지]"),
    ],
    "영남": [
        ("~카이", r"[가-힣]카이"),
        ("머라카노", r"머라카노"),
        ("억수로", r"억수로"),
        ("~데이", r"[가-힣]데이(?![가-힣])"),
        ("~니더", r"니더"),
        ("~심더", r"심더"),
        ("아이가", r"아이가(?![가-힣])"),
    ],
    "충청": [
        # 종결 위치만 — 「옮겨 갔다」 「이유」 같은 일반어에 걸리지 않게 문장 끝 부호를 요구한다
        ("~유", r"[가-힣]유[.!?~…\n]"),
        ("~겨", r"[가-힣]겨[.!?~…\n]"),
        ("워쩐댜", r"워쩐댜"),
    ],
    "강원": [
        ("~드래요", r"드래요"),
        ("마카", r"마카(?![가-힣])"),
    ],
    "제주": [
        ("~수다", r"[가-힣]수다(?![가-힣])"),
        ("~마씸", r"마씸"),
        ("혼저", r"혼저"),
        ("게난", r"게난"),
    ],
}

_COMPILED = {
    region: [(label, re.compile(pat)) for label, pat in items]
    for region, items in _LEXICON.items()
}

# 권역 → 시도 이름. regions.json 의 sido.name 과 같아야 한다.
REGION_SIDOS: dict[str, tuple[str, ...]] = {
    "호남": ("전남광주통합특별시", "전북특별자치도"),
    "영남": ("부산광역시", "대구광역시", "울산광역시", "경상북도", "경상남도"),
    "충청": ("대전광역시", "세종특별자치시", "충청북도", "충청남도"),
    "강원": ("강원특별자치도",),
    "제주": ("제주특별자치도",),
}


def dialect_hits(text: str) -> list[str]:
    """`권역:표기` 문자열 목록. 같은 어휘는 한 번만 센다."""
    hits: list[str] = []
    for region, items in _COMPILED.items():
        for label, rx in items:
            if rx.search(text):
                hits.append(f"{region}:{label}")
    return hits


def dominant_region(all_hits: list[str], min_hits: int = 3) -> str | None:
    """여러 글의 hits 를 합쳐 권역 하나를 고른다. 어휘 종류가 min_hits 미만이면 None."""
    counts: dict[str, set[str]] = {}
    for h in all_hits:
        region, _, label = h.partition(":")
        counts.setdefault(region, set()).add(label)
    if not counts:
        return None
    region, labels = max(counts.items(), key=lambda kv: len(kv[1]))
    return region if len(labels) >= min_hits else None
