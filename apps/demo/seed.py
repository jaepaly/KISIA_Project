"""코퍼스 인물·글을 우리뜰(apps/sns) DB 에 시딩한다 — 데모 리허설용.

    python apps/demo/seed.py --reset            # DB 삭제 → schema.sql → 시딩
    python apps/demo/seed.py --personas D05,D01 # 인물 지정

E 의 W4 정식 시딩 스크립트(scripts/seed_sns.py · howto/e-sns.md §5)가 나오면 이 파일은 지운다.
그 문서의 세 가지를 지킨다 — 멱등(INSERT OR IGNORE) · 작성시각은 코퍼스 값 그대로 · --reset.

⚠️ 코퍼스 파일은 읽기만 한다. 인물 JSON 을 재직렬화하지 않는다.
⚠️ 위치태그는 인물마다 ambient 글 한 편에만 단다 — 조치 ② 시연 재료. 값은 ground_truth 의
   시군구·읍면동이다. 합성 인물이므로 문제없다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNS = ROOT / "apps" / "sns"
CORPUS = ROOT / "data" / "corpus" / "v0"
sys.path.insert(0, str(SNS))

from db import connect, db_path, init  # noqa: E402  (apps/sns/db.py)

# 시연 인물 — k 가 산출되는(UNKNOWN 이 아닌) 인물만. 첫째가 메인 시연.
DEFAULT_PERSONAS = ["D05", "D01", "D11", "D17", "D06"]


def user_ref(persona_id: str) -> str:
    """계약 형식 ^u_[0-9a-f]{8,}$ — 인물 ID 에서 결정론적으로 만든다."""
    return "u_" + hashlib.sha1(persona_id.encode()).hexdigest()[:8]


def load_persona(pid: str) -> dict:
    return json.loads((CORPUS / "personas" / f"{pid}.json").read_text(encoding="utf-8"))


def load_posts(pid: str) -> list[dict]:
    p = CORPUS / "posts" / f"{pid}.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def geo_tag_for(persona: dict) -> str | None:
    loc = (persona.get("ground_truth") or {}).get("location") or ""
    parts = loc.split()
    return " ".join(parts[-2:]) if len(parts) >= 2 else None


def seed(conn, pids: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pid in pids:
        persona = load_persona(pid)
        acct = persona.get("account") or {}
        joined = (acct.get("joined") or "2024-01") + "-01T09:00:00+09:00"
        conn.execute(
            "INSERT OR IGNORE INTO authors(author_id,user_ref,nickname,bio,joined_at) VALUES(?,?,?,?,?)",
            (pid, user_ref(pid), acct.get("nickname") or pid, acct.get("profile_intro"), joined))
        posts = sorted(load_posts(pid), key=lambda p: p["post_id"])
        tag = geo_tag_for(persona)
        tagged = False
        n = 0
        for post in posts:
            texts = post["texts"]
            geo = None
            if tag and not tagged and post.get("kind") == "ambient":
                geo, tagged = tag, True
            conn.execute(
                "INSERT OR IGNORE INTO posts(post_id,author_id,title,body,created_at,geo_tag,visibility,source)"
                " VALUES(?,?,?,?,?,?,'public','seed')",
                (post["post_id"], pid, texts.get("title"), texts["body"], post["created_at"], geo))
            caps = sorted((k for k in texts if k.startswith("photo_caption:")), key=lambda k: int(k.split(":")[1]))
            for k in caps:
                conn.execute("INSERT OR IGNORE INTO photos(post_id,idx,caption) VALUES(?,?,?)",
                             (post["post_id"], int(k.split(":")[1]), texts[k]))
            n += 1
        counts[pid] = n
    conn.commit()
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--personas", default=",".join(DEFAULT_PERSONAS))
    args = ap.parse_args()
    pids = [p.strip() for p in args.personas.split(",") if p.strip()]

    p = db_path()
    if args.reset and p.exists():
        try:
            p.unlink()
        except PermissionError:
            # 서버가 파일을 잡고 있다(Windows). 파일 대신 테이블을 비운다 — howto 의 「DROP → schema.sql」
            c = connect()
            c.executescript("DROP TABLE IF EXISTS photos; DROP TABLE IF EXISTS posts; DROP TABLE IF EXISTS authors;")
            c.commit()
            c.close()
            print("db 파일이 사용 중이라 테이블만 비웠다 (서버가 떠 있다)")
    c = connect()
    try:
        init(c)
        counts = seed(c, pids)
    finally:
        c.close()
    print(f"db: {p}")
    for pid, n in counts.items():
        print(f"  {pid}  {user_ref(pid)}  posts={n}")


if __name__ == "__main__":
    main()
