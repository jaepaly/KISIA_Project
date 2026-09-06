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
    """이미 검수 골드셋에 들어간 글. blind 와 겹치면 안 된다.

    label-schema §8-3 형식(post_id 를 최상위에 갖는 글 레코드)을 읽는다.
    spans 가 비어있어도(단서 없다고 판정된 글) "이미 검토됐다"는 사실
    자체는 제외 대상이다 — 안 그러면 검토 완료된 글이 다시 배정된다.

    프로필 레코드(post_id 없음, persona_id + profile_bio)는 글이 아니라
    건너뛴다.
    """
    out: set[tuple[str, str]] = set()
    for f in glob.glob(str(Path(gold_dir) / "*_spans.jsonl")):
        pid = Path(f).stem.replace("_spans", "")
        for line in Path(f).read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            post_id = r.get("post_id", "")
            if not post_id:
                continue  # 프로필 레코드(post_id 없음)는 건너뛴다
            post = post_id.split("_")[-1]
            out.add((pid, post))
    return out


def load_blind(assignment: str) -> set[tuple[str, str]]:
    """이미 뽑아둔 blind 목록. 검수 배정이 이걸 피해야 한다.

    시간 순서가 blind(화~수) → 검수(수~금) 라서, 월요일에 gold/ 는 비어 있다.
    정작 필요한 것은 반대 방향이다 — 이 함수는 검수 배정 쪽에서 쓴다.
    """
    f = Path(assignment)
    if not f.is_file():
        return set()
    d = json.loads(f.read_text(encoding="utf-8-sig"))
    return {(x["persona_id"], x["post"]) for x in d.get("글", [])}


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
        if cur is None:
            by_post[key] = {**d, "n_clues": 0}
        elif rank.get(d["level"], 9) > rank.get(cur["level"], 9):
            # 더 어려운 등급이 나오면 대표를 바꾸되 누적은 살린다.
            # dict 를 통째로 갈아치우면 n_clues 가 1 부터 다시 세어진다
            by_post[key] = {**d, "n_clues": cur["n_clues"]}
        by_post[key]["n_clues"] += 1

    posts = list(by_post.values())
    if not posts:
        return [], {}

    # ── 5. 층 목표는 「접기 전 단서 분포」로 잡는다 ────────────────────
    # A-data.md §5 가 층화 키를 clue_plan[].level 분포로 지정했다.
    # 혼합 등급 글을 어려운 쪽으로 접으면 층 비율이 계약 키와 어긋난다
    # (implicit 이 3.5%p 깎이고 explicit 이 붙었다).
    # 목표는 단서 분포로 잡고, 뽑을 때만 대표 등급을 쓴다.
    clue_ratio = collections.Counter(
        d["level"] for d in designs
        if (d["persona"], d["post"]) not in excluded)
    clue_total = sum(clue_ratio.values())

    # ── 4. --target 은 스팬 수다. 글 수로 환산한다 ────────────────────
    # §5: "200스팬이 나올 만큼의 글 수로 환산해 뽑는다"
    per_post = sum(p["n_clues"] for p in posts) / len(posts)
    n_posts = round(target / per_post) if per_post else target

    picked, plan = [], {}
    for lv in LEVELS:
        pool = [p for p in posts if p["level"] == lv]
        want = round(n_posts * clue_ratio[lv] / clue_total) if clue_total else 0
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
        plan[lv] = {
            "단서_비율": round(clue_ratio[lv] / clue_total, 4) if clue_total else 0,
            "글_모집단": len(pool), "목표": want, "뽑힘": len(take),
            "예상_스팬": sum(p["n_clues"] for p in take),
        }
    meta = {"글당_평균_단서": round(per_post, 3), "환산_글수": n_posts}
    return picked, {"층": plan, "환산": meta}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--personas", default=DEF_PERSONAS)
    ap.add_argument("--posts", default=DEF_POSTS)
    ap.add_argument("--gold", default="data/corpus/v0/gold",
                    help="검수 골드셋. 여기 든 글은 blind 에서 제외한다")
    ap.add_argument("--assignment", default="",
                help="이미 배정된 blind 목록. 검수/IAA 배정이 이걸 피한다 (비우면 안 봄)")
    ap.add_argument("--out", default=DEF_OUT)
    ap.add_argument("--audit", default=DEF_AUDIT)
    ap.add_argument("--target", type=int, default=DEF_TARGET)
    ap.add_argument("--seed", type=int, default=DEF_SEED)
    ap.add_argument("--verify", action="store_true",
                    help="생성된 글에 실제로 있는지 대조만 한다. 파일을 쓰지 않는다")
    a = ap.parse_args()

    import subprocess
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001
        head = None

    designs = load_designs(a.personas)
    if not designs:
        print(f"인물 JSON 을 못 찾았다: {a.personas}")
        return 1
    excluded = load_excluded(a.gold)
    if a.assignment:
        excluded |= load_blind(a.assignment)
        
    picked, plan = stratified(designs, a.target, a.seed, excluded)
    if not picked:
        print("뽑을 글이 없다")
        return 1

    print(f"인물 {len({d['persona'] for d in designs})}명 · 설계 단서 {len(designs)}건")
    if excluded:
        print(f"검수 골드셋에 이미 든 글 {len(excluded)}편 제외")
    print(f"seed {a.seed} · 목표 {a.target} 스팬\n")

    st, meta = plan["층"], plan["환산"]
    print(f"환산 — 글당 평균 단서 {meta['글당_평균_단서']}건 "
          f"→ {a.target}스팬 ≈ {meta['환산_글수']}편")
    print("\n층화 — 층 목표는 접기 전 clue_plan[].level 분포로 잡는다")
    for lv in LEVELS:
        d = st.get(lv, {})
        print(f"  {lv:12} 단서 {d.get('단서_비율', 0):5.1%}"
              f" · 글 모집단 {d.get('글_모집단', 0):3}편"
              f"  →  {d.get('뽑힘', 0):3}편 (예상 {d.get('예상_스팬', 0):3}스팬)")
    print(f"  {'합계':12} {sum(d['뽑힘'] for d in st.values()):>29}편"
          f" (예상 {sum(d['예상_스팬'] for d in st.values())}스팬)")

    per = collections.Counter(p["persona"] for p in picked)
    print(f"\n인물 {len(per)}명에 분산 · 한 인물 최대 {max(per.values())}편")

    print("  ⚠️ 설계 단서 1건이 스팬 1개가 된다는 보장은 없다. 근사값이다")

    if a.verify:
        # 대조만 한다. C 가 작업 중일 때 목록이 바뀌면 안 된다
        exist = Path(a.out) / "_assignment.json"
        if exist.is_file():
            picked_keys = {(x["persona_id"], x["post"])
                           for x in json.loads(exist.read_text(encoding="utf-8-sig"))["글"]}
            print(f"\n기존 배정 {len(picked_keys)}편을 대조한다 (새로 뽑지 않는다)")
        else:
            picked_keys = {(p["persona"], p["post"]) for p in picked}
        have = set()
        for f in glob.glob(str(Path(a.posts) / "*.jsonl")):
            for line in Path(f).read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    r = json.loads(line)
                    have.add((r.get("persona_id"),
                              str(r.get("post_id", "")).rsplit("_", 1)[-1]))
        miss = sorted(picked_keys - have)
        print(f"생성 확인: {len(picked_keys) - len(miss)}/{len(picked_keys)}편 존재")
        for m in miss[:5]:
            print(f"    ⚠️ {m[0]} {m[1]}")
        if len(miss) > 5:
            print(f"    … 외 {len(miss) - 5}편")
        return 0

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
    # ⚠️ 표본별 level·attr 을 적지 않는다.
    # experiments/ 는 C 가 clone 하는 같은 저장소다. 「보지 마세요」는 물리적 불가능이 아니다.
    # A-data.md §5 가 순서를 바꾼 이유가 「순환이 물리적으로 불가능해진다」이므로
    # 층별 집계만 남긴다 — seed 와 코드와 입력 커밋이 있으면 A 가 언제든 재생성한다.
    (aud / "strata.json").write_text(json.dumps({
        "seed": a.seed, "target_spans": a.target,
        "입력_커밋": head or "(git 정보 없음)",
        "인물수": len({d["persona"] for d in designs}),
        "층화": plan, "인물별_글수": dict(per),
        "제외": len(excluded),
        "주의": "표본별 등급·속성은 일부러 적지 않는다. blind 가 끝나기 전에 "
                "이 파일이 정답지가 되면 안 된다. 재현은 seed + 입력_커밋 + 코드로 한다.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{out / '_assignment.json'}   ← C 가 읽는다 (글 번호만)")
    print(f"{aud / 'strata.json'}   ← A 가 보관 (층화 근거)")

    print("\n커밋 해시를 리포트에 적는다 (A-data.md §5)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
