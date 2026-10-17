"""exp31 — 대조 보강 합성 글 (README §3). exp30 학생이 배운 지름길(매체 · 여행 말 옆이면 내림 · 가족 호칭을 other)을 깨는 짝을 한 글에 넣는다.

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python -u experiments/exp31-distill-v2/aug2_generate.py   (GEMINI_API_KEY 는 환경변수)

글마다 대조 짝 하나(같은 말 · 반대 정답) + 다른 종류 하나. 표현 목록은 고정하지 않는다 — 지명 · 말은 Gemini 가 고르고 정답은 교사(Claude)가 단다.
D1d(판정셋)와 섞이지 않게 교사 라벨 전에 `filter_aug2.py` 로 거른다.
출력: data/aug2_posts.jsonl — {post_id, kinds, topic, voice, texts:{body}, gen_model}. 이어 돌리면 만든 글은 건너뛴다.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from kopl.c5_corpus import llm  # noqa: E402

_spec = importlib.util.spec_from_file_location("aug30", HERE.parent / "exp30-review-distill" / "aug_generate.py")
aug30 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aug30)

OUT = HERE / "data" / "aug2_posts.jsonl"
SEED = 20261022
N = 200

KINDS = {
    "home_media": "글쓴이가 **사는 동네나 매일 다니는 곳**(지명 · 시설)이 매체(뉴스 · 예능 · 드라마 · 유튜브 · 웹툰 등)에 나왔다는 이야기 — "
                  "「우리 · 내 · 제」 같은 말 없이 「십 년째 사는」 「매일 지나는」 「점심마다 가는」처럼 생활 표현으로만 드러내고, 매체 말을 지명 바로 옆에 둘 것",
    "media": "글쓴이가 **가 보지 않고** 매체(드라마 · 영화 · 예능 · 뉴스 · 유튜브 · 웹툰 등)에서 보기만 한 실제 지명이나 장소 하나",
    "home_travel": "글쓴이가 **사는 동네나 늘 다니는 곳**인데 여행 · 관광 · 놀러 같은 말이 옆에 오는 이야기(관광객이 몰리는 내 생활권 · 놀러 온 사람을 데리고 간 내 단골 등) — "
                   "「우리 · 내」 같은 말 없이 생활 표현으로 드러낼 것",
    "travel": "글쓴이가 여행 · 휴가 · 놀러 · 출장으로 간 지명 하나 (그 말이 지명을 직접 꾸미게)",
    "family_self": "글쓴이의 배우자 · 형제 · 자녀 이야기 하나 (남편 · 아내 · 와이프 · 신랑 · 누나 · 형 · 오빠 · 언니 · 남동생 · 아들 · 딸 같은 호칭으로)",
    "parent": "글쓴이의 엄마나 아빠(어머니 · 아버지 · 친정엄마 · 시아버지 등) 이야기 하나",
    "other": "다른 사람(친구 · 동료 · 친척 · 이웃)의 나이 · 직업 · 사는 곳 중 하나 — 문장에서 그 사람 것임이 분명하게",
    "self": "글쓴이 자신의 나이 · 직업 · 사는 곳 · 출퇴근 수단 중 하나",
    "visit": "글쓴이가 여행이라는 말 없이 **직접 다녀온** 지명이나 장소 하나 (주말에 들른 곳 등)",
}
PAIRS = [("home_media", "media"), ("home_travel", "travel"), ("family_self", "parent")]


def plan(n: int = N) -> list[dict]:
    rng = random.Random(SEED)
    rows = []
    for i in range(n):
        pair = PAIRS[i % 3]
        rest = [k for k in KINDS if k not in pair]
        kinds = list(pair) + [rng.choice(rest)]
        rng.shuffle(kinds)
        rows.append({"post_id": f"AUG31_{i + 1:03d}", "kinds": kinds, "topic": rng.choice(aug30.TOPICS), "voice": rng.choice(aug30.VOICES)})
    return rows


def prompt(r: dict, avoid: list[str] = ()) -> str:
    items = "\n".join(f"- {KINDS[k]}" for k in r["kinds"])
    ban = f"\n다음 지명 · 장소는 쓰지 마라: {' · '.join(avoid)}" if avoid else ""
    return (f"주제: {r['topic']}\n말투: {r['voice']}\n길이: 5~10줄\n아래 내용을 글 안에 자연스럽게 각각 한 번씩 넣어라:\n{items}\n"
            "지명 · 장소는 실제 한국(또는 해외 여행지) 이름을 쓰되, 서울 · 부산 · 제주 같은 흔한 이름만 쓰지 말고 전국으로 다양하게." + ban)


def avoid_words() -> list[str]:
    """2차 생성(README §7): 거르기에서 걸리는 장소 이름(D1d 1단 LOC 조각)을 미리 피하게 한다 — D1d 표현 문장은 주지 않는다."""
    import re
    from kopl.c1_span.attributes import _core
    out = set()
    for line in open(HERE / "results" / "a0_d1d.jsonl", encoding="utf-8"):
        for s in json.loads(line)["spans"]:
            c = _core(s["text"])
            if s["type"] in ("LOC_ADMIN", "LOC_FACILITY") and len(c) >= 2 and not re.fullmatch(r"(?:에서|에게|으로|부터|까지|한테|처럼|에도)", c):
                out.add(c)
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gemini-3.6-flash,gemini-3.7-flash,gemini-3.8-flash,gemini-flash-latest,gemini-flash-lite-latest")
    ap.add_argument("--interval", type=float, default=7.0)
    ap.add_argument("--n", type=int, default=N, help="2차 생성은 450 (AUG31_201~)")
    a = ap.parse_args()
    avoid = avoid_words() if a.n > N else []
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    client = llm.LLMClient("gemini", model=models.pop(0), temperature=1.0, max_tokens=900, max_retries=2)
    OUT.parent.mkdir(exist_ok=True)
    done = {json.loads(l)["post_id"] for l in OUT.open(encoding="utf-8")} if OUT.exists() else set()
    kept = 0
    with OUT.open("a", encoding="utf-8", newline="\n") as f:
        for r in plan(a.n):
            if r["post_id"] in done:
                continue
            time.sleep(a.interval)
            while True:
                try:
                    body = client.complete(aug30.SYSTEM, prompt(r, avoid if int(r["post_id"][-3:]) > N else [])).strip()
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
