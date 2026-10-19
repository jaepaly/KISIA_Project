"""exp30 — 학습용 함정 보강 합성 글 (README §2). 코퍼스에 함정 문맥이 거의 없어서 Gemini 로 메운다.

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python -u experiments/exp30-review-distill/aug_generate.py   (GEMINI_API_KEY 는 환경변수)

표현 목록을 고정하지 않는다 — 문맥 종류 · 주제 · 말투만 정하고 지명 · 말은 Gemini 가 고른다. 정답은 교사(Claude)가 단다.
D1c(판정셋)와 섞이지 않게: 1단이 잡은 장소 문자열이 D1c 1단 결과의 장소와 같으면 그 글은 학습에서 뺀다(`filter_aug.py` · 교사 전).
출력: data/aug_posts.jsonl — {post_id, kinds, topic, voice, texts:{body}, gen_model}. 이어 돌리면 만든 글은 건너뛴다.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from kopl.c5_corpus import llm  # noqa: E402

OUT = HERE / "data" / "aug_posts.jsonl"
SEED = 20261019
N = 160

SYSTEM = (
    "너는 한국어 개인 블로그에 일상 글을 쓰는 사람이다. 실제 사람이 폰으로 대충 쓴 것처럼 자연스럽게 쓴다 — "
    "짧은 줄 여러 개, ㅋㅋ · ㅠㅠ · 이모지 · 줄임말을 말투에 맞게 섞어도 된다. "
    "학력 · 학교 · 전공 · 정치 성향 · 건강 상태는 쓰지 않는다. 실존 인물 이름은 쓰지 않는다. 해시태그는 쓰지 않는다. 제목 없이 글 본문만 출력한다."
)
KINDS = {
    "media": "글쓴이가 **가 보지 않고** 드라마 · 영화 · 예능 · 뉴스 · 유튜브 · 웹툰 · 광고 등에서 **보기만 한** 실제 지명이나 장소 하나",
    "travel": "글쓴이가 여행 · 휴가 · 놀러 · 출장으로 간 지명 하나 (그 말이 지명을 직접 꾸미게)",
    "visit": "글쓴이가 여행이라는 말 없이 **직접 다녀온** 지명이나 장소 하나 (주말에 들른 곳 등)",
    "home_media": "글쓴이가 **사는 동네나 늘 다니는 곳**인데 매체(뉴스 · 예능 · 드라마 · 유튜브)에 나왔다는 이야기 하나",
    "other": "다른 사람(친구 · 동료 · 친척 · 이웃)의 나이 · 직업 · 사는 곳 중 하나 — 문장에서 그 사람 것임이 분명하게",
    "parent": "글쓴이의 엄마나 아빠 이야기 하나",
    "family_self": "글쓴이의 배우자 · 형제 · 자녀 이야기 하나 (남편 · 아내 · 누나 · 형 · 아들 · 딸 같은 호칭으로)",
    "meme": "장소 · 직업 · 나이처럼 보이지만 실제로는 유행어나 농담인 말 하나",
    "self": "글쓴이 자신의 나이 · 직업 · 사는 곳 · 출퇴근 수단 중 하나",
}
TOPICS = ["점심 메뉴", "주말 청소", "새로 산 운동화", "비 오는 날", "다이어트", "넷플릭스 정주행", "카페 신메뉴", "장보기", "택배",
          "이불 빨래", "아침 산책", "야식", "중고 거래", "화분 키우기", "커피 원두", "휴대폰 바꿈", "독서", "가계부", "미용실", "명절 준비"]
VOICES = ["20대 직장인 말투", "30대 직장인 말투", "40대 주부 말투", "50대 자영업자 말투", "60대 은퇴자 말투", "30대 프리랜서 말투"]


def plan() -> list[dict]:
    rng = random.Random(SEED)
    names = list(KINDS)
    rows = []
    for i in range(N):
        kinds = rng.sample(names, 3)
        rows.append({"post_id": f"AUG30_{i + 1:03d}", "kinds": kinds, "topic": rng.choice(TOPICS), "voice": rng.choice(VOICES)})
    return rows


def prompt(r: dict) -> str:
    items = "\n".join(f"- {KINDS[k]}" for k in r["kinds"])
    return (f"주제: {r['topic']}\n말투: {r['voice']}\n길이: 5~10줄\n아래 내용을 글 안에 자연스럽게 각각 한 번씩 넣어라:\n{items}\n"
            "지명 · 장소는 실제 한국(또는 해외 여행지) 이름을 쓰되, 서울 · 부산 · 제주 같은 흔한 이름만 쓰지 말고 다양하게.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gemini-3.6-flash,gemini-3.7-flash,gemini-3.8-flash,gemini-flash-latest,gemini-flash-lite-latest")
    ap.add_argument("--interval", type=float, default=7.0)
    a = ap.parse_args()
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    client = llm.LLMClient("gemini", model=models.pop(0), temperature=1.0, max_tokens=900, max_retries=2)
    done = {json.loads(l)["post_id"] for l in OUT.open(encoding="utf-8")} if OUT.exists() else set()
    kept = 0
    with OUT.open("a", encoding="utf-8", newline="\n") as f:
        for r in plan():
            if r["post_id"] in done:
                continue
            time.sleep(a.interval)
            while True:
                try:
                    body = client.complete(SYSTEM, prompt(r)).strip()
                    break
                except llm.LLMError as e:
                    if ("429" in str(e) or "503" in str(e) or "timed out" in str(e)) and models:
                        print(f"  {client.model} 한도·과부하 → {models[0]}", flush=True)
                        client = llm.LLMClient("gemini", model=models.pop(0), temperature=1.0, max_tokens=900, max_retries=2)
                        continue
                    raise
            if client.last_truncated or len(body) < 80:
                print(f"  버림 {r['post_id']} — 잘림 · 너무 짧음", flush=True)
                continue
            f.write(json.dumps({**r, "texts": {"body": body}, "gen_model": client.version}, ensure_ascii=False) + "\n")
            f.flush()
            kept += 1
            print(f"{r['post_id']} ok", flush=True)
    print(json.dumps({"kept": kept, "calls": client.calls}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
