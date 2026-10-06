"""exp17: 코퍼스 밖 평가셋의 「심을 단서」 명세 — 글마다 그대로 넣을 표현과 정답 속성.

정답은 사람·Claude 라벨이 아니라 **여기서 정한 표현의 위치**다 (생성 뒤 문자열 일치로 찾는다).
변이를 일부러 섞는다 — 코퍼스(gpt-5.6-sol)에 드문 숫자 나이 · 반말 어미 · 금액 · 구·동 단위 · 시설 · 타인 함정.
모든 인물·장소 조합은 가상이다. 학력·학교·전공·정치·건강 단서는 넣지 않는다 (RULES-DO-NOT).
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

SEED = 20261006
N_POSTS = 80


@dataclass(frozen=True)
class Clue:
    text: str      # 글에 **그대로** 들어가야 하는 표현 (정답 스팬의 핵심)
    type: str      # label-schema 유형
    level: str     # explicit / implicit
    subject: str   # self / other
    variant: str   # 어떤 변이인가 (보고용)


SELF_CLUES = [
    # AGE — 숫자 · 한글 수사 · 반말 어미
    Clue("나이 48에", "AGE", "explicit", "self", "숫자나이"),
    Clue("올해 서른둘", "AGE", "explicit", "self", "한글수사"),
    Clue("스물셋임", "AGE", "explicit", "self", "반말어미"),
    Clue("23살이고", "AGE", "explicit", "self", "숫자나이"),
    Clue("마흔하나인데", "AGE", "explicit", "self", "한글수사"),
    Clue("37세", "AGE", "explicit", "self", "숫자나이"),
    Clue("쉰다섯이야", "AGE", "explicit", "self", "반말어미"),
    Clue("스물아홉이라", "AGE", "explicit", "self", "한글수사"),
    # LOC_ADMIN — 시+구 · 동 · 약칭
    Clue("수원 영통구", "LOC_ADMIN", "explicit", "self", "시구"),
    Clue("용인 기흥구", "LOC_ADMIN", "explicit", "self", "시구"),
    Clue("대전 유성구", "LOC_ADMIN", "explicit", "self", "시구"),
    Clue("부산 해운대구", "LOC_ADMIN", "explicit", "self", "시구"),
    Clue("청주 흥덕구", "LOC_ADMIN", "explicit", "self", "시구"),
    Clue("인천 연수구", "LOC_ADMIN", "explicit", "self", "시구"),
    Clue("망원동", "LOC_ADMIN", "explicit", "self", "동"),
    Clue("봉천동", "LOC_ADMIN", "explicit", "self", "동"),
    Clue("전주 완산구", "LOC_ADMIN", "explicit", "self", "시구"),
    Clue("창원 의창구", "LOC_ADMIN", "explicit", "self", "시구"),
    # LOC_FACILITY — 역 · 공원 · 시장
    Clue("영통역", "LOC_FACILITY", "explicit", "self", "역"),
    Clue("선릉역 2번 출구", "LOC_FACILITY", "explicit", "self", "역"),
    Clue("광교호수공원", "LOC_FACILITY", "explicit", "self", "공원"),
    Clue("서면 지하상가", "LOC_FACILITY", "explicit", "self", "상가"),
    Clue("남부시장", "LOC_FACILITY", "explicit", "self", "시장"),
    # INCOME — 금액
    Clue("월급 삼백이십만 원", "INCOME", "explicit", "self", "금액"),
    Clue("연봉 4,200만", "INCOME", "explicit", "self", "금액"),
    Clue("알바비로 80만 원", "INCOME", "explicit", "self", "금액"),
    Clue("시급 만 원", "INCOME", "explicit", "self", "금액"),
    # JOB — 직업명 · 암묵
    Clue("간호사로 일한 지", "JOB", "explicit", "self", "직업명"),
    Clue("택배 기사", "JOB", "explicit", "self", "직업명"),
    Clue("웹 디자이너", "JOB", "explicit", "self", "직업명"),
    Clue("야간 교대 근무", "JOB", "implicit", "self", "암묵"),
    Clue("미용사로", "JOB", "explicit", "self", "직업명"),
    # FAM · SEX · COMMUTE
    Clue("중학생 아들", "FAM", "implicit", "self", "가족"),
    Clue("쌍둥이 딸", "FAM", "implicit", "self", "가족"),
    Clue("남편이", "SEX", "implicit", "self", "배우자"),
    Clue("2호선으로 출근", "COMMUTE", "explicit", "self", "노선"),
    Clue("832번 버스", "COMMUTE", "explicit", "self", "버스"),
]

# 타인 함정 — 문장이 단서를 다른 사람에게 귀속시킨다 (label-schema §4-2)
OTHER_CLUES = [
    Clue("동탄 사는 친구가", "LOC_ADMIN", "explicit", "other", "타인거주"),
    Clue("누나가 판교로 이사", "LOC_ADMIN", "explicit", "other", "타인거주"),
    Clue("아들이 세종에 산다", "LOC_ADMIN", "explicit", "other", "타인거주"),
    Clue("마흔둘인 형", "AGE", "explicit", "other", "타인나이"),
    Clue("아홉 살 조카", "AGE", "explicit", "other", "타인나이"),
    Clue("친구는 약사라", "JOB", "explicit", "other", "타인직업"),
]

# 단서가 아닌 수 — 나이로 잡으면 오탐 (「서른 해」 「쉰 날」)
DISTRACTORS = ["서른 해 동안", "쉰 날", "스무 권", "마흔 군데"]

VOICES = ["반말 SNS 말투", "존댓말 블로그 말투", "짧은 혼잣말 말투", "어르신 블로그 말투"]
TOPICS = ["퇴근 뒤 저녁", "주말 산책", "비 오는 날", "장보기", "카페에서", "운동한 날", "청소한 날", "택배 받은 날",
          "늦잠 잔 날", "새로 산 물건", "날씨 이야기", "점심 메뉴"]


# 단서의 정답 스팬 = 표현 안에서 실제 단서 부분 (「동탄 사는 친구가」 → 「동탄」). 없으면 표현 전체
SPAN_OF = {
    "나이 48에": "48에", "올해 서른둘": "서른둘", "간호사로 일한 지": "간호사로", "2호선으로 출근": "2호선으로",
    "동탄 사는 친구가": "동탄", "누나가 판교로 이사": "판교로", "아들이 세종에 산다": "세종에",
    "마흔둘인 형": "마흔둘인", "아홉 살 조카": "아홉 살", "친구는 약사라": "약사라",
}


def build() -> list[dict]:
    rng = random.Random(SEED)
    self_pool = SELF_CLUES[:]
    out = []
    for i in range(N_POSTS):
        if i % len(self_pool) == 0:
            rng.shuffle(self_pool)
        clues = [self_pool[i % len(self_pool)]]
        if rng.random() < 0.45:  # 두 번째 본인 단서 — 다른 유형으로
            second = rng.choice([c for c in SELF_CLUES if c.type != clues[0].type])
            clues.append(second)
        if rng.random() < 0.3:
            clues.append(rng.choice(OTHER_CLUES))
        distractor = rng.choice(DISTRACTORS) if rng.random() < 0.15 else None
        out.append({
            "post_id": f"P17_{i + 1:03d}",
            "voice": rng.choice(VOICES),
            "topic": rng.choice(TOPICS),
            "clues": [{**asdict(c), "span": SPAN_OF.get(c.text, c.text)} for c in clues],
            "distractor": distractor,
        })
    return out


if __name__ == "__main__":
    import collections
    import json

    posts = build()
    cnt = collections.Counter((c["type"], c["subject"]) for p in posts for c in p["clues"])
    print(json.dumps({"posts": len(posts), "clues": sum(cnt.values()), "by_type": {f"{t}/{s}": n for (t, s), n in sorted(cnt.items())},
                      "distractors": sum(1 for p in posts if p["distractor"])}, ensure_ascii=False, indent=1))
