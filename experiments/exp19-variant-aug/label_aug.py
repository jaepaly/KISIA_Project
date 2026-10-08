"""exp19: 변이 글에 교사 라벨을 붙여 학습 전용 골드로 저장한다.

    PYTHONPATH="src;experiments/exp19-variant-aug" python experiments/exp19-variant-aug/label_aug.py --env <KISIA .env>

- 교사: 코퍼스 교사와 같은 Claude Opus 4.8 · 탐지본 프롬프트(label_prompts L0.1) — exp18 에서 이 교사가 코퍼스 밖 글의
  본인 단서를 92% 찾는 것을 확인했다
- 교사가 놓친 **심은 단서는 정답 위치로 보충**한다 (심은 단서는 정의상 정답이다) · 숫자 함정(「스무 해 넘게」)을 AGE 로
  잡은 교사 라벨은 지운다
- 출력: data/corpus/aug/v1/AUG1_spans.jsonl (골드와 같은 형식 · reviewed=false) → prepare_bio.py --extra-gold-dir 로 학습
  재실행하면 이어 쓴다
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import kisia_env  # noqa: E402

from kopl.c5_corpus import label  # noqa: E402
from kopl.c5_corpus.llm import LLMClient  # noqa: E402

POSTS = HERE / "data" / "posts.jsonl"
OUT_DIR = ROOT / "data" / "corpus" / "aug" / "v1"
TEACHER = "claude-opus-4-8"


def _overlap(a: dict, b: dict) -> bool:
    return a.get("text_id", "body") == b.get("text_id", "body") and min(a["end"], b["end"]) > max(a["start"], b["start"])


def merge(post: dict, teacher: list[dict]) -> tuple[list[dict], dict]:
    """교사 라벨 + 놓친 심은 단서 · 숫자 함정 AGE 제거 · 겹침 없음."""
    stats = {"teacher": len(teacher), "planted_added": 0, "distractor_removed": 0}
    teacher, _ = label.dedupe([dict(s, text_id=s.get("text_id", "body")) for s in teacher])  # 코퍼스 관례 — 긴 스팬 우선 (§6)
    spans = []
    for s in teacher:
        if s["type"] == "AGE" and any(_overlap(s, d) for d in post["distractors"]):
            stats["distractor_removed"] += 1
            continue
        spans.append(s)
    for c in post["planted"]:
        if any(_overlap(dict(c, text_id="body"), s) for s in spans):
            continue  # 교사가 잡았다 (경계·유형은 교사 것을 쓴다 — 코퍼스 라벨 관례와 같게)
        spans.append({"text_id": "body", "start": c["start"], "end": c["end"], "text": c["text"], "type": c["type"],
                      "level": c["level"], "subject": c["subject"]})
        stats["planted_added"] += 1
    spans.sort(key=lambda s: (s["start"], s["end"]))
    kept, last_end = [], -1
    for s in spans:  # 겹침 정리 — 앞의 것 우선
        if s["start"] < last_end:
            continue
        kept.append(s)
        last_end = s["end"]
    body = post["texts"]["body"]
    out = []
    for i, s in enumerate(kept, 1):
        assert body[s["start"]:s["end"]] == s["text"], (post["post_id"], s)
        out.append({"span_id": f"{post['post_id']}_s{i:02d}", "text_id": "body", "start": s["start"], "end": s["end"],
                    "text": s["text"], "type": s["type"], "level": s["level"], "subject": s["subject"]})
    return out, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args()
    print(kisia_env.load(a.env))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "AUG1_spans.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(l).get("post_id") for l in out.open(encoding="utf-8") if l.strip()}
    else:
        out.write_text(json.dumps({"schema_version": "1.0", "corpus_version": "aug-v1", "teacher_model": f"anthropic:{TEACHER}",
                                   "label_prompt_version": "L0.1", "mode": "detect+planted",
                                   "source": "experiments/exp19-variant-aug (#310)"}, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    client = LLMClient("anthropic", model=TEACHER, temperature=0, max_tokens=2048, max_retries=3)
    totals = {"posts": 0, "teacher": 0, "planted_added": 0, "distractor_removed": 0}
    with out.open("a", encoding="utf-8") as f:
        for line in POSTS.open(encoding="utf-8"):
            post = json.loads(line)
            if post["post_id"] in done:
                continue
            found, _ = label.call_with_retry(lambda: label.label_one(client, post["texts"], None), post["post_id"])
            spans, st = merge(post, found)
            f.write(json.dumps({"post_id": post["post_id"], "persona_id": "AUG1", "texts": post["texts"], "spans": spans,
                                "reviewed": False, "gen_model": post["gen_model"]}, ensure_ascii=False) + "\n")
            f.flush()
            totals["posts"] += 1
            for k in ("teacher", "planted_added", "distractor_removed"):
                totals[k] += st[k]
            time.sleep(a.sleep)
    print(json.dumps({**totals, "calls": client.calls}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
