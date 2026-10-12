"""exp22 생성 — Gemini 로 계정 30명 × 글 24편. 계정 하나를 한 번에 쓰게 하고(호출 수를 줄인다), 검사에 걸린 글만 한 편씩 다시 쓴다.

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python -u experiments/exp22-stage2-judge/generate.py --env .env   (GEMINI_API_KEY 는 환경변수)

- 생성기는 Gemini (코퍼스 GPT · 교사 Claude · 2단 Qwen 과 다른 계열)
- 검사: 글마다 지정 표현이 **정확히 한 번** 있고, 다른 글의 지정 표현이 섞이지 않았다 — 아니면 그 글만 다시(최대 3번)
- 빈 본문 · 잘린 응답(MAX_TOKENS)은 받지 않는다
- 출력: data/accounts.jsonl — {account_id, voice, conditions, spec_sha, posts:[{post_id, texts:{body}, planted:[...], gen_model}]}
  재실행하면 이미 만든 계정은 건너뛴다 (이어 쓰기) — 명세 · 프롬프트 지문(spec_sha)이 다르면 멈춘다. 끝에 계정이 다 없으면 종료코드 1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from specs import build  # noqa: E402

from kopl.c5_corpus import llm  # noqa: E402

OUT = HERE / "data" / "accounts.jsonl"
SYSTEM = (
    "너는 한 사람이 SNS 에 오랫동안 쓴 일상 글을 쓰는 사람이다. 실제 사람이 쓴 것처럼 자연스럽게 쓴다. "
    "지정한 표현은 글자 하나 바꾸지 않고 그대로 넣는다(띄어쓰기·숫자·조사까지). 지정 표현은 그 글에만 넣고 다른 글에는 넣지 않는다. "
    "지정하지 않은 개인정보(다른 지명·나이·직업·학교·회사 이름·가족 관계·금액·성별)는 새로 넣지 않는다. "
    "학력·학교·전공·정치 성향·건강 상태는 쓰지 않는다. 해시태그·이모지는 쓰지 않는다."
)


def line_for(c: dict) -> str:
    who = "글쓴이 **자신의** 정보로 (지금 이야기 · 비유나 남 이야기로 쓰지 말 것)" if c["subject"] == "self" \
        else "글쓴이가 아닌 **다른 사람의** 정보로"
    return f"「{c['text']}」 — {who}"


def account_prompt(acc: dict) -> str:
    rows = []
    for p in acc["posts"]:
        req = " / ".join(line_for(c) for c in p["clues"]) or "지정 표현 없음 — 개인정보 없는 잡담"
        rows.append(f"{p['idx'] + 1}. 주제: {p['topic']} · 넣을 표현: {req}")
    return (f"한 사람이 쓴 SNS 글 {len(acc['posts'])}편을 써라. 말투: {acc['voice']}. 글마다 2~4문장.\n"
            + "\n".join(rows)
            + "\n출력은 JSON 문자열 배열 하나만 — 위 순서대로 글 본문 " + str(len(acc["posts"])) + "개. 다른 말은 쓰지 마라.")


def post_prompt(acc: dict, p: dict) -> str:
    req = "\n".join(f"- {line_for(c)}" for c in p["clues"]) or "- 지정 표현 없음 — 개인정보 없는 잡담"
    return (f"주제: {p['topic']}\n말투: {acc['voice']}\n길이: 2~4문장\n아래 표현을 모두 글자 그대로 넣어라 (따옴표는 빼고):\n{req}\n"
            "글 본문만 출력한다.")


def check(body: str, p: dict, all_texts: set[str]) -> list[dict] | None:
    planted = []
    mine = {c["text"] for c in p["clues"]}
    for c in p["clues"]:
        at = body.find(c["text"])
        if at < 0 or body.find(c["text"], at + 1) >= 0:
            return None
        planted.append({"start": at, "end": at + len(c["text"]), **{k: c[k] for k in ("text", "type", "subject", "attr", "cond")}})
    if any(t in body for t in all_texts - mine):   # 다른 글에 심을 표현이 섞이면 정답 글 수가 달라진다
        return None
    return planted


def spec_sha(acc: dict) -> str:
    """이어 쓰기 때 명세 · 프롬프트가 바뀌었는지 — 계정 명세와 system · 계정 · 다시 쓰기 프롬프트의 지문"""
    prompts = SYSTEM + account_prompt(acc) + "".join(post_prompt(acc, p) for p in acc["posts"])
    return hashlib.sha256((prompts + json.dumps(acc, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:16]


def parse_array(text: str) -> list[str] | None:
    t = text.strip()
    if t.startswith("```"):   # 코드펜스
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    try:
        arr = json.loads(t)
    except json.JSONDecodeError:
        try:
            arr = json.loads(t[t.index("["): t.rindex("]") + 1])
        except (ValueError, json.JSONDecodeError):
            return None
    return arr if isinstance(arr, list) and all(isinstance(x, str) and x.strip() for x in arr) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--models", default="gemini-3.6-flash,gemini-3.7-flash,gemini-3.8-flash,gemini-flash-latest,gemini-flash-lite-latest")
    ap.add_argument("--interval", type=float, default=7.0)
    a = ap.parse_args()
    llm.load_dotenv(a.env)
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    state = {"client": llm.LLMClient("gemini", model=models.pop(0), temperature=1.0, max_tokens=8000, max_retries=2)}

    def call(user: str) -> str:
        while True:
            time.sleep(a.interval)
            try:
                return state["client"].complete(SYSTEM, user).strip()
            except llm.LLMError as e:
                if ("429" in str(e) or "503" in str(e)) and models:
                    print(f"  {state['client'].model} 한도·과부하 → {models[0]}", flush=True)
                    state["client"] = llm.LLMClient("gemini", model=models.pop(0), temperature=1.0, max_tokens=8000, max_retries=2)
                    continue
                raise

    OUT.parent.mkdir(exist_ok=True)
    done = {}
    if OUT.exists():
        for l in OUT.open(encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                done[r["account_id"]] = r["spec_sha"]
    specs = build()
    for acc in specs:
        if acc["account_id"] in done:
            if done[acc["account_id"]] != spec_sha(acc):
                raise SystemExit(f"{acc['account_id']}: 명세 · 프롬프트가 바뀌었다 — 옛 결과와 섞지 않는다 (data/accounts.jsonl 확인)")
            continue
        all_texts = {c["text"] for p in acc["posts"] for c in p["clues"]}
        raw = call(account_prompt(acc))
        bodies = (parse_array(raw) or []) if not state["client"].last_truncated else []
        acc_model = state["client"].version
        if len(bodies) != len(acc["posts"]):
            print(f"  {acc['account_id']} 배열 길이 {len(bodies)} — 글마다 다시", flush=True)
            bodies = [""] * len(acc["posts"])
        posts, redo = [], 0
        for p, body in zip(acc["posts"], bodies):
            planted = check(body, p, all_texts) if body.strip() else None
            model = acc_model
            tries = 0
            while planted is None and tries < 3:
                tries += 1; redo += 1
                body = call(post_prompt(acc, p))
                model = state["client"].version
                ok = body.strip() and not state["client"].last_truncated
                planted = check(body, p, all_texts) if ok else None
            if planted is None:
                print(f"  {acc['account_id']} 글 {p['idx'] + 1} 실패 — 계정을 건너뛴다 (다시 실행하면 이어서)", flush=True)
                break
            posts.append({"post_id": f"{acc['account_id']}_p{p['idx'] + 1:02d}", "topic": p["topic"],
                          "texts": {"body": body}, "planted": planted, "gen_model": model})
        else:
            with OUT.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps({"account_id": acc["account_id"], "voice": acc["voice"], "conditions": acc["conditions"],
                                    "spec_sha": spec_sha(acc), "posts": posts, "redo_posts": redo},
                                   ensure_ascii=False) + "\n")
            print(f"{acc['account_id']} 완료 · 다시 쓴 글 {redo}", flush=True)
    have = {json.loads(l)["account_id"] for l in OUT.open(encoding="utf-8") if l.strip()} if OUT.exists() else set()
    missing = [a["account_id"] for a in specs if a["account_id"] not in have]
    print(json.dumps({"accounts": len(have), "missing": missing}, ensure_ascii=False))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
