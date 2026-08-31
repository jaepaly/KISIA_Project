"""blind 200 층화 표본 추출 — C 가 화요일에 쓰는 글 목록을 뽑는다.

`A-data.md` §5:

    표본 200스팬은 골드셋과 겹치지 않는 별도 글에서,
    explicit/implicit/inferential 비율을 유지한 층화 무작위로 뽑는다.
    추출 스크립트와 seed 를 커밋하고 커밋 해시를 리포트에 적는다.

    python scripts/sample_gold.py                     기본값으로 뽑는다
    python scripts/sample_gold.py --target 200        스팬 목표
    python scripts/sample_gold.py --seed 20260901     seed 를 바꾼다
    python scripts/sample_gold.py --verify            글이 실제로 생성됐는지 확인


⚠️ **C 는 정답을 보면 안 된다.**

blind 의 목적은 「교사 라벨을 보기 전에 사람이 매긴 값」이다. 그래서 C 에게 주는
파일에는 **글 번호만** 담고, 등급·속성·단서 내용은 담지 않는다.
층화 근거는 A 가 보관하는 별도 파일에 남긴다 — 재현과 감사를 위해서다.

    data/corpus/v0/gold/blind/_assignment.json   C 가 읽는다. 글 목록뿐
    experiments/blind-sampling/strata.json       A 가 보관한다. 층화 근거


⚠️ **이 스크립트는 생성 전에 돈다.**

월요일에는 글이 아직 없다. 그래서 층화 기준을 실제 스팬이 아니라
**인물 JSON 의 `clue_plan` 설계값**에서 가져온다. 설계 단서 1건이 스팬 1개가
된다는 보장은 없으므로 목표 스팬 수는 근사다 — `--verify` 로 나중에 대조한다.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import random
import sys
from pathlib import Path

LEVELS = ("explicit", "implicit", "inferential")

DEF_PERSONAS = "data/corpus/v0/personas"
DEF_POSTS = "data/corpus/v0/posts"
DEF_OUT = "data/corpus/v0/gold/blind"
DEF_AUDIT = "experiments/blind-sampling"
DEF_SEED = 20260901
DEF_TARGET = 200


def load_designs(d: str) -> list[dict]:
    """인물 JSON 에서 (인물, 글, 등급) 을 뽑는다.

    profile_bio 단서는 글에 속하지 않으므로 (post=None) 제외한다 —
    C 가 글 단위로 읽기 때문이다.
    """
    out = []
    for f in sorted(glob.glob(str(Path(d) / "*.json"))):
        try:
            p = json.loads(Path(f).read_text(encoding="utf-8-sig"))
        except Exception as e:  # noqa: BLE001
            print(f"(건너뜀: {f} — {e})", file=sys.stderr)
            continue
        pid = p.get("id") or p.get("persona_id") or Path(f).stem
        for c in p.get("clue_plan") or []:
            if not c.get("post"):
                continue
            out.append({"persona": pid, "post": c["post"],
                        "level": c.get("level"), "attr": c.get("attr"),
                        "text_id": c.get("text_id", "body")})
    return out


def load_excluded(gold_dir: str) -> set[tuple[str, str]]:
    """이미 검수 골드셋에 들어간 글. blind 와 겹치면 안 된다."""
    out: set[tuple[str, str]] = set()
    for f in glob.glob(str(Path(gold_dir) / "*_spans.jsonl")):
        for line in Path(f).read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            pid, post = r.get("persona_id"), r.get("post_id")
            if pid and post:
                out.add((pid, post.rsplit("_", 1)[-1]))
    return out


def stratified(designs: list[dict], target: int, seed: int,
               excluded: set) -> tuple[list, dict]:
    """등급 비율을 유지한 층화 무작위 추출. 단위는 글이다.

    한 글이 단서를 여럿 가질 수 있어 글 단위로 접은 뒤 뽑는다.
    인물 한 명에 몰리지 않도록 인물을 돌아가며 채운다.
    """
    rng = random.Random(seed)

    # 글 단위로 접는다. 한 글에 등급이 여럿이면 가장 낮은 쪽(어려운 쪽)을 대표로 둔다
    rank = {l: i for i, l in enumerate(LEVELS)}
    by_post: dict[tuple[str, str], dict] = {}
    for d in designs:
        key = (d["persona"], d["post"])
        if key in excluded:
            continue
        cur = by_post.get(key)
        if cur is None or rank.get(d["level"], 9) > rank.get(cur["level"], 9):
            by_post[key] = d
        by_post[key].setdefault("n_clues", 0)
        by_post[key]["n_clues"] += 1

    posts = list(by_post.values())
    ratio = collections.Counter(p["level"] for p in posts)
    total = sum(ratio.values())
    if not total:
        return [], {}

    picked, plan = [], {}
    for lv in LEVELS:
        pool = [p for p in posts if p["level"] == lv]
        want = round(target * ratio[lv] / total)
        # 인물을 돌아가며 채운다 — 한 명에게 몰리면 blind 가 그 인물 문체만 본다
        rng.shuffle(pool)
        buckets: dict[str, list] = collections.defaultdict(list)
        for p in pool:
            buckets[p["persona"]].append(p)
        order = sorted(buckets)
        rng.shuffle(order)
        take, i = [], 0
        while len(take) < min(want, len(pool)):
            b = buckets[order[i % len(order)]]
            if b:
                take.append(b.pop())
            i += 1
            if i > len(pool) * 3:
                break
        picked += take
        plan[lv] = {"모집단": ratio[lv], "비율": round(ratio[lv] / total, 4),
                    "목표": want, "뽑힘": len(take)}
    return picked, plan


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--personas", default=DEF_PERSONAS)
    ap.add_argument("--posts", default=DEF_POSTS)
    ap.add_argument("--gold", default="data/corpus/v0/gold",
                    help="검수 골드셋. 여기 든 글은 blind 에서 제외한다")
    ap.add_argument("--out", default=DEF_OUT)
    ap.add_argument("--audit", default=DEF_AUDIT)
    ap.add_argument("--target", type=int, default=DEF_TARGET)
    ap.add_argument("--seed", type=int, default=DEF_SEED)
    ap.add_argument("--verify", action="store_true",
                    help="생성된 글에 실제로 있는지 대조한다 (생성 후)")
    a = ap.parse_args()

    designs = load_designs(a.personas)
    if not designs:
        print(f"인물 JSON 을 못 찾았다: {a.personas}")
        return 1
    excluded = load_excluded(a.gold)

    picked, plan = stratified(designs, a.target, a.seed, excluded)
    if not picked:
        print("뽑을 글이 없다")
        return 1

    print(f"인물 {len({d['persona'] for d in designs})}명 · 설계 단서 {len(designs)}건")
    if excluded:
        print(f"검수 골드셋에 이미 든 글 {len(excluded)}편 제외")
    print(f"seed {a.seed} · 목표 {a.target} 스팬\n")

    print("층화 — 설계 등급 비율을 유지한다")
    for lv in LEVELS:
        s = plan.get(lv, {})
        print(f"  {lv:12} 모집단 {s.get('모집단', 0):4}편 ({s.get('비율', 0):5.1%})"
              f"  →  {s.get('뽑힘', 0):3}편")
    print(f"  {'합계':12} {sum(s['뽑힘'] for s in plan.values()):>21}편")

    per = collections.Counter(p["persona"] for p in picked)
    print(f"\n인물 {len(per)}명에 분산 · 한 인물 최대 {max(per.values())}편")

    est = sum(p.get("n_clues", 1) for p in picked)
    print(f"설계 단서 기준 예상 스팬 {est}건 (목표 {a.target})")
    print("  ⚠️ 설계 단서 1건이 스팬 1개가 된다는 보장은 없다. 근사값이다")

    # ── C 가 읽는 파일 — 글 번호만. 등급·속성은 담지 않는다 ──────────
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    assignment = {
        "생성": f"scripts/sample_gold.py --seed {a.seed} --target {a.target}",
        "설명": "blind 200 대상 글. 교사 라벨을 보기 전에 매긴다. "
                "등급·속성은 일부러 담지 않았다 — 정답을 보면 blind 가 아니다.",
        "출력": "data/corpus/v0/gold/blind/<persona_id>_spans.jsonl",
        "글": sorted([{"persona_id": p["persona"], "post": p["post"]} for p in picked],
                    key=lambda x: (x["persona_id"], x["post"])),
    }
    (out / "_assignment.json").write_text(
        json.dumps(assignment, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── A 가 보관하는 층화 근거 — C 디렉터리 밖에 둔다 ────────────────
    aud = Path(a.audit)
    aud.mkdir(parents=True, exist_ok=True)
    (aud / "strata.json").write_text(json.dumps({
        "seed": a.seed, "target": a.target,
        "층화": plan, "인물별": dict(per),
        "제외": len(excluded),
        "표본": sorted([{**{k: p[k] for k in ("persona", "post", "level", "attr", "text_id")}}
                       for p in picked], key=lambda x: (x["persona"], x["post"])),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{out / '_assignment.json'}   ← C 가 읽는다 (글 번호만)")
    print(f"{aud / 'strata.json'}   ← A 가 보관 (층화 근거)")

    if a.verify:
        have = set()
        for f in glob.glob(str(Path(a.posts) / "*.jsonl")):
            for line in Path(f).read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    r = json.loads(line)
                    have.add((r.get("persona_id"), r.get("post_id", "").rsplit("_", 1)[-1]))
        miss = [p for p in picked if (p["persona"], p["post"]) not in have]
        print(f"\n생성 확인: {len(picked) - len(miss)}/{len(picked)}편 존재")
        if miss:
            print(f"  ⚠️ 없는 글 {len(miss)}편 — 생성이 덜 됐거나 잘려서 저장되지 않았다")
            for m in miss[:5]:
                print(f"    {m['persona']} {m['post']}")

    print("\n커밋 해시를 리포트에 적는다 (A-data.md §5)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
