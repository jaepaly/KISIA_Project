"""exp27 — 원래 표현을 넣은 글을 Gemini 로 쓰고, 같은 글에서 표현만 숨긴 판을 만든다 (README §1~2).

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python -u experiments/exp27-adversarial/generate.py   (GEMINI_API_KEY 는 환경변수)

출력: data/posts.jsonl — 쌍마다 두 줄 {post_id: P27_NN_plain|P27_NN_hidden, pair, variant, technique,
      texts:{body}, planted:[{start,end,text,type,subject}], gen_model}. 재실행하면 이미 만든 쌍은 건너뛴다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from kopl.c5_corpus import llm  # noqa: E402

OUT = HERE / "data" / "posts.jsonl"

# (유형, 방법, 원래, 숨김, 주제, 말투) — README §2 표와 같다
PAIRS = [
    ("AGE", "dot", "서른여섯", "서.른.여.섯", "새해 첫 주에 세운 운동 계획", "담백한 반말 일기"),
    ("AGE", "chosung", "스물넷", "ㅅㅁㄴ", "첫 월급으로 산 물건", "들뜬 구어체"),
    ("AGE", "roman", "마흔일곱", "forty-seven", "오랜만에 간 동창 모임", "차분한 존댓말"),
    ("AGE", "paraphrase", "쉰둘", "오십 줄 하고도 둘", "건강검진 받고 온 날", "느긋한 혼잣말"),
    ("LOC_ADMIN", "dot", "도봉구", "도.봉.구", "동네 산책길에서 본 단풍", "담백한 반말 일기"),
    ("LOC_ADMIN", "chosung", "영등포구", "ㅇㄷㅍ구", "이사 온 지 한 달 된 소감", "가벼운 구어체"),
    ("LOC_ADMIN", "roman", "사하구", "Saha-gu", "집 근처 시장 구경", "차분한 존댓말"),
    ("LOC_ADMIN", "paraphrase", "강릉", "경포대 있는 도시", "고향 집에서 보낸 주말", "느긋한 혼잣말"),
    ("LOC_FACILITY", "dot", "석촌호수", "석.촌.호.수", "퇴근 뒤 혼자 걷기", "담백한 반말 일기"),
    ("LOC_FACILITY", "chosung", "을지로입구역", "ㅇㅈㄹㅇㄱ역", "매일 아침 출근길", "투덜대는 구어체"),
    ("LOC_FACILITY", "roman", "광안대교", "Gwangan Bridge", "집 앞에서 보는 야경", "차분한 존댓말"),
    ("LOC_FACILITY", "paraphrase", "서울대입구역", "샤로수길 앞 역", "자주 가는 동네 카페", "가벼운 구어체"),
    ("JOB", "dot", "방사선사", "방.사.선.사", "야간 근무 끝난 아침", "담백한 반말 일기"),
    ("JOB", "chosung", "임상병리사", "ㅇㅅㅂㄹ사", "일하면서 생긴 습관", "투덜대는 구어체"),
    ("JOB", "roman", "간호조무사", "nurse aide", "이직을 고민하는 밤", "차분한 존댓말"),
    ("JOB", "paraphrase", "보육교사 일", "꼬맹이들 낮잠 재우는 일", "오늘 하루 제일 웃겼던 일", "느긋한 혼잣말"),
    ("FAM", "dot", "외동딸", "외.동.딸", "명절에 부모님 댁 간 이야기", "담백한 반말 일기"),
    ("FAM", "chosung", "새언니", "ㅅㅇㄴ", "조카 돌잔치 준비", "가벼운 구어체"),
    ("FAM", "roman", "처남", "brother-in-law", "주말에 같이 간 낚시", "차분한 존댓말"),
    ("FAM", "paraphrase", "형수", "형의 아내", "가족 모임에서 먹은 음식", "느긋한 혼잣말"),
]

SYSTEM = (
    "너는 한국어 SNS 일상 글을 쓰는 사람이다. 실제 사람이 쓴 것처럼 자연스럽게 쓴다. "
    "지정한 표현은 글자 하나 바꾸지 않고 그대로 넣는다(띄어쓰기·숫자·조사까지). "
    "지정하지 않은 개인정보(다른 지명·나이·직업·학교·회사 이름·가족 관계·금액)는 새로 넣지 않는다. "
    "학력·학교·전공·정치 성향·건강 상태는 쓰지 않는다. 해시태그·이모지는 쓰지 않는다. 글 본문만 출력한다."
)

WHO = {"AGE": "글쓴이 **자신의** 나이로", "LOC_ADMIN": "글쓴이가 **사는** 곳으로", "LOC_FACILITY": "글쓴이가 **자주 가는 · 사는 곳 근처의** 장소로",
       "JOB": "글쓴이 **자신의** 직업으로", "FAM": "글쓴이 **자신의** 가족 관계로"}


def prompt(t: str, plain: str, topic: str, voice: str) -> str:
    return (f"주제: {topic}\n말투: {voice}\n길이: 2~4문장\n"
            f"아래 표현을 글자 그대로 **딱 한 번** 넣어라 (따옴표는 빼고):\n- 「{plain}」 — {WHO[t]} (비유·남 이야기로 쓰지 말 것)\n"
            "표현이 문장 안에서 자연스럽게 읽히도록 앞뒤만 맞춰라.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gemini-3.6-flash,gemini-3.7-flash,gemini-3.8-flash,gemini-flash-latest,gemini-flash-lite-latest")
    ap.add_argument("--interval", type=float, default=7.0)
    a = ap.parse_args()
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    client = llm.LLMClient("gemini", model=models.pop(0), temperature=1.0, max_tokens=600, max_retries=2)

    def call(user: str) -> str:
        nonlocal client
        timeouts = 0
        while True:
            try:
                return client.complete(SYSTEM, user).strip()
            except llm.LLMError as e:
                if "timed out" in str(e) and timeouts < 5:  # 응답 시간 초과 — 쉬었다가 같은 모델로 다시
                    timeouts += 1
                    print(f"  시간 초과 {timeouts}회 — 30초 뒤 다시", flush=True)
                    time.sleep(30)
                    continue
                if ("429" in str(e) or "503" in str(e)) and models:
                    print(f"  {client.model} 한도·과부하 → {models[0]}", flush=True)
                    client = llm.LLMClient("gemini", model=models.pop(0), temperature=1.0, max_tokens=600, max_retries=2)
                    continue
                raise

    OUT.parent.mkdir(exist_ok=True)
    done = {json.loads(l)["pair"] for l in OUT.open(encoding="utf-8")} if OUT.exists() else set()
    kept = dropped = 0
    with OUT.open("a", encoding="utf-8", newline="\n") as f:
        for i, (t, tech, plain, hidden, topic, voice) in enumerate(PAIRS, 1):
            pair = f"P27_{i:02d}"
            if pair in done:
                continue
            for attempt in range(3):
                time.sleep(a.interval)
                body = call(prompt(t, plain, topic, voice))
                at = body.find(plain)
                if at >= 0 and body.find(plain, at + 1) < 0 and not client.last_truncated:
                    hidden_body = body[:at] + hidden + body[at + len(plain):]
                    for variant, text, expr in (("plain", body, plain), ("hidden", hidden_body, hidden)):
                        f.write(json.dumps({"post_id": f"{pair}_{variant}", "pair": pair, "variant": variant, "technique": tech,
                                            "texts": {"body": text},
                                            "planted": [{"start": at, "end": at + len(expr), "text": expr, "type": t, "subject": "self"}],
                                            "gen_model": client.version, "attempts": attempt + 1}, ensure_ascii=False) + "\n")
                    f.flush()
                    kept += 1
                    print(f"{pair} {t} {tech} ok", flush=True)
                    break
            else:
                dropped += 1
                print(f"  버림 {pair} — 표현이 정확히 한 번 안 들어감", flush=True)
    print(json.dumps({"kept": kept, "dropped": dropped, "calls": client.calls}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
