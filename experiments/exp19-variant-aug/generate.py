"""exp19: 변이 단서를 넣은 학습용 글 생성 — 코퍼스와 같은 생성기(gpt-5.6-sol · codex CLI).

    PYTHONPATH=src python experiments/exp19-variant-aug/generate.py [--shard k --shards n]

  codex 한 호출이 10~60초라, 여러 개를 나눠 동시에 돌린다 (--shard 0..n-1). 조각은 data/posts.part<k>.jsonl ·
  이미 만든 글(어느 파일이든)은 건너뛴다. 다 끝나면 --merge 로 data/posts.jsonl 하나로 합친다 (spec 순서)

- 생성기를 코퍼스와 같게 둬야 「변이를 넣은 효과」만 따로 볼 수 있다
- 지정 표현이 그대로 안 들어가면 최대 3번 다시 · 평가셋(exp17) 표현이 본문에 나오면 버린다
- 출력 data/posts.jsonl — 재실행하면 이어 쓴다
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from specs import EXP17_SPANS, EXP17_SURFACES, build  # noqa: E402

from kopl.c5_corpus import llm  # noqa: E402

OUT = HERE / "data" / "posts.jsonl"
MODEL = "gpt-5.6-sol"
CLI = f"codex exec --sandbox read-only --skip-git-repo-check -m {MODEL} -"

SYSTEM = (
    "너는 한국어 SNS 일상 글을 쓰는 사람이다. 실제 사람이 쓴 것처럼 자연스럽게 쓴다. "
    "지정한 표현은 글자 하나 바꾸지 않고 그대로 넣는다(띄어쓰기·숫자·조사까지). "
    "지정하지 않은 개인정보(다른 지명·나이·직업·회사 이름·가족 관계·금액)는 새로 넣지 않는다. "
    "학력·학교·전공·정치 성향·건강 상태는 쓰지 않는다. 해시태그·이모지는 쓰지 않는다. 글 본문만 출력한다."
)


def prompt(spec: dict) -> str:
    lines = "\n".join(
        f"- 「{c['text']}」 — " + ("글쓴이 **자신의** 정보로 (비유·남 이야기로 쓰지 말 것)" if c["subject"] == "self"
                                  else "글쓴이가 아닌 **다른 사람의** 정보로")
        for c in spec["clues"])
    if spec["distractor"]:
        lines += f"\n- 「{spec['distractor']}」 — 나이가 아닌 수량·기간·횟수로"
    return (f"주제: {spec['topic']}\n말투: {spec['voice']}\n길이: 2~5문장\n"
            f"아래 표현을 모두 글자 그대로 넣어라 (따옴표는 빼고):\n{lines}\n"
            "표현이 문장 안에서 자연스럽게 읽히도록 앞뒤만 맞춰라.")


def leaks(body: str) -> list[str]:
    hit = [s for s in EXP17_SURFACES if s in body]
    hit += [s for s in EXP17_SPANS if re.search(r"(?<![가-힣0-9])" + re.escape(s), body)]
    return hit


def locate(body: str, spec: dict) -> dict | None:
    planted = []
    for c in spec["clues"]:
        at = body.find(c["text"])
        if at < 0:
            return None
        s = at + c["text"].find(c["span"])
        planted.append({"start": s, "end": s + len(c["span"]), "text": c["span"], "type": c["type"], "level": c["level"],
                        "subject": c["subject"], "variant": c["variant"], "clue": c["text"]})
    distractors = []
    if spec["distractor"]:
        at = body.find(spec["distractor"])
        if at < 0:
            return None
        distractors.append({"start": at, "end": at + len(spec["distractor"]), "text": spec["distractor"]})
    return {"planted": planted, "distractors": distractors}


def _existing() -> dict[str, str]:
    out = {}
    for path in sorted(OUT.parent.glob("posts*.jsonl")):
        for line in path.open(encoding="utf-8"):
            if line.strip():
                out[json.loads(line)["post_id"]] = line if line.endswith("\n") else line + "\n"
    return out


def merge_parts() -> int:
    have = _existing()
    order = [s["post_id"] for s in build()]
    OUT.write_text("".join(have[pid] for pid in order if pid in have), encoding="utf-8")
    for part in OUT.parent.glob("posts.part*.jsonl"):
        part.unlink()
    print(json.dumps({"merged": sum(1 for pid in order if pid in have), "missing": [p for p in order if p not in have][:20]}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--merge", action="store_true")
    a = ap.parse_args()
    if a.merge:
        return merge_parts()
    client = llm.LLMClient("cli", model=MODEL, cli_cmd=CLI, max_retries=2)
    OUT.parent.mkdir(exist_ok=True)
    done = set(_existing())
    target = OUT if a.shards == 1 else OUT.parent / f"posts.part{a.shard}.jsonl"
    kept = dropped = leaked = 0
    with target.open("a", encoding="utf-8") as f:
        for i, spec in enumerate(build()):
            if spec["post_id"] in done or i % a.shards != a.shard:
                continue
            for attempt in range(3):
                body = client.complete(SYSTEM, prompt(spec)).strip()
                found = locate(body, spec)
                if not found:
                    continue
                if leaks(body):
                    leaked += 1
                    continue
                f.write(json.dumps({"post_id": spec["post_id"], "texts": {"body": body}, **found, "voice": spec["voice"],
                                    "topic": spec["topic"], "gen_model": client.version, "attempts": attempt + 1},
                                   ensure_ascii=False) + "\n")
                f.flush()
                kept += 1
                break
            else:
                dropped += 1
                print(f"  버림 {spec['post_id']}", flush=True)
    print(json.dumps({"kept": kept, "dropped": dropped, "leak_retries": leaked, "calls": client.calls}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
