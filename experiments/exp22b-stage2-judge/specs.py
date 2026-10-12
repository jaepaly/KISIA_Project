"""exp22b: 2단 v1 · v2 판정용 평가셋 명세 — exp22 와 같은 설계 · seed 와 ID 형식만 다르다 (exp22 는 출력 상한 버그로 판정 불가 · README).

아래는 exp22 명세 설명 그대로다. 다른 점: SEED · 계정/글 ID 를 앱(Veilo)과 같은 길이로(`H01` · `H01_b07`) · 남의 정보 「오빠는 은행원이고」를
성별 단서가 아닌 「지인은 은행원이고」로 (exp22 설계 실수).


exp09 는 1단 test 와 같은 239편이고 불일치 사례를 이미 들여다봤다 → 독립 판정이 아니다. 그래서 새로 만든다.
2단 모델은 원문이 아니라 가명화 스팬 목록(유형 · 등급 · 본인 여부 · 글 번호)만 보고, 학습 정답은 규칙(findings_from_spans)이다.
그래서 이 셋이 재는 것은 「앱과 같은 긴 입력에서 규칙대로 판정하고 형식이 깨지지 않는가」다 — 입력은 앱 1단이 이 글에서 뽑은 스팬.

- 계정 30명 × 글 24편 — 실제 코퍼스 계정 중앙 27편(test 제외)에 가깝게. 학습 예시 중앙 9편보다 길다
- 속성마다 조건 하나: E(본인 · 직접 표현) · I(본인 · 간접 표현) · N(단서 없음). E · I 단서는 2~4편에 되풀이 (cross_post)
- E 칸의 40% 는 같은 속성의 간접 표현도 함께 (E+I 공존) — 입력이 상한(16 · 유형당 4)을 넘게 해 고르기 손실을 시험한다
- 표현은 다른 속성을 드러내지 않게 골랐다 (예: 「외동딸」은 성별을 드러내서 뺐다). 배우자 호칭은 label-schema 관례대로 SEX
- 계정마다 남의 정보 1~2개 (subject other — 근거가 되면 안 된다) · 나머지는 잡담
- 심은 속성 정답(E → specified · I → narrowed · N → abstain)은 1단 오류가 섞이므로 **참고 지표**다 (README §2)
겹침: exp17 · 17b · 17c · 17d 심은 표현 · 함정 · AUG1 정답 스팬과 부분 문자열로도 겹치면 겹침 (`overlap_check`)
"""
from __future__ import annotations

import random

SEED = 20261015
N_ACCOUNTS = 30
N_POSTS = 24
ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")
COND_P = {"E": 0.4, "I": 0.3, "N": 0.3}

# 속성 · 조건별 표현 — 본인 정보로 쓰게 시킨다. (type, 표현)
BANK = {
    "age": {"E": [("AGE", "올해 쉰둘"), ("AGE", "서른여섯인데"), ("AGE", "73년생이고"), ("AGE", "스물여덟이라")],
            "I": [("AGE", "은퇴한 지 3년째"), ("AGE", "사회초년생이라"), ("AGE", "환갑 넘기고")]},
    "sex": {"E": [("SEX", "남자 혼자"), ("SEX", "여자 혼자")],
            "I": [("SEX", "우리 영감이"), ("SEX", "아내 몰래")]},
    "location": {"E": [("LOC_ADMIN", "부천 중동"), ("LOC_ADMIN", "청주 율량동"), ("LOC_ADMIN", "울산 삼산동"), ("LOC_ADMIN", "광주 수완동")],
                 "I": [("LOC_FACILITY", "부평역 지하상가"), ("LOC_FACILITY", "동탄 호수공원"), ("LOC_FACILITY", "서면 교차로")]},
    "occupation": {"E": [("JOB", "간호조무사로"), ("JOB", "크레인 기사로"), ("JOB", "제약회사 영업"), ("JOB", "주유소 점장")],
                   "I": [("JOB", "가게 셔터 내리고"), ("JOB", "거래처 미팅"), ("JOB", "교대 근무 끝나고")]},
    "family": {"E": [("FAM", "쌍둥이 키우는"), ("FAM", "외동이라"), ("FAM", "부모님 모시고")],
               "I": [("FAM", "애들 하원"), ("FAM", "막내 학원 픽업")]},
    "commute": {"E": [("COMMUTE", "1호선 타고 출근"), ("COMMUTE", "좌석버스로 출근"), ("COMMUTE", "자전거로 출퇴근")],
                "I": [("COMMUTE", "환승 두 번"), ("COMMUTE", "새벽 첫차")]},
    "income": {"E": [("INCOME", "세후 270"), ("INCOME", "연봉 4천"), ("INCOME", "월 250 벌어")],
               "I": [("INCOME", "최저시급 받고"), ("INCOME", "성과급 없이")]},
}
SEX_PAIR = {"남자 혼자": ("SEX", "아내 몰래"), "여자 혼자": ("SEX", "우리 영감이")}
OTHER = [("LOC_ADMIN", "친구는 성남 살고"), ("JOB", "지인은 은행원이고"), ("AGE", "옆집 할머니는 여든다섯"),
         ("INCOME", "동기는 연봉 6천"), ("FAM", "사촌은 아들 셋")]
