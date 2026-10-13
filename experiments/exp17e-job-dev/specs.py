"""exp17e: 1단 JOB 오탐 개선의 **개발용** 평가셋 명세 — 후보를 고르는 데 쓴다 (판정은 exp17d 에서 한 번).

exp17d 와 같은 설계(본인 직업 · 남의 직함 · 직업 비슷한 일상 · 다른 유형 본인 단서 · 숫자 함정)에 **표현만 전부 다르다**.
B 의 내부 eval(JOB 오탐 9개)은 학습 기록(trainer_state)이 B 데스크톱에만 있어 이 PC 에서 다시 만들 수 없고,
exp17 에는 JOB 함정이 없다(심지 않은 JOB 예측 2개). 그래서 고르기용으로 따로 만든다 — 오답을 열어 봐도 된다.
겹침: exp17 · 17b · 17c · **17d** 의 심은 표현 · 함정 · AUG1 정답 스팬과 부분 문자열로도 겹치지 않게
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

SEED = 20261014
N_POSTS = 60


@dataclass(frozen=True)
class Clue:
    text: str
    type: str
    level: str
    subject: str
    variant: str
    group: str
    span: str = ""


J, TO, O = "job_self", "job_title_other", "other_self"
# 스팬은 label-schema §5-2 — 어절 정렬 · 끝 어절의 조사 · 어미 포함 · 용언 제외
JOB_SELF = [
    Clue("전기기사로", "JOB", "explicit", "self", "직업명", J),
    Clue("미용 일을", "JOB", "explicit", "self", "직업명", J),
    Clue("물리치료사라", "JOB", "explicit", "self", "직업명", J),
    Clue("제빵사라서", "JOB", "explicit", "self", "직업명", J),
    Clue("카페 매니저로", "JOB", "explicit", "self", "직업명", J),
    Clue("학원 차량 기사로", "JOB", "explicit", "self", "직업명", J),
    Clue("부장 단 지", "JOB", "explicit", "self", "본인직함", J, "부장"),
    Clue("대리 2년 차라", "JOB", "explicit", "self", "본인직함", J, "대리"),
    Clue("가게 사장이라", "JOB", "explicit", "self", "본인직함", J),
    Clue("공장 2교대", "JOB", "implicit", "self", "직업묘사", J),
    Clue("배달 대행 일", "JOB", "implicit", "self", "직업묘사", J),
    Clue("창고 재고 정리", "JOB", "implicit", "self", "직업묘사", J),
    Clue("납품 마감", "JOB", "implicit", "self", "직업묘사", J),
]
JOB_TITLE_OTHER = [
    Clue("부장님께서", "JOB", "explicit", "other", "타인직함", TO),
    Clue("대표님이", "JOB", "explicit", "other", "타인직함", TO),
    Clue("소장님 댁에", "JOB", "explicit", "other", "타인직함", TO, "소장님"),
    Clue("대리님이 또", "JOB", "explicit", "other", "타인직함", TO, "대리님이"),
    Clue("간호사 선생님이", "JOB", "explicit", "other", "타인직업", TO),
    Clue("선배 사서가", "JOB", "explicit", "other", "타인직업", TO, "사서가"),
    Clue("동생이 성우라", "JOB", "explicit", "other", "타인직업", TO, "성우라"),
]
# 직업이 아닌 뜻으로 쓰게 시킨다 — 이 표현을 JOB 으로 잡으면 오탐
JOB_LOOKALIKE = [
    ("개학이라", "일정"), ("휴가 내고", "일정"), ("조퇴하고", "일정"), ("클라이밍이 취미", "취미"), ("캠핑 모임", "취미"),
    ("화분 분갈이", "취미"), ("빨래 당번", "집안일"), ("장 보러", "집안일"), ("안과 검진", "간 곳"),
    ("수선집에 맡기러", "간 곳"), ("택배 부치러", "일상"), ("면허 갱신", "일상"), ("베이킹 클래스", "일상"), ("등산하러", "일상"),
]
OTHER_SELF = [
    Clue("쉰여섯인데", "AGE", "explicit", "self", "한글수사", O), Clue("나이 41에", "AGE", "explicit", "self", "숫자나이", O, "41에"),
    Clue("92년생이라", "AGE", "explicit", "self", "출생연도", O),
    Clue("구리 갈매동", "LOC_ADMIN", "explicit", "self", "시구", O), Clue("원주 단계동", "LOC_ADMIN", "explicit", "self", "시구", O),
    Clue("노원역 4번 출구", "LOC_FACILITY", "explicit", "self", "역", O),
    Clue("월급 삼백십", "INCOME", "explicit", "self", "금액", O), Clue("GTX로", "COMMUTE", "explicit", "self", "노선", O),
    Clue("올케랑", "FAM", "implicit", "self", "시가처가", O), Clue("바깥사람이", "SEX", "implicit", "self", "배우자호칭", O),
]
AGE_DISTRACTORS = ["스물두 번", "마흔 개", "쉰 장째", "서른 바퀴"]
VOICES = ["반말 SNS 말투", "존댓말 블로그 말투", "짧은 혼잣말 말투", "어르신 블로그 말투", "20대 커뮤니티 말투"]
TOPICS = ["퇴근 뒤", "주말 오후", "비 오는 아침", "장보기", "카페", "운동", "청소", "택배", "늦잠", "새로 산 물건",
          "날씨", "점심", "명절", "산책", "친구 만난 날", "월요일", "저녁 메뉴", "동네 가게"]

# 글마다 주 요소 하나: 본인 직업 20 · 남의 직함 17 · 직업 비슷한 일상 23
PLAN = ["job_self"] * 20 + ["job_title_other"] * 17 + ["job_lookalike"] * 23


def build() -> list[dict]:
    rng = random.Random(SEED)
    plan = PLAN[:]
    rng.shuffle(plan)
    pools = {"job_self": JOB_SELF[:], "job_title_other": JOB_TITLE_OTHER[:], "job_lookalike": JOB_LOOKALIKE[:]}
    cursor = {k: 0 for k in pools}
    out = []
    for i, kind in enumerate(plan):
        pool = pools[kind]
        if cursor[kind] % len(pool) == 0:
            rng.shuffle(pool)
        main = pool[cursor[kind] % len(pool)]
        cursor[kind] += 1
        clues, distractors = [], []
        if kind == "job_lookalike":
            distractors.append({"text": main[0], "type": "JOB", "variant": main[1]})
        else:
            clues.append(main)
        if rng.random() < 0.5:
            clues.append(rng.choice(OTHER_SELF))
        if kind == "job_lookalike" and rng.random() < 0.3:     # 일상 함정과 진짜 직업이 한 글에 같이 있는 경우
            clues.append(rng.choice(JOB_SELF))
        if rng.random() < 0.15:
            distractors.append({"text": rng.choice(AGE_DISTRACTORS), "type": "AGE", "variant": "숫자함정"})
        out.append({"post_id": f"P17E_{i + 1:03d}", "kind": kind, "voice": rng.choice(VOICES), "topic": rng.choice(TOPICS),
                    "clues": [{**asdict(c), "span": c.span or c.text} for c in clues], "distractors": distractors})
    return out


def overlap_check(root) -> list[tuple[str, str]]:
    """exp17 · exp17b · exp17c · exp17d 심은 표현 · 함정 · AUG1 정답 스팬과 부분 문자열로라도 겹치는 새 표현 → [(새 표현, 기존 표현)]"""
    import json
    from pathlib import Path

    root = Path(root)
    used: set[str] = set()
    for f in ("experiments/exp17-planted-eval/data/posts.jsonl", "experiments/exp17b-heldout-eval/data/posts.jsonl",
              "experiments/exp17c-final-eval/data/posts.jsonl", "experiments/exp17d-job-eval/data/posts.jsonl"):
        for line in (root / f).read_text(encoding="utf-8").splitlines():
            if line.strip():
                g = json.loads(line)
                used |= {c["text"] for c in g["planted"]} | {c.get("clue") or c["text"] for c in g["planted"]}
                used |= {d["text"] for d in g.get("distractors", [])}
    for line in (root / "data/corpus/aug/v1/AUG1_spans.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line) if line.strip() else {}
        used |= {s["text"] for s in r.get("spans", [])}
    allc = JOB_SELF + JOB_TITLE_OTHER + OTHER_SELF
    new = {c.text for c in allc} | {c.span for c in allc if c.span} | {t for t, _ in JOB_LOOKALIKE} | set(AGE_DISTRACTORS)
    # 두 글자 이하 기존 표현(「사는」「동네」)은 너무 흔해 겹침 판단에서 뺀다
    return sorted((n, u) for n in new for u in used if len(u) >= 3 and (n in u or u in n))


if __name__ == "__main__":
    import collections
    import json
    from pathlib import Path

    posts = build()
    g = collections.Counter(c["group"] for p in posts for c in p["clues"])
    d = collections.Counter(x["type"] for p in posts for x in p["distractors"])
    print(json.dumps({"posts": len(posts), "kinds": dict(collections.Counter(p["kind"] for p in posts)),
                      "clues": sum(g.values()), "by_group": dict(g), "distractors": dict(d),
                      "overlap": overlap_check(Path(__file__).resolve().parents[2])}, ensure_ascii=False, indent=1))
