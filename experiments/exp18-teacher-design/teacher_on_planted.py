"""exp18: 교사 모델 비교를 「심은 단서」 평가셋(exp17)으로 — 어느 교사의 출력에도 기대지 않은 정답.

검수 골드는 교사(Opus 4.8) 출력을 사람이 고쳐 만든 것이라 다른 교사를 대면 경계·유형이 4.8 쪽으로 기운다.
exp17 평가셋(Gemini 가 쓰고 정답 = 심은 표현)은 그 치우침이 없다.

    PYTHONPATH="src;experiments/exp18-teacher-design" python experiments/exp18-teacher-design/teacher_on_planted.py \\
        --env <KISIA .env> --model claude-opus-5-5 --out results/planted_opus55.jsonl
    python experiments/exp17-planted-eval/score.py results/planted_*.jsonl

탐지본(힌트 없음)과 같은 프롬프트(label_prompts L0.1). 출력은 exp17 score.py 형식. 재실행하면 이어 쓴다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kisia_env  # noqa: E402

from kopl.c5_corpus import label  # noqa: E402
from kopl.c5_corpus.llm import LLMClient  # noqa: E402

PLANTED = HERE.parent / "exp17-planted-eval" / "data" / "posts.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args()
    print(kisia_env.load(a.env))
    out = Path(a.out) if Path(a.out).is_absolute() else HERE / a.out
    out.parent.mkdir(exist_ok=True)
    done = {json.loads(l)["post_id"] for l in out.open(encoding="utf-8")} if out.exists() else set()
    client = LLMClient("anthropic", model=a.model, temperature=0, max_tokens=2048, max_retries=3)
    with out.open("a", encoding="utf-8") as f:
        for line in PLANTED.open(encoding="utf-8"):
            post = json.loads(line)
            if post["post_id"] in done:
                continue
            found, dropped = label.call_with_retry(lambda: label.label_one(client, post["texts"], None), post["post_id"])
            f.write(json.dumps({"post_id": post["post_id"], "spans": found, "teacher": client.version}, ensure_ascii=False) + "\n")
            f.flush()
            time.sleep(a.sleep)
    print(json.dumps({"calls": client.calls, "usage": client.usage}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
