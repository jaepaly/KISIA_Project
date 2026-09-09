"""이미 생성된 글의 created_at 필드를 재계산한다 — 재생성 없이.

#182 — sample_time() 의 기준일(2026-03-02)이 하드코딩돼 있어, 30편
인물도 마지막 글이 6월대에 그친다. 본문(§#201 로 늦여름~가을 반영)과
타임스탬프가 어긋난다.

여기서는 generate.py 를 안 건드린다 — week_no 가 프롬프트에 이미
들어가 본문 생성에 영향을 주므로, 그걸 고치면 재생성이 필요해지고
동결 일정과 부딪힌다. 대신 이미 나온 글의 created_at 「메타데이터
필드만」 generated_at 기준으로 역산해 다시 찍는다. texts(본문)는
안 건드린다.

시각(몇 시)은 기존 로직(5개 고정 시각 편중)의 최소 개선만 한다 —
active_windows 있으면 그걸 쓰고, 없으면 typical_active_hours 를
정규식으로 대략 파싱하고, 그마저 없으면 24시간 전체에서 고른다.

    python scripts/patch_created_at.py --dry-run   먼저 몇 명만 눈으로 확인
    python scripts/patch_created_at.py              전체 적용 + 커밋
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


def stable_seed(base_seed: int, pid: str) -> int:
    """파이썬 내장 hash()는 프로세스마다 값이 달라진다(해시 무작위화).
    seed가 같아도 재현이 안 되는 걸 막기 위해 md5로 결정론적 시드를 만든다.
    """
    digest = hashlib.md5(pid.encode("utf-8")).hexdigest()
    return base_seed + int(digest[:8], 16) % 1000

KST = timezone(timedelta(hours=9))

_HOUR_HINTS = [
    (re.compile(r"새벽\s*(\d+)"), lambda m: int(m.group(1))),
    (re.compile(r"오전\s*(\d+)"), lambda m: int(m.group(1))),
    (re.compile(r"오후\s*(\d+)"),
     lambda m: int(m.group(1)) + 12 if int(m.group(1)) < 12 else int(m.group(1))),
    (re.compile(r"밤\s*(\d+)"),
     lambda m: int(m.group(1)) + 12 if int(m.group(1)) < 12 else int(m.group(1))),
]
_ZONE_HINTS = [
    (re.compile(r"새벽"), (0, 5)),
    (re.compile(r"아침|오전"), (6, 10)),
    (re.compile(r"점심|정오"), (11, 13)),
    (re.compile(r"오후"), (13, 17)),
    (re.compile(r"저녁|퇴근"), (18, 20)),
    (re.compile(r"밤|야간|자정"), (21, 23)),
]


def parse_active_hour(raw: str, rng: random.Random) -> int:
    for pat, fn in _HOUR_HINTS:
        m = pat.search(raw)
        if m:
            return fn(m)
    for pat, (lo, hi) in _ZONE_HINTS:
        if pat.search(raw):
            return rng.randint(lo, hi)
    return rng.randint(0, 23)


def recompute(posts_path: Path, persona: dict, seed: int, write: bool = True) -> tuple[int, int, str | None, str | None]:
    """한 인물의 posts jsonl에서 created_at만 다시 찍는다.

    write=False 면 파일을 안 건드리고 계산만 한다 (--dry-run 용).
    반환: (수정건수, 전체건수, 첫편_이전값, 첫편_이후값)
    """
    recs = [json.loads(l) for l in posts_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not recs:
        return 0, 0, None, None

    rng = random.Random(seed)
    windows = (persona.get("account") or {}).get("active_windows")
    typical = (persona.get("account") or {}).get("typical_active_hours", "")

    gen_ats = [r.get("generated_at") for r in recs if r.get("generated_at")]
    if gen_ats:
        anchor = max(datetime.fromisoformat(g) for g in gen_ats)
    else:
        anchor = datetime.now(KST)

    total = len(recs)
    avg_gap = rng.randint(2, 6)
    changed = 0
    before_first = recs[0].get("created_at")

    for i, rec in enumerate(recs):
        old = rec.get("created_at")
        days_from_end = (total - 1 - i) * avg_gap
        base = anchor.replace(hour=0, minute=0, second=0, microsecond=0) \
            - timedelta(days=days_from_end)
        if windows:
            w = rng.choice(windows)
            hour = rng.randint(w.get("start_hour", 20), w.get("end_hour", 23))
        else:
            hour = parse_active_hour(typical, rng)
        new_dt = base.replace(hour=hour % 24, minute=rng.randint(0, 59), second=rng.randint(0, 59))
        new_val = new_dt.isoformat()
        if new_val != old:
            rec["created_at"] = new_val
            changed += 1

    after_first = recs[0].get("created_at")

    if write:
        posts_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
            encoding="utf-8",
        )
    return changed, total, before_first, after_first


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts", default="data/corpus/v0/posts")
    ap.add_argument("--personas", default="data/corpus/v0/personas")
    ap.add_argument("--seed", type=int, default=20260909)
    ap.add_argument("--dry-run", action="store_true",
                     help="파일을 안 쓰고 앞 3명만 미리보기로 계산 결과를 보여준다")
    a = ap.parse_args()

    posts_dir = Path(a.posts)
    personas_dir = Path(a.personas)
    write = not a.dry_run

    persona_files = sorted(f for f in personas_dir.glob("*.json") if not f.stem.startswith("_"))
    if a.dry_run:
        persona_files = persona_files[:3]

    total_changed = total_posts = 0

    for pf in persona_files:
        pid = pf.stem
        posts_path = posts_dir / f"{pid}.jsonl"
        if not posts_path.is_file():
            continue
        try:
            persona = json.loads(pf.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            continue

        changed, total, before, after = recompute(
            posts_path, persona, stable_seed(a.seed, pid), write=write
        )
        if a.dry_run:
            print(f"  {pid}: {before} → {after}  ({changed}/{total}건 변경 예정, 파일 미저장)")
        else:
            print(f"  {pid}: {changed}/{total}건 갱신")

        total_changed += changed
        total_posts += total

    print(f"\n합계: {total_changed}/{total_posts}건")
    if a.dry_run:
        print("(--dry-run — 파일을 저장하지 않았다. 실제 적용은 --dry-run 없이 재실행)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
