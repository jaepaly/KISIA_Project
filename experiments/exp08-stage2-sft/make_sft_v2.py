"""2단 v2 SFT 예시 — 실제 크기 계정 · 앱과 같은 입력 (W9 D 5번 · README 「v2 준비」).

    PYTHONIOENCODING=utf-8 python experiments/exp08-stage2-sft/make_sft_v2.py [--k 7] [--seed 20261012]

v1 과 다른 점 (v1 은 검수 글만 · 계정당 글 중앙 3편 · 앱은 중앙 27편을 보낸다):
- 스팬 = 교사 라벨 + 검수 골드(`data/corpus/v0/gold/<pid>_spans.jsonl` 전부). test 글(`splits/test_post_ids.json`)은 쓰지 않는다
- 입력 = 앱과 같은 가명화(`pseudonymize_spans`) · 고르기(`select_for_model` · 상한 16/4) · **스팬 없는 글은 뺀다**
- 계정마다 전체 글 1개 + 글 일부만 고른 예시 k 개 (고르는 글 수는 2편~전체 사이 로그 균등) — 짧은 계정부터 긴 계정까지
- 정답 = 고른 스팬으로 다시 계산한 findings (make_sft_v1.findings_from_spans 와 같은 규칙) · rewrites [] · **recommendation 없음**
  (앱은 2단 모델의 findings 만 쓰고 추천은 규칙이 만든다 — infer.analyze)
- system = SYSTEM_V2 (v1 학습 프롬프트 + #296 판정 기준). 앱이 v2 로 바뀔 때 infer 가 같은 문자열을 쓴다
- dev 인물은 v1 과 같은 12명 (같은 seed 20260916 섞기) — v1 · v2 dev 비교가 되게
출력: data/v2_train.jsonl · data/v2_dev.jsonl · data/v2_stats.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(HERE)]
from kopl.c4_stage2.infer import pseudonymize_spans, select_for_model  # noqa: E402
from make_sft_v1 import findings_from_spans, load_test_ids, user_ref  # noqa: E402

GOLD = ROOT / "data/corpus/v0/gold"
POSTS = ROOT / "data/corpus/v0/posts"
MAX_SPANS, MAX_PER_TYPE = 16, 4   # 실제 계정이 모두 2048 토큰 안 (v2_length.py · 최대 1,950)

SYSTEM_V2 = """공개 게시글 스팬 목록만 보고 글쓴이 7속성(age·sex·location·occupation·family·commute·income)이 얼마나 특정되는지 판정한다.
verdict: specified(확정) · narrowed(범위 좁혀짐) · weak_signal(약한 신호) · abstain(근거 없음 — 추측 금지, 정상 동작).
판정 기준(속성마다 그 속성 유형의 본인 스팬만): explicit 이 하나라도 있으면 specified · 아니면 implicit 이 하나라도 있으면 narrowed · 아니면 inferential 만 있는데 서로 다른 글 2편 이상이면 narrowed · inferential 이 글 1편뿐이면 weak_signal · 단서가 없으면 abstain.
규칙: evidence 는 근거 스팬의 post_id·span_id 만 (프로필 스팬은 post_id null). subject "other" 는 남의 정보라 근거 불가.
본인 얘기라도 예전 거주지·출신지·방문지·이사 갈 곳·예전 직장은 지금 것이 아니다 — 근거 불가.
cross_post 는 근거가 서로 다른 글 2편 이상일 때만 true. 실제 값(나이·지명)은 쓰지 않는다.
출력은 {"findings": {7속성 전부}, "rewrites": []} JSON 하나."""


def dev_personas(pids: list[str], n: int = 12, seed: int = 20260916) -> set[str]:
    """make_sft_v1 과 같은 섞기 — 같은 12명이 dev 가 된다."""
    order = sorted(pids)
    random.Random(seed).shuffle(order)
    return set(order[:n])


def load_account(pid: str, test_ids: set[str]) -> list[dict]:
    gold: dict[str, list[dict]] = {}
    for line in (GOLD / f"{pid}_spans.jsonl").read_text(encoding="utf-8-sig").splitlines():
        r = json.loads(line) if line.strip() else {}
        if "post_id" in r:
            gold[r["post_id"]] = r.get("spans") or []
    out = []
    for line in (POSTS / f"{pid}.jsonl").read_text(encoding="utf-8-sig").splitlines():
        p = json.loads(line) if line.strip() else {}
        if "post_id" in p and p["post_id"] not in test_ids:
            out.append({"post_id": p["post_id"],
                        "spans": pseudonymize_spans({"texts": p.get("texts") or {}, "spans": gold.get(p["post_id"], [])})})
    return out


def example(pid: str, entries: list[dict]) -> dict:
    sel = select_for_model(entries, max_spans=MAX_SPANS, max_per_type=MAX_PER_TYPE)
    sel = [e for e in sel if e["spans"]]
    findings = findings_from_spans([(e["post_id"], e["spans"]) for e in sel])
    inp = {"user_ref": user_ref(pid), "profile": None, "posts": sel}
    return {"messages": [
        {"role": "system", "content": SYSTEM_V2},
        {"role": "user", "content": json.dumps(inp, ensure_ascii=False)},
        {"role": "assistant", "content": json.dumps({"findings": findings, "rewrites": []}, ensure_ascii=False)}],
        "meta": {"persona_id": pid, "n_posts": len(entries), "n_spans": sum(len(e["spans"]) for e in sel)}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=7, help="계정마다 글 일부만 고른 예시 수 (전체 글 예시 1개는 따로)")
    ap.add_argument("--seed", type=int, default=20261012)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    test_ids = load_test_ids()
    pids = sorted(p.stem.replace("_spans", "") for p in GOLD.glob("[A-E]*_spans.jsonl"))
    dev = dev_personas(pids)
    stats = {"seed": a.seed, "k": a.k, "max_spans": MAX_SPANS, "max_per_type": MAX_PER_TYPE, "dev_personas": sorted(dev),
             "train": 0, "dev": 0, "personas": 0, "skipped_no_posts": []}
    with (HERE / "data/v2_train.jsonl").open("w", encoding="utf-8", newline="\n") as ftr, \
         (HERE / "data/v2_dev.jsonl").open("w", encoding="utf-8", newline="\n") as fdv:
        for pid in pids:
            entries = load_account(pid, test_ids)
            if len(entries) < 2:
                stats["skipped_no_posts"].append(pid)
                continue
            stats["personas"] += 1
            sink, key = (fdv, "dev") if pid in dev else (ftr, "train")
            n = len(entries)
            samples = [entries]
            for _ in range(a.k):
                size = round(math.exp(rng.uniform(math.log(2), math.log(n))))
                keep = set(rng.sample(range(n), size))
                samples.append([e for i, e in enumerate(entries) if i in keep])   # 글 순서는 원래대로
            for s in samples:
                ex = example(pid, s)
                if not ex["messages"][1]["content"].count('"span_id"'):
                    continue   # 스팬이 하나도 없는 입력은 학습에 쓰지 않는다
                sink.write(json.dumps(ex, ensure_ascii=False) + "\n")
                stats[key] += 1
    (HERE / "data/v2_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "dev_personas"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
