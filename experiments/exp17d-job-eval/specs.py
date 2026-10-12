"""exp17d: 1단 JOB 오탐 개선의 판정용 평가셋 명세 — 기준선 v2 와 후보를 **한 번씩만** 잰다 (#322 ③ · README W9 D 4번).

exp17 은 개발용(오답을 봤다), exp17b · exp17c 는 이미 채점에 썼다. JOB 오탐을 판정하려면 「직업이 아닌데 직업으로 잡을 만한 표현」이
충분히 들어 있어야 해서 JOB 중심으로 새로 만든다. 묶음(group):
- **job_self** — 글쓴이 본인 직업 (새 값). 직업명 · 직업 묘사 → JOB 재현율이 떨어지지 않는지
- **job_title_other** — 남의 직함 (「팀장님께서」 등 · subject=other). 본인 JOB 으로 잡으면 k 를 잘못 좁힌다 — 실제 글 오탐의 대부분 (#322 코멘트)
- **job_lookalike** — 직업이 아닌 일상 표현(일정 · 취미 · 집안일 · 소비자로 간 곳). 정답이 아니라 **함정**(distractor · type=JOB)
- **other_self** — 다른 유형의 본인 단서 (새 값) — JOB 을 고치다 다른 유형이 같이 떨어지지 않는지 (회귀 확인)
- 숫자 함정(AGE) — exp17c 와 같은 방식

함정 표현을 고른 근거는 #322 의 실제 사례 두 종류(「방학이」 · 「회장님께서 · 부장님께서」)와 사전 추론이다. exp17 · exp17b · exp17c 의 오답 목록은 보지 않았다.
겹침: exp17 · exp17b · exp17c 의 심은 표현 · 함정과 exp19(AUG1) 정답 스팬 — 부분 문자열로도 겹치면 겹침 (`overlap_check`)
⚠️ 채점은 기준선 · 후보를 같은 날 **한 번만** 하고, 오답을 열어 고치지 않는다. 판정 기준은 README §2 — 데이터를 보기 전에 적었다.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

SEED = 20261012
N_POSTS = 90


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
    Clue("보험설계사로", "JOB", "explicit", "self", "직업명", J),
    Clue("용접공으로", "JOB", "explicit", "self", "직업명", J),
    Clue("세무사 일을", "JOB", "explicit", "self", "직업명", J),
    Clue("버스 기사로", "JOB", "explicit", "self", "직업명", J),
    Clue("수의사라서", "JOB", "explicit", "self", "직업명", J),
    Clue("조경 기사로", "JOB", "explicit", "self", "직업명", J),
    # 본인 직함 — 아래 남의 직함과 짝. 직함을 일괄로 거르는 후보가 이것까지 잃으면 재현율에서 드러난다
    Clue("팀장 3년 차라", "JOB", "explicit", "self", "본인직함", J, "팀장"),
    Clue("식당 사장이라", "JOB", "explicit", "self", "본인직함", J),
    Clue("과장 달고", "JOB", "explicit", "self", "본인직함", J, "과장"),
    Clue("야간 경비 근무", "JOB", "implicit", "self", "직업묘사", J),
    Clue("매장 마감 정산", "JOB", "implicit", "self", "직업묘사", J),
    Clue("택시 운행", "JOB", "implicit", "self", "직업묘사", J),
    Clue("건설 현장 일", "JOB", "implicit", "self", "직업묘사", J),
    Clue("청과 도매업", "JOB", "implicit", "self", "직업묘사", J),
]
JOB_TITLE_OTHER = [
    Clue("팀장님께서", "JOB", "explicit", "other", "타인직함", TO),
    Clue("원장님이", "JOB", "explicit", "other", "타인직함", TO),
    Clue("이장님 댁에", "JOB", "explicit", "other", "타인직함", TO, "이장님"),
    Clue("과장님이 또", "JOB", "explicit", "other", "타인직함", TO, "과장님이"),
    Clue("기사님이 친절하게", "JOB", "explicit", "other", "타인직함", TO, "기사님이"),
    Clue("실장님한테", "JOB", "explicit", "other", "타인직함", TO),
    Clue("선배 치위생사가", "JOB", "explicit", "other", "타인직업", TO, "치위생사가"),
    Clue("동생이 플로리스트라", "JOB", "explicit", "other", "타인직업", TO, "플로리스트라"),
]
# 직업이 아닌 뜻으로 쓰게 시킨다 — 이 표현을 JOB 으로 잡으면 오탐
JOB_LOOKALIKE = [
    ("방학이라", "일정"), ("연차 내고", "일정"), ("반차 쓰고", "일정"), ("베이킹이 취미", "취미"), ("주말 텃밭", "취미"),
    ("뜨개질 모임", "취미"), ("설거지 당번", "집안일"), ("분리수거 하러", "집안일"), ("치과 진료 받으러", "간 곳"),
    ("세탁소에 맡기러", "간 곳"), ("택배 받으러", "일상"), ("운전 연수", "일상"), ("요리 유튜브", "일상"), ("헌혈하러", "일상"),
]
OTHER_SELF = [
    Clue("마흔셋인데", "AGE", "explicit", "self", "한글수사", O), Clue("나이 34에", "AGE", "explicit", "self", "숫자나이", O, "34에"),
    Clue("87년생이라", "AGE", "explicit", "self", "출생연도", O),
    Clue("안양 평촌동", "LOC_ADMIN", "explicit", "self", "시구", O), Clue("춘천 후평동", "LOC_ADMIN", "explicit", "self", "시구", O),
    Clue("연신내역 3번 출구", "LOC_FACILITY", "explicit", "self", "역", O),
    Clue("월급 이백칠십", "INCOME", "explicit", "self", "금액", O), Clue("서해선으로", "COMMUTE", "explicit", "self", "노선", O),
    Clue("처형이랑", "FAM", "implicit", "self", "시가처가", O), Clue("우리 집 양반이", "SEX", "implicit", "self", "배우자호칭", O),
]
AGE_DISTRACTORS = ["스물한 개", "마흔 장", "예순 번째", "서른 그릇"]
VOICES = ["반말 SNS 말투", "존댓말 블로그 말투", "짧은 혼잣말 말투", "어르신 블로그 말투", "20대 커뮤니티 말투"]
TOPICS = ["퇴근 뒤", "주말 오후", "비 오는 아침", "장보기", "카페", "운동", "청소", "택배", "늦잠", "새로 산 물건",
          "날씨", "점심", "명절", "산책", "친구 만난 날", "월요일", "저녁 메뉴", "동네 가게"]

# 글마다 주 요소 하나: 본인 직업 30 · 남의 직함 25 · 직업 비슷한 일상 35
PLAN = ["job_self"] * 30 + ["job_title_other"] * 25 + ["job_lookalike"] * 35


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
        out.append({"post_id": f"P17D_{i + 1:03d}", "kind": kind, "voice": rng.choice(VOICES), "topic": rng.choice(TOPICS),
                    "clues": [{**asdict(c), "span": c.span or c.text} for c in clues], "distractors": distractors})
    return out


def overlap_check(root) -> list[tuple[str, str]]:
    """exp17 · exp17b · exp17c 심은 표현 · 함정 · AUG1 정답 스팬과 부분 문자열로라도 겹치는 새 표현 → [(새 표현, 기존 표현)]"""
    import json
    from pathlib import Path

    root = Path(root)
    used: set[str] = set()
    for f in ("experiments/exp17-planted-eval/data/posts.jsonl", "experiments/exp17b-heldout-eval/data/posts.jsonl",
              "experiments/exp17c-final-eval/data/posts.jsonl"):
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
