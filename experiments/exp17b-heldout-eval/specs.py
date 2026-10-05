"""exp17b: 최종 판정용 평가셋 명세 — 변이 글 재학습(#313)의 효과를 **한 번만** 잰다.

exp17 은 오답을 들여다봤고 exp19(학습 변이 글)와 같은 설계라 개발용이 됐다. exp17b 는
- **노린 변이 · 새 값** (group=targeted): exp17·exp19 와 같은 종류(숫자 나이 · 금액 · 시·구 …)지만 값이 모두 다르다 → 일반화
- **노리지 않은 변이** (group=untargeted): exp19 가 만들지 않은 표현(출생 연도 · 연령대 · 생활권 별칭 · 랜드마크 ·
  지점명 · 직업 묘사 · 시가·처가 호칭 · 배우자 별칭 · 광역버스·자차 · 실수령) → 과적합 여부
- 새 형태의 타인 함정 · 숫자 함정

⚠️ 채점은 #313 재학습 결과가 나온 뒤 **한 번만** 하고, 오답을 열어 고치지 않는다.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

SEED = 20261008
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
    Clue("나이 57에", "AGE", "explicit", "self", "숫자나이", T, "57에"), Clue("33살인데", "AGE", "explicit", "self", "숫자나이", T),
    Clue("마흔다섯이야", "AGE", "explicit", "self", "반말어미", T), Clue("서른넷임", "AGE", "explicit", "self", "반말어미", T),
    Clue("올해 예순둘", "AGE", "explicit", "self", "한글수사", T, "예순둘"), Clue("스물일곱이고", "AGE", "explicit", "self", "한글수사", T),
    Clue("김포 사우동", "LOC_ADMIN", "explicit", "self", "시구", T), Clue("구리 인창동", "LOC_ADMIN", "explicit", "self", "시구", T),
    Clue("평택 고덕동", "LOC_ADMIN", "explicit", "self", "시구", T), Clue("세종 나성동", "LOC_ADMIN", "explicit", "self", "시구", T),
    Clue("신림동", "LOC_ADMIN", "explicit", "self", "동", T), Clue("구로동", "LOC_ADMIN", "explicit", "self", "동", T),
    Clue("월급 이백구십만 원", "INCOME", "explicit", "self", "금액", T), Clue("연봉 2,900만", "INCOME", "explicit", "self", "금액", T),
    Clue("봉급 350만 원", "INCOME", "explicit", "self", "금액", T),
    Clue("사당역 4번 출구", "LOC_FACILITY", "explicit", "self", "역", T), Clue("익선동 한옥거리", "LOC_FACILITY", "explicit", "self", "상가", T),
    Clue("치과위생사로", "JOB", "explicit", "self", "직업명", T), Clue("택시 운전을", "JOB", "explicit", "self", "직업명", T),
    Clue("9호선으로", "COMMUTE", "explicit", "self", "노선", T), Clue("6411번 버스", "COMMUTE", "explicit", "self", "버스", T),
    # ── 노리지 않은 변이
    Clue("93년생", "AGE", "explicit", "self", "출생연도", U), Clue("88년생이라", "AGE", "explicit", "self", "출생연도", U, "88년생이라"),
    Clue("40대 초반", "AGE", "explicit", "self", "연령대", U), Clue("환갑을 앞두고", "AGE", "implicit", "self", "생애사건", U, "환갑을"),
    Clue("분당 사는", "LOC_ADMIN", "explicit", "self", "생활권별칭", U, "분당"), Clue("잠실 토박이", "LOC_ADMIN", "explicit", "self", "생활권별칭", U, "잠실"),
    Clue("경상남도 시골", "LOC_ADMIN", "explicit", "self", "시도정식", U, "경상남도"),
    Clue("롯데월드타워", "LOC_FACILITY", "explicit", "self", "랜드마크", U), Clue("이마트 연수점", "LOC_FACILITY", "explicit", "self", "지점명", U),
    Clue("환자 차트 정리", "JOB", "implicit", "self", "직업묘사", U), Clue("수업 끝나고 학생들 숙제 검사", "JOB", "implicit", "self", "직업묘사", U, "학생들 숙제 검사"),
    Clue("납품 트럭", "JOB", "implicit", "self", "직업묘사", U),
    Clue("시어머니가", "FAM", "implicit", "self", "시가처가", U), Clue("처제랑", "FAM", "implicit", "self", "시가처가", U),
    Clue("외손녀", "FAM", "implicit", "self", "가족", U),
    Clue("집사람이", "SEX", "implicit", "self", "배우자별칭", U), Clue("바깥양반이", "SEX", "implicit", "self", "배우자별칭", U),
    Clue("광역버스로", "COMMUTE", "explicit", "self", "광역버스", U), Clue("자차로 40분", "COMMUTE", "implicit", "self", "자차", U),
    Clue("실수령 290", "INCOME", "explicit", "self", "실수령", U), Clue("한 달에 400 벌어", "INCOME", "explicit", "self", "구어금액", U, "한 달에 400"),
]
TRAPS = [
    Clue("옆집 할머니는 여든셋", "AGE", "explicit", "other", "타인나이", "trap", "여든셋"),
    Clue("사촌이 대구 달서구에", "LOC_ADMIN", "explicit", "other", "타인거주", "trap", "대구 달서구에"),
    Clue("동생 직업이 소방관이라", "JOB", "explicit", "other", "타인직업", "trap", "소방관이라"),
    Clue("후배는 청주에 살고", "LOC_ADMIN", "explicit", "other", "타인거주", "trap", "청주에"),
    Clue("마흔아홉인 사장님", "AGE", "explicit", "other", "타인나이", "trap", "마흔아홉인"),
]
DISTRACTORS = ["열두 시", "마흔 페이지", "스물두 걸음", "서른 개", "쉰 번"]
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
        out.append({"post_id": f"P17B_{i + 1:03d}", "voice": rng.choice(VOICES), "topic": rng.choice(TOPICS),
                    "clues": [{**asdict(c), "span": c.span or c.text} for c in clues], "distractor": distractor})
    return out


if __name__ == "__main__":
    import collections
    import json

    posts = build()
    g = collections.Counter(c["group"] for p in posts for c in p["clues"])
    t = collections.Counter(f"{c['type']}/{c['subject']}" for p in posts for c in p["clues"])
    print(json.dumps({"posts": len(posts), "clues": sum(g.values()), "by_group": dict(g), "by_type": dict(sorted(t.items())),
                      "distractors": sum(1 for p in posts if p["distractor"])}, ensure_ascii=False, indent=1))
