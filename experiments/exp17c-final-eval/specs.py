"""exp17c: 1단 교체 후보 최종 판정용 평가셋 명세 — 기준선 v2 와 후보(C그룹 + o-weight 0.05)를 **한 번씩만** 잰다 (#322 · DEC-011).

exp17 은 개발용(오답을 봤고 후보를 고르는 데 썼다), exp17b 는 기준선 v2 를 한 번 쟀다(10/8). 후보를 exp17 로 골랐으니
같은 설계의 **새 값 · 새 표현**으로 다시 만든다. 구성은 exp17b 와 같다:
- **노린 변이 · 새 값** (group=targeted): exp17 · exp17b · exp19(학습 변이 글)와 같은 종류지만 값이 모두 다르다
- **노리지 않은 변이** (group=untargeted): exp19 가 만들지 않은 형태(출생 연도 · 연령대 · 생애 사건 · 생활권 별칭 · 시도 정식 ·
  랜드마크 · 지점명 · 직업 묘사 · 시가·처가 호칭 · 배우자 별칭 · 철도 노선 · 셔틀 · 세후 · 구어 금액)를 새 값으로
- 새 값의 타인 함정 · 숫자 함정

겹침: exp17 · exp17b 의 심은 표현과 exp19(AUG1) 의 정답 스팬 — **어느 쪽이 다른 쪽을 품어도(부분 문자열) 겹침으로 본다** (`overlap_check`)
⚠️ 채점은 기준선 · 후보를 같은 날 **한 번만** 하고, 오답을 열어 고치지 않는다.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

SEED = 20261009
N_POSTS = 80


@dataclass(frozen=True)
class Clue:
    text: str
    type: str
    level: str
    subject: str
    variant: str
    group: str        # targeted / untargeted / trap
    span: str = ""


T, U = "targeted", "untargeted"
SELF = [
    # ── 노린 변이 · 새 값
    Clue("나이 63에", "AGE", "explicit", "self", "숫자나이", T, "63에"), Clue("29살인데", "AGE", "explicit", "self", "숫자나이", T),
    Clue("쉰여덟이야", "AGE", "explicit", "self", "반말어미", T), Clue("서른아홉임", "AGE", "explicit", "self", "반말어미", T),
    Clue("올해 일흔하나", "AGE", "explicit", "self", "한글수사", T, "일흔하나"), Clue("스물다섯이고", "AGE", "explicit", "self", "한글수사", T),
    Clue("의정부 민락동", "LOC_ADMIN", "explicit", "self", "시구", T), Clue("파주 운정동", "LOC_ADMIN", "explicit", "self", "시구", T),
    Clue("광명 철산동", "LOC_ADMIN", "explicit", "self", "시구", T), Clue("김해 장유동", "LOC_ADMIN", "explicit", "self", "시구", T),
    Clue("길음동", "LOC_ADMIN", "explicit", "self", "동", T), Clue("화곡동", "LOC_ADMIN", "explicit", "self", "동", T),
    Clue("월급 삼백오십만 원", "INCOME", "explicit", "self", "금액", T), Clue("연봉 3,300만", "INCOME", "explicit", "self", "금액", T),
    Clue("합정역 7번 출구", "LOC_FACILITY", "explicit", "self", "역", T), Clue("을지로 노가리골목", "LOC_FACILITY", "explicit", "self", "상가", T),
    Clue("사회복지사로", "JOB", "explicit", "self", "직업명", T), Clue("제빵사로", "JOB", "explicit", "self", "직업명", T),
    Clue("7호선으로", "COMMUTE", "explicit", "self", "노선", T), Clue("472번 버스", "COMMUTE", "explicit", "self", "버스", T),
    # ── 노리지 않은 변이 (새 값)
    Clue("01년생", "AGE", "explicit", "self", "출생연도", U), Clue("79년생이라", "AGE", "explicit", "self", "출생연도", U),
    Clue("50대 중반", "AGE", "explicit", "self", "연령대", U), Clue("정년퇴직을 앞두고", "AGE", "implicit", "self", "생애사건", U, "정년퇴직을"),
    Clue("목동 사는", "LOC_ADMIN", "explicit", "self", "생활권별칭", U, "목동"), Clue("송파 토박이", "LOC_ADMIN", "explicit", "self", "생활권별칭", U, "송파"),
    Clue("전라남도 바닷가", "LOC_ADMIN", "explicit", "self", "시도정식", U, "전라남도"),
    Clue("N서울타워", "LOC_FACILITY", "explicit", "self", "랜드마크", U), Clue("홈플러스 동대문점", "LOC_FACILITY", "explicit", "self", "지점명", U),
    Clue("손님 머리 커트", "JOB", "implicit", "self", "직업묘사", U), Clue("물류센터 야간 분류", "JOB", "implicit", "self", "직업묘사", U),
    Clue("시누이랑", "FAM", "implicit", "self", "시가처가", U), Clue("장모님이", "FAM", "implicit", "self", "시가처가", U),
    Clue("친손자", "FAM", "implicit", "self", "가족", U),
    Clue("애들 엄마가", "SEX", "implicit", "self", "배우자별칭", U), Clue("신랑이", "SEX", "implicit", "self", "배우자별칭", U),
    Clue("공항철도로", "COMMUTE", "explicit", "self", "철도노선", U), Clue("회사 셔틀로", "COMMUTE", "implicit", "self", "셔틀", U),
    Clue("세후 310", "INCOME", "explicit", "self", "세후", U), Clue("한 달에 280 받아", "INCOME", "explicit", "self", "구어금액", U, "한 달에 280"),
]
TRAPS = [
    Clue("윗집 아저씨는 일흔둘", "AGE", "explicit", "other", "타인나이", "trap", "일흔둘"),
    Clue("이모가 광주 서구에", "LOC_ADMIN", "explicit", "other", "타인거주", "trap", "광주 서구에"),
    Clue("형 직업이 경찰이라", "JOB", "explicit", "other", "타인직업", "trap", "경찰이라"),
    Clue("직장 동료는 군포에 살고", "LOC_ADMIN", "explicit", "other", "타인거주", "trap", "군포에"),
    Clue("예순여섯인 반장님", "AGE", "explicit", "other", "타인나이", "trap", "예순여섯인"),
]
DISTRACTORS = ["열한 시", "예순 장", "스물세 개", "마흔 바퀴", "서른 분"]
VOICES = ["반말 SNS 말투", "존댓말 블로그 말투", "짧은 혼잣말 말투", "어르신 블로그 말투", "20대 커뮤니티 말투"]
TOPICS = ["퇴근 뒤", "주말 오후", "비 오는 아침", "장보기", "카페", "운동", "청소", "택배", "늦잠", "새로 산 물건",
          "날씨", "점심", "출근길", "명절", "미용실", "이사 정리", "산책", "친구 만난 날"]


def build() -> list[dict]:
    rng = random.Random(SEED)
    pool = SELF[:]
    out = []
    for i in range(N_POSTS):
        if i % len(pool) == 0:
            rng.shuffle(pool)
        clues = [pool[i % len(pool)]]
        if rng.random() < 0.45:
            clues.append(rng.choice([c for c in SELF if c.type != clues[0].type]))
        if rng.random() < 0.3:
            clues.append(rng.choice(TRAPS))
        distractor = rng.choice(DISTRACTORS) if rng.random() < 0.2 else None
        out.append({"post_id": f"P17C_{i + 1:03d}", "voice": rng.choice(VOICES), "topic": rng.choice(TOPICS),
                    "clues": [{**asdict(c), "span": c.span or c.text} for c in clues], "distractor": distractor})
    return out


def overlap_check(root) -> list[tuple[str, str]]:
    """exp17 · exp17b 심은 표현 · AUG1 정답 스팬과 부분 문자열로라도 겹치는 새 표현 → [(새 표현, 기존 표현)]"""
    import json
    from pathlib import Path

    root = Path(root)
    used: set[str] = set()
    for f in ("experiments/exp17-planted-eval/data/posts.jsonl", "experiments/exp17b-heldout-eval/data/posts.jsonl"):
        for line in (root / f).read_text(encoding="utf-8").splitlines():
            if line.strip():
                g = json.loads(line)
                used |= {c["text"] for c in g["planted"]} | {c.get("clue") or c["text"] for c in g["planted"]}
                used |= {d["text"] for d in g.get("distractors", [])}
    for line in (root / "data/corpus/aug/v1/AUG1_spans.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line) if line.strip() else {}
        used |= {s["text"] for s in r.get("spans", [])}
    new = {c.text for c in SELF + TRAPS} | {c.span for c in SELF + TRAPS if c.span} | set(DISTRACTORS)
    # 두 글자 이하 기존 표현(「사는」「동네」)은 너무 흔해 겹침 판단에서 뺀다
    return sorted((n, u) for n in new for u in used if len(u) >= 3 and (n in u or u in n))


if __name__ == "__main__":
    import collections
    import json
    from pathlib import Path

    posts = build()
    g = collections.Counter(c["group"] for p in posts for c in p["clues"])
    t = collections.Counter(f"{c['type']}/{c['subject']}" for p in posts for c in p["clues"])
    print(json.dumps({"posts": len(posts), "clues": sum(g.values()), "by_group": dict(g), "by_type": dict(sorted(t.items())),
                      "distractors": sum(1 for p in posts if p["distractor"]),
                      "overlap": overlap_check(Path(__file__).resolve().parents[2])}, ensure_ascii=False, indent=1))
