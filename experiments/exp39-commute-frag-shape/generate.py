"""exp39 — 판정셋 글 생성. 표현을 심지 않고 주제 · 말투만 주어 자유롭게 쓴다(이동이 나오기 쉬운 일상 주제). exp29 generate.py 의 호출부를 쓴다.

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python -u experiments/exp39-commute-frag-shape/generate.py   (GEMINI_API_KEY 는 환경변수)
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

PLAN = HERE / "data" / "plan.jsonl"
OUT = HERE / "data" / "posts.jsonl"
SYSTEM = (
    "너는 한국어 개인 블로그에 일상 글을 쓰는 사람이다. 실제 사람이 폰으로 대충 쓴 것처럼 자연스럽게 쓴다 — "
    "짧은 줄 여러 개, ㅋㅋ · ㅠㅠ · 이모지 · 줄임말을 말투에 맞게 섞어도 된다. "
    "학력 · 학교 · 전공 · 정치 성향 · 건강 상태는 쓰지 않는다. 실존 인물 이름은 쓰지 않는다. 해시태그는 쓰지 않는다. 제목 없이 글 본문만 출력한다."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gemini-3.6-flash,gemini-3.7-flash,gemini-3.8-flash,gemini-flash-latest,gemini-flash-lite-latest,gemini-3.1-flash-lite,gemini-3-flash-preview")
    ap.add_argument("--interval", type=float, default=7.0)
    a = ap.parse_args()
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    client = llm.LLMClient("gemini", model=models.pop(0), temperature=1.0, max_tokens=900, max_retries=2)
    plan = [json.loads(l) for l in PLAN.open(encoding="utf-8")]
    done = {json.loads(l)["post_id"] for l in OUT.open(encoding="utf-8")} if OUT.exists() else set()
    with OUT.open("a", encoding="utf-8", newline="\n") as f:
        for r in plan:
            if r["post_id"] in done:
                continue
            user = f"주제: {r['topic']}\n말투: {r['voice']}\n길이: 5~10줄"
            while True:
                time.sleep(a.interval)
                try:
                    body = client.complete(SYSTEM, user).strip()
                    break
                except llm.LLMError as e:
                    if ("429" in str(e) or "503" in str(e) or "timed out" in str(e)) and models:
                        print(f"  {client.model} 실패 → {models[0]}", flush=True)
                        client = llm.LLMClient("gemini", model=models.pop(0), temperature=1.0, max_tokens=900, max_retries=2)
                        continue
                    raise
            if client.last_truncated or not body:
                print(f"  버림 {r['post_id']}", flush=True)
                continue
            f.write(json.dumps({"post_id": r["post_id"], "topic": r["topic"], "voice": r["voice"], "texts": {"body": body},
                                "gen_model": client.version}, ensure_ascii=False) + "\n")
            f.flush()
            print(r["post_id"], "ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
