"""exp21 (B) — 바꿔 쓰기 교사 데이터. Codex CLI(GPT)가 합성 골드 글의 단서마다 「더 일반적인 말」을 낸다.

    python experiments/exp21-local-rewrite/make_teacher.py --n-posts 400 --cache <캐시 폴더>   # Codex 호출 (이어 하기 가능)
    python experiments/exp21-local-rewrite/make_teacher.py --build --cache <캐시 폴더>          # 정제 → data/train.jsonl · dev.jsonl

- 글: 합성 골드(corpus v0)에서 **test 글 · 평가 인물(eval_post_ids.json 의 글을 가진 인물 전체)** 을 뺀다
- 교사: GPT (Codex CLI). Claude 계열은 쓰지 않는다 — 교사 라벨(스팬)이 Claude 라 순환이 생긴다 (c5_corpus.llm.BLOCKED_GENERATION 과 같은 이유)
- 입력 형식은 실행(rewrite_llm.build_messages)과 같다 — 글 + 바꿀 말 목록. 정제는 실행과 같은 거름(check)
  + 1단 재탐지(바꿔도 같은 자리 · 같은 유형 단서가 잡히면 null 로 고쳐 가르친다)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("KISIA_DATA", ROOT / "data"))
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(HERE)]

from kopl.c4_stage2.rewrite import suggest  # noqa: E402
from rewrite_llm import FEW_SHOT_ASSISTANT, FEW_SHOT_USER, SYSTEM, TYPE_KO, build_messages, check, make_items  # noqa: E402

BATCH = 6
MAX_SPANS = 8


def load_posts() -> list[dict]:
    corpus = DATA / "corpus" / "v0"
    test = set(json.loads((corpus / "splits" / "test_post_ids.json").read_text(encoding="utf-8")))
    eval_ids = set(json.loads((HERE / "eval_post_ids.json").read_text(encoding="utf-8")))
    posts = []
    for f in sorted((corpus / "gold").glob("*_spans.jsonl")):
        recs = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        recs = [r for r in recs if "post_id" in r]
        if any(r["post_id"] in eval_ids for r in recs):
            continue  # 평가 인물은 통째로 뺀다 — 같은 사람의 말투·단서가 학습에 새지 않게
        for r in recs:
            if r["post_id"] in test:
                continue
            body = r["texts"].get("body") or ""
            spans = [s for s in r["spans"] if s["text_id"] == "body" and s.get("subject") == "self"
                     and not suggest(s, body)]
            if spans and len(body) <= 900:
                posts.append({"post_id": r["post_id"], "persona": f.stem.split("_")[0], "text": body,
                              "spans": spans[:MAX_SPANS]})
    return posts


def teacher_prompt(batch: list[dict]) -> str:
    blocks = []
    for n, post in enumerate(batch, 1):
        user = build_messages(post["text"], make_items(post["text"], post["spans"], max_spans=MAX_SPANS))[-1]["content"]
        blocks.append(f"### 글{n}\n{user}")
    return (f"{SYSTEM}\n\n예시 입력:\n{FEW_SHOT_USER}\n예시 출력:\n{FEW_SHOT_ASSISTANT}\n\n"
            "파일을 읽거나 명령을 실행하지 말고 아래 글들만 보고 답하라. 글마다 JSON 한 줄씩, 맨 앞에 글 번호를 넣는다:\n"
            '{"글": 1, "1": "바꾼 말", "2": null, ...}\n\n' + "\n\n".join(blocks))


def run_codex(prompt: str) -> str:
    exe = shutil.which("codex.cmd") or shutil.which("codex") or "codex"  # 윈도우는 codex.cmd
    r = subprocess.run([exe, "exec", "--sandbox", "read-only", "-m", "gpt-6.1-sol", "-"], input=prompt,
                       capture_output=True, text=True, encoding="utf-8", timeout=900)
    return r.stdout


def collect(n_posts: int, cache: Path, seed: int) -> None:
    posts = load_posts()
    random.Random(seed).shuffle(posts)
    posts = posts[:n_posts]
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "posts.json").write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
    for b in range(0, len(posts), BATCH):
        out = cache / f"batch_{b // BATCH:03d}.txt"
        if out.exists() and out.stat().st_size > 0:
            continue
        out.write_text(run_codex(teacher_prompt(posts[b:b + BATCH])), encoding="utf-8")
        print(f"batch {b // BATCH} 완료", flush=True)


def build(cache: Path, dev_frac: float = 0.1) -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from apps.analyzer.engines import real

    posts = json.loads((cache / "posts.json").read_text(encoding="utf-8"))
    answers: dict[str, dict] = {}
    for b in range(0, len(posts), BATCH):
        f = cache / f"batch_{b // BATCH:03d}.txt"
        if not f.exists():
            continue
        for m in re.finditer(r"\{[^{}]*\"글\"\s*:\s*(\d+)[^{}]*\}", f.read_text(encoding="utf-8")):
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
            idx = b + int(obj.pop("글")) - 1
            if 0 <= idx < len(posts) and idx < b + BATCH:
                answers[posts[idx]["post_id"]] = obj

    stats = {"posts": 0, "items": 0, "kept": 0, "null_teacher": 0, "null_filtered": 0, "null_residual": 0}
    rows_by_persona: dict[str, list] = {}
    for post in posts:
        ans = answers.get(post["post_id"])
        if ans is None:
            continue
        items = make_items(post["text"], post["spans"], max_spans=MAX_SPANS)
        target: dict[str, str | None] = {}
        for i, it in enumerate(items, 1):
            stats["items"] += 1
            raw = ans.get(str(i))
            sug, reason = check(it, raw)
            if raw is None:
                stats["null_teacher"] += 1
            elif sug is None:
                stats["null_filtered"] += 1
            else:
                new_text = post["text"][:it["start"]] + sug + post["text"][it["end"]:]
                lo, hi = it["start"], it["start"] + len(sug)
                det = real.detect_spans({"post_id": "teach", "body": new_text})["spans"]
                if any(d["type"] == it["type"] and d["start"] < hi and lo < d["end"] for d in det):
                    stats["null_residual"] += 1
                    sug = None
            if sug is not None:
                stats["kept"] += 1
            # 타깃은 핵심어(조사 뺀 말) — 실행 때 josa 가 다시 붙인다. 거른 건 null 로 가르친다
            target[str(i)] = raw.strip().strip("「」\"'") if sug is not None else None
        msgs = build_messages(post["text"], items)
        msgs.append({"role": "assistant", "content": json.dumps(target, ensure_ascii=False)})
        rows_by_persona.setdefault(post["persona"], []).append({"post_id": post["post_id"], "messages": msgs})
        stats["posts"] += 1

    personas = sorted(rows_by_persona)
    random.Random(20261008).shuffle(personas)
    n_dev = max(1, int(len(personas) * dev_frac))
    out = HERE / "data"
    out.mkdir(exist_ok=True)
    for name, group in (("dev", personas[:n_dev]), ("train", personas[n_dev:])):
        rows = [r for p in group for r in rows_by_persona[p]]
        (out / f"{name}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                           encoding="utf-8")
        stats[f"{name}_posts"] = len(rows)
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-posts", type=int, default=400)
    ap.add_argument("--seed", type=int, default=21)
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--build", action="store_true")
    a = ap.parse_args()
    build(a.cache) if a.build else collect(a.n_posts, a.cache, a.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
