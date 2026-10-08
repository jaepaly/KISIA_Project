"""exp19: 1단 학습용 변이 글의 단서 명세 (#310 2번).

코퍼스(gpt-5.6-sol)에 거의 없는 표현 — 숫자 나이 · 반말 어미 · 금액 · 시·구 / 동 단위 지명 · 역·시설 · 직업명 ·
노선·버스 · 타인 함정 · 숫자 함정 — 을 일부러 섞는다.

⚠️ 평가셋(exp17)과 **표면형이 겹치지 않게** 값을 따로 고른다. 「나이 48에」 「수원 영통구」 같은 평가셋 표현이
학습에 들어가면 exp17 점수가 부풀어 비교가 무의미해진다. ``EXP17_SURFACES`` 와의 겹침을 build() 가 막고,
generate.py 가 생성된 글 본문에서도 다시 검사한다.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

SEED = 20261007
N_POSTS = 300

# exp17 평가셋에 심은 표현 (specs.py SELF_CLUES · OTHER_CLUES · DISTRACTORS 의 text) — 학습 글에 나오면 안 된다
EXP17_SURFACES = {
    "나이 48에", "올해 서른둘", "스물셋임", "23살이고", "마흔하나인데", "37세", "쉰다섯이야", "스물아홉이라",
    "수원 영통구", "용인 기흥구", "대전 유성구", "부산 해운대구", "청주 흥덕구", "인천 연수구", "망원동", "봉천동",
    "전주 완산구", "창원 의창구", "영통역", "선릉역 2번 출구", "광교호수공원", "서면 지하상가", "남부시장",
    "월급 삼백이십만 원", "연봉 4,200만", "알바비로 80만 원", "시급 만 원", "간호사로", "택배 기사", "웹 디자이너",
    "야간 교대 근무", "미용사로", "중학생 아들", "쌍둥이 딸", "2호선으로", "832번 버스",
    "동탄 사는 친구가", "누나가 판교로 이사", "아들이 세종에 산다", "마흔둘인 형", "아홉 살 조카", "친구는 약사라",
    "서른 해 동안", "쉰 날", "스무 권", "마흔 군데",
}
# exp17 정답 스팬(심은 표현의 핵심 부분) — 학습 글 본문에 단어로 나오면 안 된다
EXP17_SPANS = {"48에", "서른둘", "마흔하나인데", "쉰다섯이야", "스물아홉이라", "동탄", "판교로", "세종에", "마흔둘인", "약사라"}


@dataclass(frozen=True)
class Clue:
    text: str
    type: str
    level: str
    subject: str
    variant: str
    span: str = ""   # 정답 스팬 (표현 안의 단서 부분). 비우면 표현 전체


def _ages() -> list[Clue]:
    nums = [19, 21, 26, 28, 31, 34, 39, 42, 45, 47, 51, 53, 56, 59, 62, 64, 67]
    native = ["스물하나", "스물넷", "스물여섯", "서른하나", "서른셋", "서른여섯", "서른여덟", "마흔셋", "마흔넷", "마흔여섯",
              "마흔일곱", "쉰둘", "쉰셋", "쉰일곱", "예순하나", "예순넷", "예순일곱"]
    out = []
    forms_num = ["나이 {n}에", "{n}살이고", "{n}살인데", "{n}세", "올해 {n}살", "{n}살임"]
    forms_nat = ["{w}인데", "{w}이야", "{w}임", "올해 {w}", "{w}이라", "{w}이고"]
    for i, n in enumerate(nums):
        f = forms_num[i % len(forms_num)]
        t = f.format(n=n)
        span = t.replace("올해 ", "").replace("나이 ", "")
        out.append(Clue(t, "AGE", "explicit", "self", "숫자나이", span))
    for i, w in enumerate(native):
        f = forms_nat[i % len(forms_nat)]
        t = f.format(w=w)
        out.append(Clue(t, "AGE", "explicit", "self", "반말어미" if f.endswith(("야}", "임")) or "임" in f or "이야" in f else "한글수사",
                        t.replace("올해 ", "")))
    return out


CITY_GU = [("고양", "일산동구"), ("안양", "동안구"), ("천안", "서북구"), ("광주", "북구"), ("대구", "수성구"), ("성남", "중원구"),
           ("부천", "원미구"), ("포항", "남구"), ("울산", "남구"), ("청주", "상당구"), ("전주", "덕진구"), ("창원", "성산구"),
           ("안산", "상록구"), ("수원", "권선구"), ("용인", "수지구"), ("서울", "노원구"), ("서울", "강서구"),
           ("부산", "동래구"), ("대전", "서구"), ("인천", "부평구"), ("광주", "광산구")]
DONG = ["합정동", "상도동", "중계동", "사직동", "범어동", "구월동", "삼송동", "정왕동", "효자동", "연산동", "괴정동", "다산동"]
FACILITY = [("정자역", "역"), ("미금역 3번 출구", "역"), ("일산호수공원", "공원"), ("동성로", "상가"), ("양동시장", "시장"),
            ("모란시장", "시장"), ("범계역", "역"), ("송도센트럴파크", "공원"), ("대구 서문시장", "시장"), ("광안리 해변", "공원")]
INCOME = ["월급 이백팔십만 원", "연봉 3,600만", "알바비로 55만 원", "시급 만 이천 원", "월급 410만 원", "연봉 오천만",
          "이번 달 수당 30만 원", "연금 백이십만 원"]
JOB = [("물리치료사로", "직업명"), ("바리스타로", "직업명"), ("지게차 기사", "직업명"), ("공인중개사로", "직업명"),
       ("어린이집 교사로", "직업명"), ("편의점 점장", "직업명"), ("보험 설계사", "직업명"), ("헬스 트레이너로", "직업명"),
       ("주간 2교대 근무", "암묵"), ("반찬가게를 운영", "암묵")]
FAM = ["초등학생 딸", "고3 아들", "세 살 아들", "남매", "막내딸", "큰아들"]
SEX = ["아내가", "와이프가", "남편이랑"]
COMMUTE = [("4호선으로", "노선"), ("수인분당선으로", "노선"), ("152번 버스", "버스"), ("7016번 버스", "버스"), ("경의중앙선으로", "노선")]

OTHER = [Clue("일산 사는 동생이", "LOC_ADMIN", "explicit", "other", "타인거주", "일산"),
         Clue("언니가 청라로 이사", "LOC_ADMIN", "explicit", "other", "타인거주", "청라로"),
         Clue("딸이 부산에 산다", "LOC_ADMIN", "explicit", "other", "타인거주", "부산에"),
         Clue("서른다섯인 언니", "AGE", "explicit", "other", "타인나이", "서른다섯인"),
         Clue("일곱 살 손주", "AGE", "explicit", "other", "타인나이", "일곱 살"),
         Clue("남편은 회계사라", "JOB", "explicit", "other", "타인직업", "회계사라"),
         Clue("친구가 노원구에 살아서", "LOC_ADMIN", "explicit", "other", "타인거주", "노원구에")]
DISTRACTORS = ["스무 해 넘게", "서른 번째", "마흔 장", "쉰 개", "예순 그루"]
VOICES = ["반말 SNS 말투", "존댓말 블로그 말투", "짧은 혼잣말 말투", "어르신 블로그 말투", "20대 커뮤니티 말투"]
TOPICS = ["퇴근 뒤 저녁", "주말 산책", "비 오는 날", "장보기", "카페에서", "운동한 날", "청소한 날", "택배 받은 날",
          "늦잠 잔 날", "새로 산 물건", "날씨 이야기", "점심 메뉴", "출근길", "명절 준비", "미용실 다녀온 날", "이사 정리"]


def self_clues() -> list[Clue]:
    out = _ages()
    out += [Clue(f"{c} {g}", "LOC_ADMIN", "explicit", "self", "시구") for c, g in CITY_GU]
    out += [Clue(d, "LOC_ADMIN", "explicit", "self", "동") for d in DONG]
    out += [Clue(t, "LOC_FACILITY", "explicit", "self", v) for t, v in FACILITY]
    out += [Clue(t, "INCOME", "explicit", "self", "금액") for t in INCOME]
    out += [Clue(t, "JOB", "explicit" if v == "직업명" else "implicit", "self", v) for t, v in JOB]
    out += [Clue(t, "FAM", "implicit", "self", "가족") for t in FAM]
    out += [Clue(t, "SEX", "implicit", "self", "배우자") for t in SEX]
    out += [Clue(t, "COMMUTE", "explicit", "self", v) for t, v in COMMUTE]
    return out


def build() -> list[dict]:
    pool = self_clues()
    for c in pool + OTHER:
        assert c.text not in EXP17_SURFACES and not any(s in c.text for s in EXP17_SURFACES), c.text
    for d in DISTRACTORS:
        assert d not in EXP17_SURFACES, d
    rng = random.Random(SEED)
    order = pool[:]
    out = []
    for i in range(N_POSTS):
        if i % len(order) == 0:
            rng.shuffle(order)
        clues = [order[i % len(order)]]
        if rng.random() < 0.5:
            clues.append(rng.choice([c for c in pool if c.type != clues[0].type]))
        if rng.random() < 0.3:
            clues.append(rng.choice(OTHER))
        distractor = rng.choice(DISTRACTORS) if rng.random() < 0.15 else None
        out.append({"post_id": f"AUG1_{i + 1:04d}", "voice": rng.choice(VOICES), "topic": rng.choice(TOPICS),
                    "clues": [{**asdict(c), "span": c.span or c.text} for c in clues], "distractor": distractor})
    return out


if __name__ == "__main__":
    import collections
    import json

    posts = build()
    cnt = collections.Counter(f"{c['type']}/{c['subject']}" for p in posts for c in p["clues"])
    var = collections.Counter(c["variant"] for p in posts for c in p["clues"])
    print(json.dumps({"posts": len(posts), "clues": sum(cnt.values()), "self_pool": len(self_clues()), "by_type": dict(sorted(cnt.items())),
                      "by_variant": dict(sorted(var.items())), "distractors": sum(1 for p in posts if p["distractor"])},
                     ensure_ascii=False, indent=1))
