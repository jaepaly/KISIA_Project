"""exp28b — exp28 generate.py 와 같다. data/plan.jsonl 대로 블로그 문체 글을 Gemini 로 쓴다 (README §1).

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python -u experiments/exp28b-context-review-v2/generate.py   (GEMINI_API_KEY 는 환경변수)

출력: data/posts.jsonl — {post_id, group, texts:{body}, planted:[{start,end,text,type,subject}],
      traps:[{start,end,text,kind,wrong}], gen_model, attempts}. 재실행하면 이미 만든 글은 건너뛴다.
표현이 하나라도 정확히 한 번 들어가지 않으면 세 번까지 다시 쓰고, 그래도 안 되면 버린다.
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
    "지정한 표현은 글자 하나 바꾸지 않고 그대로 넣는다(띄어쓰기 · 숫자 · 조사 앞부분까지). "
    "지정하지 않은 개인정보(다른 지명 · 나이 · 직업 · 학교 · 회사 이름 · 가족 관계 · 생일 · 반려동물 · 사람 이름 · 금액)는 새로 넣지 않는다. "
    "학력 · 학교 · 전공 · 정치 성향 · 건강 상태는 쓰지 않는다. 해시태그는 쓰지 않는다. 제목 없이 글 본문만 출력한다."
)


def prompt(r: dict) -> str:
    items = [f"- 「{p['text']}」 — {p['how']}" for p in r["planted"]] + [f"- 「{t['text']}」 — {t['how']}" for t in r["traps"]]
    return (f"주제: {r['topic']}\n말투: {r['voice']}\n길이: 5~10줄\n"
            "아래 표현을 글자 그대로 **각각 딱 한 번씩** 넣어라 (따옴표는 빼고 · 표시한 뜻으로만 쓸 것):\n" + "\n".join(items) +
            "\n표현이 문장 안에서 자연스럽게 읽히도록 앞뒤만 맞춰라.")


def locate(body: str, exprs: list[str]) -> list[int] | None:
    pos = []
    for e in exprs:
        at = body.find(e)
        if at < 0 or body.find(e, at + 1) >= 0:
            return None
        pos.append(at)
    spans = sorted((a, a + len(e)) for a, e in zip(pos, exprs))
    if any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1)):
        return None
    return pos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gemini-3.6-flash,gemini-3.7-flash,gemini-3.8-flash,gemini-flash-latest,gemini-flash-lite-latest")
    ap.add_argument("--interval", type=float, default=7.0)
    a = ap.parse_args()
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    client = llm.LLMClient("gemini", model=models.pop(0), temperature=1.0, max_tokens=900, max_retries=2)

    def call(user: str) -> str:
        nonlocal client
        timeouts = 0
        while True:
            try:
                return client.complete(SYSTEM, user).strip()
            except llm.LLMError as e:
                if "timed out" in str(e) and timeouts < 5:
                    timeouts += 1
                    print(f"  시간 초과 {timeouts}회 — 30초 뒤 다시", flush=True)
                    time.sleep(30)
                    continue
                if ("429" in str(e) or "503" in str(e)) and models:
                    print(f"  {client.model} 한도·과부하 → {models[0]}", flush=True)
                    client = llm.LLMClient("gemini", model=models.pop(0), temperature=1.0, max_tokens=900, max_retries=2)
                    continue
                raise

    plan = [json.loads(l) for l in PLAN.open(encoding="utf-8")]
    done = {json.loads(l)["post_id"] for l in OUT.open(encoding="utf-8")} if OUT.exists() else set()
    kept = dropped = 0
    with OUT.open("a", encoding="utf-8", newline="\n") as f:
        for r in plan:
            if r["post_id"] in done:
                continue
            exprs = [p["text"] for p in r["planted"]] + [t["text"] for t in r["traps"]]
            for attempt in range(3):
                time.sleep(a.interval)
                body = call(prompt(r))
                pos = locate(body, exprs)
                if pos is not None and not client.last_truncated:
                    n = len(r["planted"])
                    planted = [{"start": s, "end": s + len(p["text"]), "text": p["text"], "type": p["type"], "subject": "self"}
                               for s, p in zip(pos[:n], r["planted"])]
                    traps = [{"start": s, "end": s + len(t["text"]), "text": t["text"], "kind": t["kind"], "wrong": t["wrong"]}
                             for s, t in zip(pos[n:], r["traps"])]
                    f.write(json.dumps({"post_id": r["post_id"], "group": r["group"], "texts": {"body": body}, "planted": planted,
                                        "traps": traps, "gen_model": client.version, "attempts": attempt + 1}, ensure_ascii=False) + "\n")
                    f.flush()
                    kept += 1
                    print(f"{r['post_id']} {r['group']} ok", flush=True)
                    break
            else:
                dropped += 1
                print(f"  버림 {r['post_id']} — 표현이 정확히 한 번씩 안 들어감", flush=True)
    print(json.dumps({"kept": kept, "dropped": dropped, "calls": client.calls}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
