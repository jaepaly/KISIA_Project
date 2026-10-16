"""exp28b — 심을 표현 · 함정 · 주제 · 말투를 생성 전에 고정한다 (README §1).

    PYTHONIOENCODING=utf-8 python experiments/exp28b-context-review-v2/plan.py

D3(회귀 감시 · 교사 라벨 골드 300편) 목록도 data/d3_post_ids.json 으로 고정한다 (README §2).

출력: data/plan.jsonl — 글마다 {post_id, group, topic, voice, planted:[{text,type,how}], traps:[{text,kind,wrong,how}]}.
이미 쓴 판정셋(exp17 · 17b · 17c · 17d · 17e · exp27 · exp28) 글에 부분 문자열로 있는 표현이 있으면 멈춘다.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "data" / "plan.jsonl"
SEED = 20261017
USED = ["exp17-planted-eval", "exp17b-heldout-eval", "exp17c-final-eval", "exp17d-job-eval", "exp17e-job-dev", "exp27-adversarial", "exp28-context-review"]

SELF = "글쓴이 **자신의** "
# (표현, 유형, 쓰는 법) — A 묶음 40 · exp28 과 겹치지 않는 새 표현
A = [
    ("서른여덟", "AGE", SELF + "나이로"), ("이십대 초반", "AGE", SELF + "나이대로"), ("스물여섯", "AGE", SELF + "나이로"),
    ("84년생", "AGE", SELF + "출생 연도로"), ("사십대 후반", "AGE", SELF + "나이대로"), ("쉰셋", "AGE", SELF + "나이로"),
    ("서른 중반", "AGE", SELF + "나이대로"),
    ("동두천", "LOC_ADMIN", "글쓴이가 **사는** 곳으로"), ("오산", "LOC_ADMIN", "글쓴이가 **사는** 도시로"),
    ("양주", "LOC_ADMIN", "글쓴이가 **사는** 도시로"), ("상도동", "LOC_ADMIN", "글쓴이가 **사는** 동네로"),
    ("영천", "LOC_ADMIN", "글쓴이가 **사는** 도시로"), ("포항", "LOC_ADMIN", "글쓴이가 **사는** 도시로"),
    ("익산", "LOC_ADMIN", "글쓴이가 **사는** 도시로"),
    ("안양천", "LOC_FACILITY", "글쓴이가 **집 근처에서 자주 가는** 곳으로"), ("불광천", "LOC_FACILITY", "글쓴이가 **집 근처에서 자주 가는** 곳으로"),
    ("반월당역", "LOC_FACILITY", "글쓴이가 **매일 타는** 역으로"), ("율동공원", "LOC_FACILITY", "글쓴이가 **집 근처에서 자주 가는** 곳으로"),
    ("모락산", "LOC_FACILITY", "글쓴이가 **집 근처에서 자주 오르는** 산으로"),
    ("온새미로", "LOC_FACILITY", "글쓴이가 **단골인 동네 식당** 이름으로"), ("초록문방구", "LOC_FACILITY", "글쓴이가 **단골인 동네 가게** 이름으로"),
    ("요양보호사", "JOB", SELF + "직업으로"), ("콜센터 상담원", "JOB", SELF + "직업으로"), ("헬스 트레이너", "JOB", SELF + "직업으로"),
    ("네일아티스트", "JOB", SELF + "직업으로"), ("공무원", "JOB", SELF + "직업으로"), ("프리랜서 번역가", "JOB", SELF + "직업으로"),
    ("배달 라이더", "JOB", SELF + "일로"),
    ("세 살 아들 엄마", "FAM", SELF + "가족 구성으로"), ("결혼 7년차", "FAM", SELF + "생애 단계로"), ("외동아들", "FAM", SELF + "가족 안 위치로"),
    ("늦둥이 딸 아빠", "FAM", SELF + "가족 구성으로"), ("시댁 식구", "FAM", "글쓴이가 **결혼해 시댁이 있다**는 뜻으로"), ("돌싱", "FAM", SELF + "생애 단계로"),
    ("우이신설선", "COMMUTE", SELF + "출퇴근 노선으로"), ("마을버스 타고 출근", "COMMUTE", SELF + "출근 방법으로"), ("자전거 출퇴근", "COMMUTE", SELF + "출퇴근 방법으로"),
    ("1호선 급행", "COMMUTE", SELF + "출퇴근 노선으로"), ("출근 셔틀", "COMMUTE", SELF + "출근 수단으로"), ("KTX 출퇴근", "COMMUTE", SELF + "출퇴근 방법으로"),
]
BDAY = ["3월 3일", "7월 21일", "11월 11일", "1월 30일", "5월 16일", "8월 8일", "12월 24일", "2월 14일", "6월 25일", "9월 7일", "4월 19일", "10월 9일"]
PET = [("누룽지", "강아지"), ("호두", "고양이"), ("몽실", "강아지"), ("초코", "강아지"), ("별이", "고양이"), ("나비", "고양이"),
       ("루루", "강아지"), ("밤톨", "햄스터"), ("쿠키", "강아지"), ("깨비", "고양이"), ("젤리", "앵무새"), ("찹쌀", "고양이")]

ALL = ["AGE", "SEX", "LOC_ADMIN", "LOC_FACILITY", "REL_HOME", "REL_WORK", "JOB", "FAM", "COMMUTE", "INCOME"]
LOC = ["LOC_ADMIN", "LOC_FACILITY"]
# (표현, 종류, 오탐으로 세는 유형, 쓰는 법) — exp28 과 같은 종류 · 새 표현
TRAPS = [
    ("엄마가 해준", "parent", ["SEX"], "글쓴이의 어머니가 해준 것으로"), ("아빠한테 혼남", "parent", ["SEX"], "글쓴이가 아버지에게 혼난 이야기로"),
    ("엄마랑 싸워서", "parent", ["SEX"], "글쓴이가 어머니와 다툰 이야기로"), ("아빠 몰래", "parent", ["SEX"], "글쓴이가 아버지 몰래 한 일로"),
    ("엄마 생신", "parent", ["SEX"], "글쓴이 어머니의 생일 이야기로"), ("아빠가 데리러", "parent", ["SEX"], "글쓴이의 아버지가 데리러 온 이야기로"),
    ("엄마가 챙겨준", "parent", ["SEX"], "글쓴이의 어머니가 챙겨준 것으로"), ("아빠는 항상", "parent", ["SEX"], "글쓴이의 아버지 버릇 이야기로"),
    ("엄마 잔소리", "parent", ["SEX"], "글쓴이가 어머니에게 듣는 잔소리로"), ("아빠랑 낚시", "parent", ["SEX"], "글쓴이가 아버지와 낚시 간 이야기로"),
    ("개꿀", "meme", ALL, "아주 좋다는 유행어로"), ("핵노잼", "meme", ALL, "아주 재미없다는 유행어로"), ("출근지옥", "meme", ALL, "출근이 괴롭다는 농담으로"),
    ("월급 루팡", "meme", ALL, "일 안 하고 월급 받는다는 농담으로"), ("탕진잼", "meme", ALL, "돈 쓰는 재미라는 유행어로"),
    ("소확행", "meme", ALL, "작은 행복이라는 유행어로"), ("멘붕", "meme", ALL, "당황했다는 유행어로"), ("번아웃각", "meme", ALL, "지칠 것 같다는 농담으로"),
    ("주말순삭", "meme", ALL, "주말이 빨리 지났다는 유행어로"), ("킹받네", "meme", ALL, "짜증 난다는 유행어로"),
    ("꿀잠각", "meme", ALL, "푹 잘 것 같다는 유행어로"), ("친구가 교사라", "other", ["JOB"], "글쓴이 **친구의** 직업으로"),
    ("속리산 등산", "travel", LOC, "글쓴이가 **놀러 가서** 한 것으로"), ("다큐에 나온 지리산", "media", LOC, "글쓴이가 **본 다큐멘터리의 장소**로"),
    ("삿포로 여행", "travel", LOC, "글쓴이가 **여행으로 다녀온** 곳으로"), ("강릉 바다 보러", "travel", LOC, "글쓴이가 **놀러 간** 곳으로"),
    ("태안 캠핑", "travel", LOC, "글쓴이가 **놀러 가서** 한 것으로"), ("남해 드라이브", "travel", LOC, "글쓴이가 **놀러 가서** 한 것으로"),
    ("대만 여행", "travel", LOC, "글쓴이가 **여행으로 다녀온** 곳으로"), ("단양 패러글라이딩", "travel", LOC, "글쓴이가 **놀러 가서** 한 것으로"),
    ("괌 여행", "travel", LOC, "글쓴이가 **여행으로 다녀온** 곳으로"), ("보령 머드축제", "travel", LOC, "글쓴이가 **놀러 간** 곳으로"),
    ("홍콩 여행", "travel", LOC, "글쓴이가 **여행으로 다녀온** 곳으로"), ("안면도 놀러", "travel", LOC, "글쓴이가 **놀러 간** 곳으로"),
    ("언니가 은행원이라", "other", ["JOB"], "글쓴이 **언니의** 직업으로"), ("사촌동생이 열 살", "other", ["AGE"], "글쓴이 **사촌동생의** 나이로"),
    ("친구가 사는 송도", "other", LOC, "글쓴이 **친구가 사는** 곳으로"), ("친구 남편이 소방관", "other", ["JOB"], "글쓴이 **친구 남편의** 직업으로"),
    ("동료가 쉰 살", "other", ["AGE"], "글쓴이 **동료의** 나이로"), ("선배가 사는 판교", "other", LOC, "글쓴이 **선배가 사는** 곳으로"),
    ("이모가 약사", "other", ["JOB"], "글쓴이 **이모의** 직업으로"), ("대리님 고향인 목포", "other", LOC, "글쓴이 **회사 대리님의** 고향으로"),
    ("친구 딸이 다섯 살", "other", ["AGE"], "글쓴이 **친구 딸의** 나이로"),
    ("드라마 촬영지인 문경", "media", LOC, "글쓴이가 **본 드라마의 촬영지**로 (글쓴이와 관계없는 곳)"), ("영화 속 인천항", "media", LOC, "글쓴이가 **본 영화의 장면**으로"),
    ("예능에 나온 완도", "media", LOC, "글쓴이가 **본 예능의 촬영지**로"), ("웹툰 배경인 연남동", "media", LOC, "글쓴이가 **읽은 웹툰의 배경**으로"),
    ("뉴스에 나온 울릉도", "media", LOC, "글쓴이가 **본 뉴스의 장소**로"), ("유튜버가 간 영월", "media", LOC, "글쓴이가 **본 유튜브 영상의 장소**로"),
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
        out.append({"post_id": f"P28B_{n:02d}", "group": group, "topic": rng.choice(TOPICS), "voice": rng.choice(VOICES),
                    "planted": planted, "traps": tr})
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    test = set(json.load(open(ROOT / "data/corpus/v0/splits/test_post_ids.json", encoding="utf-8"))["post_ids"])
    assert len(test) == 255
    pool_d3 = []
    for g in sorted((ROOT / "data/corpus/v0/gold").glob("*_spans.jsonl")):
        for line in g.open(encoding="utf-8"):
            d = json.loads(line)
            if ("spans" in d and not d.get("reviewed") and d["post_id"] not in test and d["texts"].get("body")
                    and any(x["text_id"] == "body" for x in d["spans"])):
                pool_d3.append(d["post_id"])
    d3 = sorted(random.Random(SEED).sample(sorted(pool_d3), 300))
    (HERE / "data" / "d3_post_ids.json").write_text(json.dumps({"seed": SEED, "pool": len(pool_d3), "post_ids": d3}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"posts": len(out), "planted": sum(len(r["planted"]) for r in out), "traps": sum(len(r["traps"]) for r in out),
                      "trap_kinds": {k: sum(1 for r in out for t in r["traps"] if t["kind"] == k) for k in ["parent", "meme", "travel", "other", "media"]}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
