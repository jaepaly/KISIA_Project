"""2단 v0 라벨 → SFT 예시 (chat jsonl). 글 부분집합 증강은 gold/stage2/README.md §5.

    python experiments/exp08-stage2-sft/make_sft.py [--k 8] [--seed 20260907] [--dev 12]

- 인물 1명 → 원본 1건 + 부분집합 k건. 부분집합마다 §3-1 을 다시 적용해 타깃이 따라온다
- dev 는 인물 단위로 뗀다 (같은 인물의 부분집합이 train/dev 에 갈리면 누수)
- blind·IAA 배정 인물은 test 전용이라 여기 train 에 넣지 않는다 (README 「test 전용으로 격리」)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from build_stage2_labels import ATTRS, build_input, findings_for  # noqa: E402

PERSONAS = ROOT / "data/corpus/v0/personas"
HERE = Path(__file__).parent

SYSTEM = """공개 게시글 스팬 목록만 보고 글쓴이 7속성(age·sex·location·occupation·family·commute·income)이 얼마나 특정되는지 판정한다.
verdict: specified(확정) · narrowed(범위 좁혀짐) · weak_signal(약한 신호) · abstain(근거 없음 — 추측 금지, 정상 동작).
규칙: evidence 는 근거 스팬의 post_id·span_id 만 (프로필 스팬은 post_id null). subject "other" 는 남의 정보라 근거 불가.
본인 얘기라도 예전 거주지·출신지·방문지·이사 갈 곳·예전 직장은 지금 것이 아니다 — 근거 불가.
cross_post 는 근거가 서로 다른 글 2편 이상일 때만 true. 실제 값(나이·지명)은 쓰지 않는다.
출력은 {"findings": {7속성 전부}, "rewrites": []} JSON 하나."""


def test_only_posts() -> set[str]:
    """blind·IAA 배정 글 — test 전용. 인물이 아니라 글 단위다 (배정이 101명에 걸쳐 있어 인물 단위로 빼면 남는 게 없다)."""
    out: set[str] = set()
    for name in ("blind", "iaa"):
        f = ROOT / "data/corpus/v0/gold" / name / "_assignment.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding="utf-8-sig"))
        for p in d.get("글") or d.get("posts") or []:
            if isinstance(p, dict) and p.get("persona_id") and p.get("post"):
                out.add(f"{p['persona_id']}_{p['post']}")
    return out


def example(inp: dict, findings: dict) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(inp, ensure_ascii=False)},
            {"role": "assistant", "content": json.dumps({"findings": findings, "rewrites": []}, ensure_ascii=False)},
        ]
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20260907)
    ap.add_argument("--dev", type=int, default=12, help="dev 로 뗄 인물 수")
    ap.add_argument("--out", default=str(HERE / "data"))
    a = ap.parse_args()
    rng = random.Random(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    test_posts = test_only_posts()
    files = sorted(PERSONAS.glob("[A-E]*.json"))
    pids = [f.stem for f in files]
    rng.shuffle(pids)
    dev_pids = set(pids[: a.dev])

    stats = {"train": 0, "dev": 0, "test_only_posts": len(test_posts), "dropped_posts": 0, "k": a.k, "seed": a.seed}
    with (out / "train.jsonl").open("w", encoding="utf-8") as ftr, (out / "dev.jsonl").open("w", encoding="utf-8") as fdv:
        for f in files:
            pid = f.stem
            p = json.loads(f.read_text(encoding="utf-8-sig"))
            inp, by_span = build_input(pid, p.get("clue_plan", []))
            # test 전용 글은 입력에서 뺀다 — 타깃도 남은 글 기준으로 다시 유도
            kept = [x for x in inp["posts"] if x["post_id"] not in test_posts]
            stats["dropped_posts"] += len(inp["posts"]) - len(kept)
            inp = {**inp, "posts": kept}
            post_ids = [x["post_id"] for x in kept]
            if not post_ids and not inp["profile"]:
                continue
            sink = fdv if pid in dev_pids else ftr
            key = "dev" if pid in dev_pids else "train"
            # 원본 (test 글 제외 상태)
            sink.write(json.dumps(example(inp, findings_for(by_span, set(post_ids))), ensure_ascii=False) + "\n")
            stats[key] += 1
            # 부분집합 — 크기 1 ~ 전체-1. 글이 1편뿐이면 증강 없음
            if len(post_ids) < 2:
                continue
            seen = set()
            for _ in range(a.k):
                size = rng.randint(1, len(post_ids) - 1)
                sub = tuple(sorted(rng.sample(post_ids, size)))
                if sub in seen:
                    continue
                seen.add(sub)
                sub_inp = {**inp, "posts": [x for x in inp["posts"] if x["post_id"] in sub]}
                sink.write(json.dumps(example(sub_inp, findings_for(by_span, set(sub))), ensure_ascii=False) + "\n")
                stats[key] += 1
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"train {stats['train']} · dev {stats['dev']} · test 전용 글 {stats['dropped_posts']}편 제외 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
