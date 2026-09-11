"""코퍼스 → 가상 SNS DB 시딩 스크립트.

설계는 docs/roles/howto/e-sns.md §5 가 정본이다.

    python scripts/seed_sns.py \\
      --corpus data/corpus/v0/posts/ \\
      --personas data/corpus/v0/personas/ \\
      --db data/interim/sns.db \\
      --authors E06,E07

지켜야 할 3가지 (howto §5):
  ① 멱등성 — INSERT OR IGNORE. 두 번 돌려도 글이 두 배가 되지 않는다.
  ② 작성시각 — 코퍼스의 created_at 을 그대로 쓴다(이미 있으면). 없으면
     인물의 typical_active_hours 에 맞춰 흩뿌린다.
  ③ --reset — DROP 후 schema.sql 로 재생성하고 다시 시딩한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "apps" / "sns"))

import db as sns_db  # noqa: E402

PHOTO_CAPTION_RE = re.compile(r"^photo_caption:(\d+)$")

# 코퍼스에 시각이 없을 때 쓸 기본 활동 시간대 (본문에 없을 경우의 폴백)
DEFAULT_HOURS = list(range(8, 23))


def user_ref_for(persona_id: str) -> str:
    """persona_id 로부터 결정적인 u_[0-9a-f]{8,} 핸들을 만든다.

    같은 persona_id 는 언제 돌려도 같은 user_ref 가 나와야 authors 의
    UNIQUE(user_ref) 와 INSERT OR IGNORE 가 멱등하게 맞물린다.
    """
    h = hashlib.sha256(persona_id.encode("utf-8")).hexdigest()[:12]
    return f"u_{h}"


def active_hours_from_persona(persona: dict) -> list[int]:
    """persona.account.typical_active_hours 문장에서 시간대(0-23)를 뽑는다.

    자유 서술 텍스트라 정확한 파싱은 불가능하다 — 문장에 등장하는
    「새벽/밤/오전/오후/저녁/낮」키워드로 대략의 시간대만 좁힌다.
    아무 것도 못 찾으면 DEFAULT_HOURS 로 폴백한다.
    """
    text = persona.get("account", {}).get("typical_active_hours", "") or ""
    hours: set[int] = set()

    for m in re.finditer(r"(\d{1,2})\s*시", text):
        h = int(m.group(1))
        if "밤" in text[max(0, m.start() - 4):m.start()] or "새벽" in text:
            pass  # 아래 키워드 매칭에서 통합 처리
        if 0 <= h <= 23:
            hours.add(h)

    keyword_hours = {
        "새벽": [0, 1, 2, 3, 4, 5],
        "아침": [6, 7, 8],
        "오전": [9, 10, 11],
        "점심": [12, 13],
        "오후": [14, 15, 16, 17],
        "저녁": [18, 19, 20],
        "밤": [21, 22, 23],
        "야근": [21, 22, 23],
        "주말": [10, 11, 20, 21],
    }
    for kw, kw_hours in keyword_hours.items():
        if kw in text:
            hours.update(kw_hours)

    return sorted(hours) if hours else DEFAULT_HOURS


def load_persona(personas_dir: Path, persona_id: str) -> dict:
    p = personas_dir / f"{persona_id}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def load_profile(posts_dir: Path, persona_id: str) -> dict | None:
    p = posts_dir / f"{persona_id}_profile.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def iter_posts(posts_dir: Path, persona_id: str):
    p = posts_dir / f"{persona_id}.jsonl"
    if not p.exists():
        return
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def scatter_created_at(record: dict, hours: list[int], rng: random.Random) -> str:
    """코퍼스에 created_at 이 있으면 그대로 쓰고, 없으면 흩뿌려 만든다."""
    created_at = record.get("created_at")
    if created_at:
        return created_at
    # 폴백 — 현재 코퍼스에는 항상 created_at 이 있어 이 경로는 정상 동작에서
    # 쓰이지 않지만, howto §5 ②가 요구하는 안전망이라 남겨 둔다.
    hour = rng.choice(hours)
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    return f"2026-01-01T{hour:02d}:{minute:02d}:{second:02d}+09:00"


def seed_persona(
    conn: sqlite3.Connection,
    posts_dir: Path,
    personas_dir: Path,
    persona_id: str,
    rng: random.Random,
) -> tuple[int, int]:
    persona = load_persona(personas_dir, persona_id)
    profile = load_profile(posts_dir, persona_id)

    nickname = persona.get("account", {}).get("nickname", persona_id)
    bio = None
    joined = persona.get("account", {}).get("joined")
    joined_at = f"{joined}-01T00:00:00+09:00" if joined else "2020-01-01T00:00:00+09:00"

    if profile:
        bio = profile.get("texts", {}).get("profile_bio")
        nickname = nickname or persona_id

    conn.execute(
        "INSERT OR IGNORE INTO authors(author_id, user_ref, nickname, bio, joined_at)"
        " VALUES(?, ?, ?, ?, ?)",
        (persona_id, user_ref_for(persona_id), nickname, bio, joined_at),
    )

    hours = active_hours_from_persona(persona)

    n_posts = 0
    n_photos = 0
    for record in iter_posts(posts_dir, persona_id):
        texts = record.get("texts", {})
        post_id = record["post_id"]
        created_at = scatter_created_at(record, hours, rng)
        # nickname 은 코퍼스 레코드에도 실려 오지만 authors.nickname 이 정본이다
        nickname_from_post = record.get("nickname")
        if nickname_from_post:
            nickname = nickname_from_post

        cur = conn.execute(
            "INSERT OR IGNORE INTO posts"
            "(post_id, author_id, title, body, created_at, geo_tag, visibility, source)"
            " VALUES (?, ?, ?, ?, ?, ?, 'public', 'seed')",
            (post_id, persona_id, texts.get("title"), texts.get("body"), created_at, None),
        )
        if cur.rowcount:
            n_posts += 1

        captions: dict[int, str] = {}
        for key, value in texts.items():
            m = PHOTO_CAPTION_RE.match(key)
            if m:
                captions[int(m.group(1))] = value
        for idx in sorted(captions):
            cur = conn.execute(
                "INSERT OR IGNORE INTO photos(post_id, idx, caption) VALUES (?, ?, ?)",
                (post_id, idx, captions[idx]),
            )
            if cur.rowcount:
                n_photos += 1

    # authors.nickname 을 마지막으로 본 코퍼스 nickname 으로 맞춰둔다
    # (INSERT OR IGNORE 는 이미 있는 행을 갱신하지 않으므로 별도 UPDATE)
    conn.execute(
        "UPDATE authors SET nickname = ? WHERE author_id = ? AND nickname != ?",
        (nickname, persona_id, nickname),
    )

    return n_posts, n_photos


def discover_persona_ids(posts_dir: Path) -> list[str]:
    ids = sorted(
        p.stem for p in posts_dir.glob("*.jsonl")
    )
    return ids


def reset_db(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="코퍼스 → 가상 SNS DB 시딩")
    ap.add_argument("--corpus", required=True, help="posts 디렉터리 (예: data/corpus/v0/posts/)")
    ap.add_argument("--personas", required=True, help="personas 디렉터리 (예: data/corpus/v0/personas/)")
    ap.add_argument("--db", required=True, help="SQLite DB 경로 (예: data/interim/sns.db)")
    ap.add_argument("--authors", default=None, help="쉼표로 구분한 persona_id 목록. 생략하면 corpus 전체")
    ap.add_argument("--reset", action="store_true", help="DROP 후 schema.sql 로 재생성하고 다시 시딩한다")
    ap.add_argument("--seed", type=int, default=42, help="시각 흩뿌리기용 랜덤 시드 (재현성)")
    args = ap.parse_args()

    posts_dir = Path(args.corpus)
    personas_dir = Path(args.personas)
    db_path = Path(args.db)

    if args.reset:
        reset_db(db_path)

    import os
    os.environ["SNS_DB_PATH"] = str(db_path)
    conn = sns_db.connect()
    sns_db.init(conn)

    persona_ids = (
        [a.strip() for a in args.authors.split(",") if a.strip()]
        if args.authors
        else discover_persona_ids(posts_dir)
    )

    rng = random.Random(args.seed)
    total_posts = 0
    total_photos = 0
    for persona_id in persona_ids:
        if not (posts_dir / f"{persona_id}.jsonl").exists():
            print(f"⚠️  {persona_id}: {posts_dir} 에 코퍼스 파일 없음 — 건너뜀", file=sys.stderr)
            continue
        n_posts, n_photos = seed_persona(conn, posts_dir, personas_dir, persona_id, rng)
        total_posts += n_posts
        total_photos += n_photos
        print(f"  {persona_id}: 글 {n_posts}편 · 사진 캡션 {n_photos}건")

    conn.commit()
    conn.close()
    print(f"완료: 인물 {len(persona_ids)}명 / 새 글 {total_posts}편 / 새 사진 캡션 {total_photos}건 / {db_path}")


if __name__ == "__main__":
    main()
