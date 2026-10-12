"""exp17e (1단 JOB 오탐 개발용 — 후보 고르기): exp17d 생성기 그대로 · 명세만 specs.py 의 다른 표현. exp17c 생성기 — Gemini 로 「심은 단서」와 「함정」이 든 SNS 글을 쓰고,
정답 스팬을 문자열 일치로 고정한다. exp17c 와 다른 점은 함정이 여러 개 · 유형별(AGE 숫자 · JOB 일상 표현)이라는 것뿐이다.

    PYTHONPATH=src python experiments/exp17e-job-dev/generate.py --env .env   (GEMINI_API_KEY 는 환경변수로)

- 생성기는 Gemini (코퍼스 GPT · 교사 Claude · 2단 Qwen 과 다른 계열 — 어느 1단 구성에도 유리하지 않게)
- 지정한 표현이 **그대로** 들어가지 않으면 최대 3번 다시 시키고, 그래도 안 되면 버린다
- 출력: data/posts.jsonl — {post_id, kind, texts:{body}, planted:[{start,end,text,type,level,subject,variant,group}],
  distractors:[{start,end,text,type,variant}]}
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
    for d in spec["distractors"]:
        lines += (f"\n- 「{d['text']}」 — 나이가 아닌 수량·순서로" if d["type"] == "AGE"
                  else f"\n- 「{d['text']}」 — 글쓴이의 **직업과 상관없는** 일상 이야기로 (직업·직장을 짐작하게 쓰지 말 것)")
    return (f"주제: {spec['topic']}\n말투: {spec['voice']}\n길이: 2~4문장\n"
            f"아래 표현을 모두 글자 그대로 넣어라 (따옴표는 빼고):\n{lines}\n"
            "표현이 문장 안에서 자연스럽게 읽히도록 앞뒤만 맞춰라.")


def locate(body: str, spec: dict) -> dict | None:
    """심은 표현 · 함정이 모두 **정확히 한 번씩** 있고 서로 겹치지 않으면 정답 스팬 목록. 아니면 None (다시 생성).
    두 번 나오면 어느 쪽이 정답인지 정할 수 없고, 함정이 단서 안에 들어가면 함정 오탐과 정답 탐지가 섞인다 (Codex 10/12)."""
    def once(text: str) -> int:
        first = body.find(text)
        return first if first >= 0 and body.find(text, first + 1) < 0 else -1

    planted, taken = [], []
    for c in spec["clues"]:
        at, off = once(c["text"]), c["text"].find(c["span"])
        if at < 0 or off < 0:
            return None
        planted.append({"start": at + off, "end": at + off + len(c["span"]), "text": c["span"], "type": c["type"],
                        "level": c["level"], "subject": c["subject"], "variant": c["variant"], "group": c["group"], "clue": c["text"]})
        taken.append((at, at + len(c["text"])))
    distractors = []
    for d in spec["distractors"]:
        at = once(d["text"])
        if at < 0:
            return None
        taken.append((at, at + len(d["text"])))
        distractors.append({"start": at, "end": at + len(d["text"]), **d})
    taken.sort()
    if any(b[0] < a[1] for a, b in zip(taken, taken[1:])):
        return None
    return {"planted": planted, "distractors": distractors}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--models", default="gemini-3.6-flash,gemini-3.7-flash,gemini-3.8-flash,gemini-flash-latest,gemini-flash-lite-latest",
                    help="한도·과부하(429·503) 응답이 오면 다음 Gemini 모델로 넘어간다 (글마다 gen_model 기록)")
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
                                        "kind": spec["kind"], "voice": spec["voice"], "topic": spec["topic"], "gen_model": client.version,
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