TOPICS = ["퇴근 뒤", "주말 오후", "비 오는 아침", "장보기", "카페", "운동", "청소", "택배", "늦잠", "새로 산 물건",
          "날씨", "점심", "명절", "산책", "친구 만난 날", "월요일", "저녁 메뉴", "동네 가게", "드라마", "여행 계획"]
VOICES = ["반말 SNS 말투", "존댓말 블로그 말투", "짧은 혼잣말 말투", "어르신 블로그 말투", "20대 커뮤니티 말투"]


def build() -> list[dict]:
    """계정마다 {account_id, voice, conditions{attr: E|I|N}, posts[{idx, topic, clues[{attr,cond,type,text,subject}]}]}"""
    rng = random.Random(SEED)
    out = []
    for a in range(N_ACCOUNTS):
        conds = {attr: rng.choices(list(COND_P), weights=list(COND_P.values()))[0] for attr in ATTRS}
        # 성별은 SEX(E) 와 배우자 호칭(I) 이 같은 사람 안에서 모순되지 않게 — 하나만 쓴다
        posts = [{"idx": i, "topic": rng.choice(TOPICS), "clues": []} for i in range(N_POSTS)]
        for attr, c in conds.items():
            if c == "N":
                continue
            typ, text = rng.choice(BANK[attr][c])
            for i in rng.sample(range(N_POSTS), rng.choice([2, 3, 4])):
                posts[i]["clues"].append({"attr": attr, "cond": c, "type": typ, "text": text, "subject": "self"})
            if c == "E" and rng.random() < 0.4:   # 같은 속성의 간접 표현도 — 정답은 그대로 specified
                # 성별은 짝을 맞춘다 — 「여자 혼자」에 「아내 몰래」가 붙으면 모순 (배우자 호칭 = SEX 관례)
                typ2, text2 = SEX_PAIR[text] if attr == "sex" else rng.choice(BANK[attr]["I"])
                for i in rng.sample(range(N_POSTS), rng.choice([1, 2])):
                    if all(x["text"] != text2 for x in posts[i]["clues"]):
                        posts[i]["clues"].append({"attr": attr, "cond": "E+I", "type": typ2, "text": text2, "subject": "self"})
        for typ, text in rng.sample(OTHER, rng.choice([1, 2])):
            posts[rng.randrange(N_POSTS)]["clues"].append({"attr": None, "cond": "other", "type": typ, "text": text, "subject": "other"})
        out.append({"account_id": f"H{a + 1:02d}", "voice": rng.choice(VOICES), "conditions": conds, "posts": posts})
    return out


def overlap_check(root) -> list[tuple[str, str]]:
    import json
    from pathlib import Path

    root = Path(root)
    used: set[str] = set()
    for f in ("exp17-planted-eval", "exp17b-heldout-eval", "exp17c-final-eval", "exp17d-job-eval"):
        path = root / "experiments" / f / "data/posts.jsonl"
        if not path.exists():
            raise SystemExit(f"겹침 비교 파일이 없다: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                g = json.loads(line)
                used |= {c["text"] for c in g["planted"]} | {c.get("clue") or c["text"] for c in g["planted"]}
                used |= {d["text"] for d in g.get("distractors", [])}
    for line in (root / "data/corpus/aug/v1/AUG1_spans.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line) if line.strip() else {}
        used |= {s["text"] for s in r.get("spans", [])}
    new = {t for v in BANK.values() for lst in v.values() for _, t in lst} | {t for _, t in OTHER}
    return sorted((n, u) for n in new for u in used if len(u) >= 3 and (n in u or u in n))


if __name__ == "__main__":
    import collections
    import json
    from pathlib import Path

    acc = build()
    cond = collections.Counter(c for a in acc for c in a["conditions"].values())
    per_attr = {attr: dict(collections.Counter(a["conditions"][attr] for a in acc)) for attr in ATTRS}
    clue_posts = sum(1 for a in acc for p in a["posts"] if p["clues"])
    print(json.dumps({"accounts": len(acc), "cells": dict(cond), "per_attr": per_attr, "posts": len(acc) * N_POSTS,
                      "posts_with_clues": clue_posts, "overlap": overlap_check(Path(__file__).resolve().parents[2])},
                     ensure_ascii=False, indent=1))
