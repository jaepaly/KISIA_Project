"""exp28 — 심을 표현 · 함정 · 주제 · 말투를 생성 전에 고정한다 (README §1).

    PYTHONIOENCODING=utf-8 python experiments/exp28-context-review/plan.py

출력: data/plan.jsonl — 글마다 {post_id, group, topic, voice, planted:[{text,type,how}], traps:[{text,kind,wrong,how}]}.
이미 쓴 판정셋(exp17 · 17b · 17c · 17d · 17e · exp27) 글에 부분 문자열로 있는 표현이 있으면 멈춘다.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "data" / "plan.jsonl"
SEED = 20261016
USED = ["exp17-planted-eval", "exp17b-heldout-eval", "exp17c-final-eval", "exp17d-job-eval", "exp17e-job-dev", "exp27-adversarial"]

SELF = "글쓴이 **자신의** "
# (표현, 유형, 쓰는 법) — A 묶음 40
A = [
    ("서른셋", "AGE", SELF + "나이로"), ("삼십대 중반", "AGE", SELF + "나이대로"), ("서른하나", "AGE", SELF + "나이로"),
    ("96년생", "AGE", SELF + "출생 연도로"), ("마흔 코앞", "AGE", SELF + "나이로 (곧 마흔이라는 뜻)"),
    ("이십대 끝자락", "AGE", SELF + "나이대로"), ("쉰 넘어서", "AGE", SELF + "나이로 (쉰이 넘은 뒤로)"),
    ("연희동", "LOC_ADMIN", "글쓴이가 **사는** 동네로"), ("일산", "LOC_ADMIN", "글쓴이가 **사는** 곳으로"),
    ("화정", "LOC_ADMIN", "글쓴이가 **사는** 동네로"), ("수성구", "LOC_ADMIN", "글쓴이가 **사는** 곳으로"),
    ("천안", "LOC_ADMIN", "글쓴이가 **사는** 도시로"), ("부평", "LOC_ADMIN", "글쓴이가 **사는** 곳으로"),
    ("거제", "LOC_ADMIN", "글쓴이가 **사는** 도시로"),
    ("탄천", "LOC_FACILITY", "글쓴이가 **집 근처에서 자주 가는** 곳으로"), ("홍제천", "LOC_FACILITY", "글쓴이가 **집 근처에서 자주 가는** 곳으로"),
    ("범어역", "LOC_FACILITY", "글쓴이가 **매일 타는** 역으로"), ("동탄호수공원", "LOC_FACILITY", "글쓴이가 **집 근처에서 자주 가는** 곳으로"),
    ("일월저수지", "LOC_FACILITY", "글쓴이가 **집 근처에서 자주 가는** 곳으로"),
    ("달빛상회", "LOC_FACILITY", "글쓴이가 **단골인 동네 가게** 이름으로"), ("소금빵공방", "LOC_FACILITY", "글쓴이가 **단골인 동네 빵집** 이름으로"),
    ("물류센터 야간조", "JOB", SELF + "일로"), ("치과기공사", "JOB", SELF + "직업으로"), ("학원 강사", "JOB", SELF + "직업으로"),
    ("편의점 사장", "JOB", SELF + "직업으로"), ("월급쟁이", "JOB", "글쓴이가 **회사에 다니는 사람**이라는 뜻으로 (예: 월급쟁이의 주말)"),
    ("대리기사", "JOB", SELF + "직업으로"), ("웹디자이너", "JOB", SELF + "직업으로"),
    ("두 아이 엄마", "FAM", SELF + "가족 구성으로"), ("신혼 3개월차", "FAM", SELF + "생애 단계로"), ("막내딸", "FAM", SELF + "가족 안 위치로"),
    ("쌍둥이 아빠", "FAM", SELF + "가족 구성으로"), ("예비신부", "FAM", SELF + "생애 단계로"), ("할머니랑 둘이", "FAM", "글쓴이가 **할머니와 둘이 산다**는 뜻으로"),
    ("신분당선", "COMMUTE", SELF + "출퇴근 노선으로"), ("빨간버스", "COMMUTE", SELF + "출퇴근 수단으로"), ("따릉이로 출근", "COMMUTE", SELF + "출근 방법으로"),
    ("경의중앙선", "COMMUTE", SELF + "출퇴근 노선으로"), ("카풀", "COMMUTE", SELF + "출퇴근 방법으로"), ("통근버스", "COMMUTE", SELF + "출퇴근 수단으로"),
]
# B 묶음 24 — 생일 날짜는 「내 생일」 문맥에서 날짜 문자열을, 반려동물은 이름을 심는다
BDAY = ["3월 14일", "7월 2일", "11월 23일", "1월 9일", "5월 30일", "8월 17일", "12월 5일", "2월 27일", "6월 11일", "9월 19일", "4월 8일", "10월 28일"]
PET = [("버터", "강아지"), ("치즈", "고양이"), ("호떡", "강아지"), ("모카", "고양이"), ("꼬미", "강아지"), ("뭉치", "고양이"),
       ("보송이", "강아지"), ("까미", "고양이"), ("단풍", "강아지"), ("망고", "앵무새"), ("솜이", "고양이"), ("도토리", "햄스터")]

ALL = ["AGE", "SEX", "LOC_ADMIN", "LOC_FACILITY", "REL_HOME", "REL_WORK", "JOB", "FAM", "COMMUTE", "INCOME"]
LOC = ["LOC_ADMIN", "LOC_FACILITY"]
# (표현, 종류, 오탐으로 세는 유형, 쓰는 법) — 96개 필요(A 40 + B 24 + C 32)
TRAPS = [
    ("엄마가 끓여준", "parent", ["SEX"], "글쓴이의 어머니 이야기로"), ("아빠한테 혼나서", "parent", ["SEX"], "글쓴이가 아버지에게 혼난 이야기로"),
    ("엄마 몰래", "parent", ["SEX"], "글쓴이가 어머니 몰래 한 일로"), ("아빠 차 빌려서", "parent", ["SEX"], "글쓴이가 아버지 차를 빌린 이야기로"),
    ("엄마는 맨날", "parent", ["SEX"], "글쓴이의 어머니 버릇 이야기로"), ("아빠가 보내준", "parent", ["SEX"], "글쓴이의 아버지가 보내준 것으로"),
    ("엄마가 사준", "parent", ["SEX"], "글쓴이의 어머니가 사준 것으로"), ("아빠는 또", "parent", ["SEX"], "글쓴이의 아버지 버릇 이야기로"),
    ("엄마한테 전화", "parent", ["SEX"], "글쓴이가 어머니에게 전화한 이야기로"), ("아빠 생신", "parent", ["SEX"], "글쓴이 아버지의 생일 이야기로"),
    ("엄마 닮아서", "parent", ["SEX"], "글쓴이가 어머니를 닮았다는 말로"), ("아빠랑 통화", "parent", ["SEX"], "글쓴이가 아버지와 통화한 이야기로"),
    ("뷰맛집", "meme", ALL, "경치가 좋다는 평가말로"), ("분위기맛집", "meme", ALL, "분위기가 좋다는 평가말로"),
    ("야근행", "meme", ALL, "야근하게 됐다는 농담으로"), ("다이어트 실패행", "meme", ALL, "다이어트를 망쳤다는 농담으로"),
    ("퇴사각", "meme", ALL, "그만두고 싶을 만큼 힘들다는 농담으로"), ("갓생", "meme", ALL, "부지런한 삶이라는 유행어로"),
    ("꿀잼각", "meme", ALL, "재미있겠다는 유행어로"), ("텅장", "meme", ALL, "통장이 비었다는 유행어로"),
    ("현생", "meme", ALL, "현실 생활이라는 유행어로"), ("지옥행 열차", "meme", ALL, "힘든 일정이라는 농담으로"),
    ("존맛탱", "meme", ALL, "아주 맛있다는 유행어로"), ("인생샷 명소", "meme", ALL, "사진이 잘 나온다는 평가말로"),
    ("후쿠오카 여행", "travel", LOC, "글쓴이가 **여행으로 다녀온** 곳으로"), ("속초 놀러", "travel", LOC, "글쓴이가 **놀러 간** 곳으로"),
    ("다낭 가서", "travel", LOC, "글쓴이가 **여행 가서** 겪은 일로"), ("오사카 여행", "travel", LOC, "글쓴이가 **여행으로 다녀온** 곳으로"),
    ("경주 당일치기", "travel", LOC, "글쓴이가 **하루 놀러 간** 곳으로"), ("여수 밤바다 보러", "travel", LOC, "글쓴이가 **놀러 간** 곳으로"),
    ("방콕 여행", "travel", LOC, "글쓴이가 **여행으로 다녀온** 곳으로"), ("가평 펜션", "travel", LOC, "글쓴이가 **놀러 가서 묵은** 곳으로"),
    ("전주 한옥마을", "travel", LOC, "글쓴이가 **놀러 간** 곳으로"), ("타이베이 여행", "travel", LOC, "글쓴이가 **여행으로 다녀온** 곳으로"),
    ("양양 서핑", "travel", LOC, "글쓴이가 **놀러 가서** 한 것으로"), ("담양 죽녹원", "travel", LOC, "글쓴이가 **놀러 간** 곳으로"),
    ("친구가 간호사라", "other", ["JOB"], "글쓴이 **친구의** 직업으로"), ("동생이 군인이라", "other", ["JOB"], "글쓴이 **동생의** 직업으로"),
    ("조카가 일곱 살", "other", ["AGE"], "글쓴이 **조카의** 나이로"), ("아랫집 아저씨", "other", ["AGE", "SEX"], "글쓴이 **이웃** 이야기로"),
    ("친구네 동네인 분당", "other", LOC, "글쓴이 **친구가 사는** 곳으로"), ("남친이 개발자", "other", ["JOB"], "글쓴이 **남자친구의** 직업으로"),
    ("팀장님이 마흔", "other", ["AGE"], "글쓴이 **팀장의** 나이로"), ("사촌언니가 사는 대전", "other", LOC, "글쓴이 **사촌이 사는** 곳으로"),
    ("친구 아버지가 의사", "other", ["JOB"], "글쓴이 **친구 아버지의** 직업으로"), ("룸메가 경찰", "other", ["JOB"], "글쓴이 **룸메이트의** 직업으로"),
    ("드라마 배경인 군산", "media", LOC, "글쓴이가 **본 드라마의 배경**으로 (글쓴이와 관계없는 곳)"), ("영화에 나온 남산", "media", LOC, "글쓴이가 **본 영화의 장면**으로"),
    ("예능에 나온 통영", "media", LOC, "글쓴이가 **본 예능의 촬영지**로"), ("웹툰 속 성수동", "media", LOC, "글쓴이가 **읽은 웹툰의 배경**으로"),
    ("뉴스에 나온 제주", "media", LOC, "글쓴이가 **본 뉴스의 장소**로"), ("유튜버가 간 을왕리", "media", LOC, "글쓴이가 **본 유튜브 영상의 장소**로"),
]
TOPICS = ["주말에 한 일", "퇴근하고 생긴 일", "요즘 빠진 취미", "비 오는 날 기록", "오늘 먹은 것들", "새로 산 물건 후기", "아침 루틴",
          "운동 기록", "기분 꿀꿀한 날", "오랜만에 쉰 날", "장 본 날", "청소한 날", "밤에 혼자 생각", "카페에서 쓴 글", "월요병",
          "월급날", "늦잠 잔 날", "산책 기록", "친구랑 수다", "가을 타는 중"]
VOICES = ["ㅋㅋ 많은 반말 일기", "ㅠㅠ 섞인 투덜대는 반말", "이모지 섞인 들뜬 반말", "짧은 줄 여러 개로 끊어 쓰는 반말",
          "존댓말 블로그 후기체", "띄어쓰기 대충 하는 빠른 반말"]


def main() -> int:
    rng = random.Random(SEED)
    traps = TRAPS[:]
    assert len(traps) >= 96 // 2, len(traps)
    rng.shuffle(traps)
    pool = traps + traps  # 96 개 자리 — 같은 함정을 두 글에 쓴다(다른 글 · 다른 주제)
    rows = []
    for i, (text, t, how) in enumerate(A):
        rows.append(("A", [{"text": text, "type": t, "how": how}], 1))
    for d in BDAY:
        rows.append(("B", [{"text": d, "type": "BIRTHDAY", "how": f"글쓴이 **자신의** 생일 날짜로 (「{d}」이 내 생일이라는 문맥)"}], 1))
    for name, kind in PET:
        rows.append(("B", [{"text": name, "type": "PET_NAME", "how": f"글쓴이가 **키우는 {kind}** 이름으로 (이 글에서 이 이름은 이 한 번만)"}], 1))
    for _ in range(16):
        rows.append(("C", [], 2))
    assert len(rows) == 80 and sum(n for *_, n in rows) == 96

    used = "\n".join(json.loads(l)["texts"]["body"] for x in USED for l in (ROOT / "experiments" / x / "data" / "posts.jsonl").open(encoding="utf-8"))
    clash = sorted({e for e in [r[0] for r in A] + BDAY + [p for p, _ in PET] + [t[0] for t in TRAPS] if e in used})
    if clash:
        print("이미 쓴 판정셋에 있는 표현:", clash)
        return 1

    k = 0
    out = []
    for n, (group, planted, ntrap) in enumerate(rows, 1):
        tr = []
        while len(tr) < ntrap:
            cand = pool[k]
            k += 1
            if any(cand[0] in p["text"] or p["text"] in cand[0] for p in planted) or any(cand[0] == x["text"] for x in tr):
                pool.append(cand)
                continue
            tr.append({"text": cand[0], "kind": cand[1], "wrong": cand[2], "how": cand[3]})
        out.append({"post_id": f"P28_{n:02d}", "group": group, "topic": rng.choice(TOPICS), "voice": rng.choice(VOICES),
                    "planted": planted, "traps": tr})
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"posts": len(out), "planted": sum(len(r["planted"]) for r in out), "traps": sum(len(r["traps"]) for r in out),
                      "trap_kinds": {k: sum(1 for r in out for t in r["traps"] if t["kind"] == k) for k in ["parent", "meme", "travel", "other", "media"]}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
