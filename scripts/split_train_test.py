"""전체 코퍼스를 train/test로 나눈다.

blind(C가 매긴 것) + IAA(A·C 파일럿) 배정 글은 test 전용이다.
교사 출력을 보기 전에 사람이 매긴 골드 표본이라, 학습(train)에
섞이면 모델이 이미 본 적 있는 글로 평가받는 셈이 된다.

    python scripts/split_train_test.py --dry-run   먼저 통계만 확인
    python scripts/split_train_test.py              실제 분리 + 파일 저장

seed는 train 내부를 섞는 데만 쓴다 — test 구성 자체는 배정 파일로
결정되는 거라 무작위성이 없다.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path


def load_assignment(path: Path) -> set[tuple[str, str]]:
    """blind/iaa _assignment.json에서 (persona_id, post) 집합을 읽는다."""
    if not path.is_file():
        raise SystemExit(f"배정 파일이 없다: {path} — 없으면 test 가 비어서 조용히 누수된다")
    d = json.loads(path.read_text(encoding="utf-8-sig"))
    keys = {(g["persona_id"], g["post"]) for g in d.get("글", [])}
    if not keys:
        raise SystemExit(f"배정 파일에 글이 없다: {path}")
    return keys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts", default="data/corpus/v0/posts")
    ap.add_argument("--blind-assignment", default="data/corpus/v0/gold/blind/_assignment.json")
    ap.add_argument("--iaa-assignment", default="data/corpus/v0/gold/iaa/_assignment.json")
    ap.add_argument("--out", default="data/corpus/v0/splits")
    ap.add_argument("--seed", type=int, default=20260910)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    test_keys = load_assignment(Path(a.blind_assignment)) | load_assignment(Path(a.iaa_assignment))
    print(f"test 전용 배정: blind+IAA 합쳐 {len(test_keys)}건")

    posts_dir = Path(a.posts)
    train_recs: list[dict] = []
    test_recs: list[dict] = []
    missing = []

    for f in sorted(posts_dir.glob("*.jsonl")):
        pid = f.stem
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError as e:
                raise SystemExit(f"JSON 오류: {f}: {e}")
            post_id = r.get("post_id")
            if not post_id:
                raise SystemExit(f"post_id 없는 레코드: {f}")
            post = post_id.split("_")[-1]
            key = (pid, post)
            if key in test_keys:
                test_recs.append(r)
                test_keys.discard(key)  # 실제로 찾은 것만 남기고 지운다
            else:
                train_recs.append(r)

    if test_keys:
        missing = sorted(test_keys)
        print(f"🔴 배정됐지만 posts에 없는 글 {len(missing)}건 — 배정과 코퍼스가 어긋났다")
        for k in missing[:10]:
            print("  ", k)
        return 1

    kind_counts = {
        "train": dict(sorted(collections.Counter(r.get("kind", "?") for r in train_recs).items())),
        "test": dict(sorted(collections.Counter(r.get("kind", "?") for r in test_recs).items())),
    }
    print(f"train {len(train_recs)}편 {kind_counts['train']} · test {len(test_recs)}편 {kind_counts['test']}")

    if a.dry_run:
        print("(--dry-run — 파일을 저장하지 않았다)")
        return 0

    rng = random.Random(a.seed)
    rng.shuffle(train_recs)

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    train_path = out_dir / "train.jsonl"
    test_path = out_dir / "test.jsonl"

    train_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in train_recs) + "\n",
        encoding="utf-8",
    )
    test_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in test_recs) + "\n",
        encoding="utf-8",
    )

    # 누수 검사 — test의 post_id가 train에 하나도 없는지
    train_ids = {r["post_id"] for r in train_recs if r.get("post_id")}
    test_ids = {r["post_id"] for r in test_recs if r.get("post_id")}
    leak = train_ids & test_ids
    if leak:
        print(f"🔴 누수 발견: {len(leak)}건이 train·test 둘 다에 있다 — {sorted(leak)[:5]}")
        return 1
    print("누수 검사 통과 — train·test 겹침 없음")

    meta = {
        "seed": a.seed,
        "train_count": len(train_recs),
        "test_count": len(test_recs),
        "kind_counts": kind_counts,
        "test_personas": len({r.get("persona_id") for r in test_recs}),
        "note": "test 는 blind·IAA 배정 = 전부 단서 글(kind=clue). 잡담·ambient 가 없어 과탐·기권 평가엔 별도 표본이 필요하다. test 인물은 전원 train 에도 있다(인물 분리 아님).",
        "blind_assignment": a.blind_assignment,
        "iaa_assignment": a.iaa_assignment,
    }
    (out_dir / "split_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"저장: {train_path}, {test_path}, {out_dir / 'split_meta.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
