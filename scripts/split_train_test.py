"""전체 코퍼스를 train/test로 나눈다.

blind(C가 매긴 것) + IAA(A·C 파일럿) 배정 글은 test 전용이다.
교사 출력을 보기 전에 사람이 매긴 골드 표본이라, 학습(train)에
섞이면 모델이 이미 본 적 있는 글로 평가받는 셈이 된다.

#235 — blind·IAA는 전부 단서 글(kind=clue)이라, 1단 과탐(precision·
특이도)과 2단 기권(abstain)을 잴 잡담·ambient 표본이 test에 없었다.
선택지 (가)로 간다 — 검수 정본(gold/ 최상위, reviewed:true)의
negative_control 글 중 일부를 seed로 뽑아 test에 추가한다. blind는
아니지만(교사 라벨을 본 뒤 검수), 잡담·ambient는 "단서가 없다"는
확인이 핵심이라 등급·유형처럼 판단이 갈리는 영역이 아니다 — 검수
정본의 신뢰도로 충분하다.

    python scripts/split_train_test.py --dry-run   먼저 통계만 확인
    python scripts/split_train_test.py              실제 분리 + 파일 저장

seed는 train 내부를 섞는 데, 그리고 잡담 표본을 뽑는 데 쓴다.
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


def load_noise_candidates(gold_dir: Path) -> set[tuple[str, str]]:
    """검수 정본(최상위 gold/*_spans.jsonl)에서 reviewed:true + negative_control
    글의 (persona_id, post) 후보를 모은다. blind/iaa/detect 하위 폴더는
    glob("*_spans.jsonl")이 최상위만 보므로 자동으로 제외된다.
    """
    candidates: set[tuple[str, str]] = set()
    for f in gold_dir.glob("*_spans.jsonl"):
        pid = f.stem.replace("_spans", "")
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            post_id = r.get("post_id")
            if not post_id:
                continue  # 프로필 레코드
            if r.get("reviewed") and r.get("flags", {}).get("negative_control"):
                post = post_id.split("_")[-1]
                candidates.add((pid, post))
    return candidates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts", default="data/corpus/v0/posts")
    ap.add_argument("--blind-assignment", default="data/corpus/v0/gold/blind/_assignment.json")
    ap.add_argument("--iaa-assignment", default="data/corpus/v0/gold/iaa/_assignment.json")
    ap.add_argument("--gold-dir", default="data/corpus/v0/gold")
    ap.add_argument("--out", default="data/corpus/v0/splits")
    ap.add_argument("--seed", type=int, default=20260910)
    ap.add_argument("--noise-sample-size", type=int, default=80,
                     help="검수 정본에서 test로 추가할 잡담(noise) 글 수 (#235 선택지 가)")
    ap.add_argument("--no-noise", action="store_true",
                     help="잡담 표본 추가를 끈다 (W4까지의 옛 동작)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    test_keys = load_assignment(Path(a.blind_assignment)) | load_assignment(Path(a.iaa_assignment))
    print(f"test 전용 배정(blind+IAA): {len(test_keys)}건")

    noise_added = 0
    if not a.no_noise:
        candidates = load_noise_candidates(Path(a.gold_dir)) - test_keys
        rng_noise = random.Random(a.seed)
        sample_size = min(a.noise_sample_size, len(candidates))
        noise_sample = set(rng_noise.sample(sorted(candidates), sample_size))
        test_keys |= noise_sample
        noise_added = len(noise_sample)
        print(f"잡담 표본 추가(#235 가): 후보 {len(candidates)}건 중 {noise_added}건 (seed={a.seed})")

    posts_dir = Path(a.posts)
    train_recs: list[dict] = []
    test_recs: list[dict] = []

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
                test_keys.discard(key)
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
        "noise_sample_added": noise_added,
        "test_personas": len({r.get("persona_id") for r in test_recs}),
        "note": (
            "test = blind·IAA(단서 글) + #235 결정(가)로 추가한 검수 정본 "
            "잡담(noise) 표본. 잡담 표본은 blind가 아니라 검수(교사 라벨을 "
            "본 뒤 사람이 확정)라는 한계가 있음 — 다만 '단서 없음' 확인은 "
            "등급·유형처럼 판단이 갈리는 영역이 아니라 신뢰도 충분하다고 판단. "
            "test 인물은 전원 train에도 있다(인물 분리 아님) — 인물 단위 "
            "부트스트랩으로 보완 필요."
        ),
        "blind_assignment": a.blind_assignment,
        "iaa_assignment": a.iaa_assignment,
        "decision_issue": "#235",
    }
    (out_dir / "split_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"저장: {train_path}, {test_path}, {out_dir / 'split_meta.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
