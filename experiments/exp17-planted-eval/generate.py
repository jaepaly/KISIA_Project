"""exp17: Gemini 로 「심은 단서」가 든 SNS 글을 쓰고, 정답 스팬을 문자열 일치로 고정한다.

    PYTHONPATH=src python experiments/exp17-planted-eval/generate.py --env <KISIA .env 경로>

- 생성기는 Gemini (코퍼스 GPT · 교사 Claude · 2단 Qwen 과 다른 계열 — 어느 1단 구성에도 유리하지 않게)
- 지정한 표현이 **그대로** 들어가지 않으면 최대 3번 다시 시키고, 그래도 안 되면 버린다
- 출력: data/posts.jsonl — {post_id, texts:{body}, planted:[{start,end,text,type,level,subject,variant}], distractors:[...]}
  재실행하면 이미 만든 글은 건너뛴다 (이어 쓰기)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from specs import build  # noqa: E402

from kopl.c5_corpus import llm  # noqa: E402

OUT = HERE / "data" / "posts.jsonl"

SYSTEM = (
    "너는 한국어 SNS 일상 글을 쓰는 사람이다. 실제 사람이 쓴 것처럼 자연스럽게 쓴다. "
    "지정한 표현은 글자 하나 바꾸지 않고 그대로 넣는다(띄어쓰기·숫자·조사까지). "
    "지정하지 않은 개인정보(다른 지명·나이·직업·학교·회사 이름·가족 관계·금액)는 새로 넣지 않는다. "
    "학력·학교·전공·정치 성향·건강 상태는 쓰지 않는다. 해시태그·이모지는 쓰지 않는다. 글 본문만 출력한다."
)


def prompt(spec: dict) -> str:
    lines = "\n".join(
        f"- 「{c['text']}」 — " + ("글쓴이 **자신의** 정보로 (비유·남 이야기로 쓰지 말 것)" if c["subject"] == "self"
                                  else "글쓴이가 아닌 **다른 사람의** 정보로")
        for c in spec["clues"])
    if spec["distractor"]:
        lines += f"\n- 「{spec['distractor']}」 — 나이가 아닌 수량·기간으로"
    return (f"주제: {spec['topic']}\n말투: {spec['voice']}\n길이: 2~4문장\n"
            f"아래 표현을 모두 글자 그대로 넣어라 (따옴표는 빼고):\n{lines}\n"
            "표현이 문장 안에서 자연스럽게 읽히도록 앞뒤만 맞춰라.")


def locate(body: str, spec: dict) -> dict | None:
    """심은 표현이 모두 그대로 있으면 정답 스팬 목록. 하나라도 없으면 None."""
    planted, cursor_used = [], set()
    for c in spec["clues"]:
        at = body.find(c["text"])
        if at < 0:
            return None
        s = at + c["text"].find(c["span"])
        if (s, c["type"]) in cursor_used:
            return None
        cursor_used.add((s, c["type"]))
        planted.append({"start": s, "end": s + len(c["span"]), "text": c["span"], "type": c["type"],
                        "level": c["level"], "subject": c["subject"], "variant": c["variant"], "clue": c["text"]})
    distractors = []
    if spec["distractor"]:
        at = body.find(spec["distractor"])
        if at < 0:
            return None
        distractors.append({"start": at, "end": at + len(spec["distractor"]), "text": spec["distractor"]})
    return {"planted": planted, "distractors": distractors}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--models", default="gemini-3.6-flash,gemini-3.7-flash,gemini-3.8-flash,gemini-flash-latest,gemini-flash-lite-latest",
                    help="무료 등급 한도가 모델당 하루 20회라, 한도(429)에 걸리면 다음 Gemini 모델로 넘어간다 (글마다 gen_model 기록)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--interval", type=float, default=7.0, help="호출 간격(초) — 분당 한도(429) 회피")
    a = ap.parse_args()
    llm.load_dotenv(a.env)
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    client = llm.LLMClient("gemini", model=models.pop(0), temperature=1.0, max_tokens=600, max_retries=2)

    def call(spec: dict) -> str:
        nonlocal client
        while True:
            try:
                return client.complete(SYSTEM, prompt(spec)).strip()
            except llm.LLMError as e:
                if ("429" in str(e) or "503" in str(e)) and models:
                    print(f"  {client.model} 한도·과부하 → {models[0]}", flush=True)
                    client = llm.LLMClient("gemini", model=models.pop(0), temperature=1.0, max_tokens=600, max_retries=2)
                    continue
                raise
    OUT.parent.mkdir(exist_ok=True)
    done = {json.loads(l)["post_id"] for l in OUT.open(encoding="utf-8")} if OUT.exists() else set()
    specs = [s for s in build() if s["post_id"] not in done]
    if a.limit:
        specs = specs[: a.limit]
    kept = dropped = 0
    with OUT.open("a", encoding="utf-8") as f:
        for spec in specs:
            for attempt in range(3):
                time.sleep(a.interval)
                body = call(spec)
                found = locate(body, spec)
                if found and not client.last_truncated:
                    f.write(json.dumps({"post_id": spec["post_id"], "texts": {"body": body}, **found,
                                        "voice": spec["voice"], "topic": spec["topic"], "gen_model": client.version,
                                        "attempts": attempt + 1}, ensure_ascii=False) + "\n")
                    f.flush()
                    kept += 1
                    break
            else:
                dropped += 1
                print(f"  버림 {spec['post_id']} — 지정 표현이 그대로 안 들어감", flush=True)
    print(json.dumps({"kept": kept, "dropped": dropped, "calls": client.calls, "usage": client.usage}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
