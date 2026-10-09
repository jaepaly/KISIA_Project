"""가상 SNS v0 — 뼈대.

    pip install -r apps/sns/requirements.txt
    python apps/sns/app.py            # http://localhost:3000

⚠️ 이 파일은 **뼈대다.** 화면 4개(`list.html` · `post.html` · `new.html` ·
`profile.html`)는 E 가 채운다. 만드는 법은 docs/roles/howto/e-sns.md §4 에 있다.
지금은 템플릿이 없어도 서버가 뜨도록 라우트가 안내 문구를 돌려준다.

⭐ **다만 `/api/export/<user_ref>` 는 채워져 있다.**

이게 계층 경계다 (README 「내보내기 API 가 계층 경계다」 · plan.md §4).
분석기는 이 응답만 본다. 여기 없는 것은 분석기가 볼 수 없다.
형식이 틀리면 W5 통합 전까지 아무도 모르므로 계약대로 먼저 맞춰뒀다.
테스트가 계약을 강제한다 — `python -m pytest apps/sns/test_export.py`
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import Flask, abort, g, jsonify, redirect, render_template, request

from db import connect, init

app = Flask(__name__)
KST = timezone(timedelta(hours=9))
PAGE_SIZE = 20


@app.template_filter("hue")
def _hue(s: str) -> int:
    """작성자마다 같은 아바타 색 — 문자열을 0~359 색상각으로. 사진이 없는 가상 SNS 라 이니셜 아바타를 쓴다.
    글자 합이 아니라 해시다 — B18·B19 처럼 연번 ID 는 합으로 하면 1도 차이라 전부 같은 색이 된다."""
    import hashlib
    return int.from_bytes(hashlib.md5((s or "").encode("utf-8")).digest()[:2], "big") % 360


def db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def _close(_) -> None:
    if (c := g.pop("db", None)):
        c.close()


def _todo(screen: str, where: str) -> str:
    return (f"<h1>{screen} — 아직 안 만들었다</h1>"
            f"<p>만드는 법: <code>docs/roles/howto/e-sns.md {where}</code></p>"
            f'<p><a href="/api/export/u_00000000">/api/export/&lt;user_ref&gt;</a> 는 됩니다.</p>')


# ── 화면 4개 ─────────────────────────────────────────────────────────
@app.get("/")
def index():
    """글 목록. 최신순 · 작성자 필터 · private 는 회색."""
    author_id = request.args.get("author")
    page = max(1, request.args.get("page", 1, type=int))
    q = ("SELECT p.*, a.nickname, a.user_ref FROM posts p"
         " JOIN authors a ON a.author_id = p.author_id")
    args: list = []
    if author_id:
        q += " WHERE p.author_id = ?"
        args.append(author_id)
    # 한 장 더 읽어 다음 장이 있는지만 본다 — 20편씩 무한 스크롤 (list.html · fx.js)
    q += " ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
    args += [PAGE_SIZE + 1, (page - 1) * PAGE_SIZE]
    try:
        rows = db().execute(q, args).fetchall()
        posts, has_more = [dict(r) for r in rows[:PAGE_SIZE]], len(rows) > PAGE_SIZE
        # 사진 캡션 띠 — 카드를 안 열어도 사진이 있고 무엇인지 보이게 (데모 list.html 과 같은 모양)
        if posts:
            ids = [p["post_id"] for p in posts]
            caps: dict[str, list[str]] = {}
            for r in db().execute(
                    f"SELECT post_id, caption FROM photos WHERE post_id IN ({','.join('?' * len(ids))}) ORDER BY post_id, idx", ids):
                caps.setdefault(r["post_id"], []).append(r["caption"])
            for p in posts:
                p["photos"] = caps.get(p["post_id"], [])
        next_url = None
        if has_more:
            next_url = f"/?page={page + 1}" + (f"&author={author_id}" if author_id else "")
        if request.args.get("partial"):
            return render_template("_cards.html", posts=posts, next_url=next_url)
        authors = db().execute("SELECT * FROM authors ORDER BY nickname").fetchall()
        # 오른쪽 레일 — 글을 거치지 않고 프로필로 가는 길 · 자주 찍히는 동네 (공개 글만)
        recent_authors = db().execute(
            "SELECT a.author_id, a.nickname, a.user_ref, COUNT(*) AS n, MAX(p.created_at) AS last"
            " FROM posts p JOIN authors a ON a.author_id = p.author_id"
            " WHERE p.visibility = 'public' GROUP BY a.author_id ORDER BY last DESC LIMIT 8").fetchall()
        top_tags = db().execute(
            "SELECT geo_tag, COUNT(*) AS n FROM posts"
            " WHERE visibility = 'public' AND geo_tag IS NOT NULL AND geo_tag != ''"
            " GROUP BY geo_tag ORDER BY n DESC LIMIT 6").fetchall()
        return render_template("list.html", posts=posts, authors=authors,
                                selected_author=author_id, next_url=next_url,
                                recent_authors=recent_authors, top_tags=top_tags)
    except sqlite3.OperationalError:
        return _todo("글 목록", "§4")


@app.get("/posts/<post_id>")
def post(post_id: str):
    p = db().execute(
        "SELECT p.*, a.nickname, a.user_ref FROM posts p"
        " JOIN authors a ON a.author_id = p.author_id"
        " WHERE p.post_id = ?", (post_id,)).fetchone()
    if p is None:
        abort(404)
    photos = db().execute(
        "SELECT idx, caption FROM photos WHERE post_id = ? ORDER BY idx",
        (post_id,)).fetchall()
    try:
        return render_template("post.html", p=p, photos=photos)
    except sqlite3.OperationalError:
        return _todo("글 본문", "§4")


@app.get("/new")
def new():
    """작성 화면. ⚠️ 작성시각을 직접 입력받는다 — howto §4."""
    authors = db().execute("SELECT * FROM authors ORDER BY nickname").fetchall()
    now_kst = datetime.now(KST).strftime("%Y-%m-%dT%H:%M")
    try:
        return render_template("new.html", authors=authors, now=now_kst)
    except sqlite3.OperationalError:
        return _todo("글 작성", "§4")


@app.post("/posts")
def create_post():
    """조치 시연의 재료가 되는 글을 여기서 만든다. source는 항상 'manual'이다 —
    시딩(W4)이 넣는 글과 섞이지 않게 구분해 둔다."""
    f = request.form
    author_id = f["author_id"]
    created_at = f["created_at"]
    if len(created_at) == 16:          # <input type=datetime-local> 은 초가 없다
        created_at += ":00"
    created_at += "+09:00"

    visibility = f.get("visibility", "public")
    if visibility not in ("public", "private"):
        abort(400)

    post_id = f"{author_id}_m{os.urandom(4).hex()}"
    db().execute(
        "INSERT INTO posts(post_id, author_id, title, body, created_at,"
        " geo_tag, visibility, source) VALUES (?,?,?,?,?,?,?,'manual')",
        (post_id, author_id, f.get("title") or None, f["body"], created_at,
         f.get("geo_tag") or None, visibility))

    captions = [c.strip() for c in f.get("captions", "").splitlines() if c.strip()]
    for idx, caption in enumerate(captions):
        db().execute(
            "INSERT INTO photos(post_id, idx, caption) VALUES (?,?,?)",
            (post_id, idx, caption))

    db().commit()
    return redirect(f"/posts/{post_id}")


@app.post("/posts/<post_id>/visibility")
def toggle_visibility(post_id: str):
    """조치 ③ 비공개 — 사용자가 '플랫폼에서' 실행한다. 분석기가 아니다.

    분석기는 "이 글을 비공개하라"까지만 말하고, 실제로 누르는 건 여기다
    (E-system.md §2 「조치를 누가 실행하나」). visibility 를 바꾸면 다음
    /api/export 호출부터 이 글이 바로 빠진다 — 재스캔하면 위험도가 실제로
    내려가는 걸 보여줄 수 있다.
    """
    row = db().execute(
        "SELECT visibility, author_id FROM posts WHERE post_id = ?",
        (post_id,)).fetchone()
    if row is None:
        abort(404)
    new_v = "private" if row["visibility"] == "public" else "public"
    db().execute(
        "UPDATE posts SET visibility = ? WHERE post_id = ?", (new_v, post_id))
    db().commit()

    back = request.form.get("back") or f"/posts/{post_id}"
    return redirect(back)


@app.post("/u/<user_ref>/edit")
def edit_profile(user_ref: str):
    """활동 메타 관리 — nickname · bio 수정. W6."""
    a = db().execute(
        "SELECT * FROM authors WHERE user_ref = ?", (user_ref,)).fetchone()
    if a is None:
        abort(404)
    f = request.form
    nickname = f.get("nickname", "").strip() or a["nickname"]
    bio = f.get("bio", "").strip() or None
    db().execute(
        "UPDATE authors SET nickname = ?, bio = ? WHERE user_ref = ?",
        (nickname, bio, user_ref))
    db().commit()
    return redirect(f"/u/{user_ref}")


@app.post("/posts/<post_id>/edit")
def edit_post_meta(post_id: str):
    """활동 메타 관리 — geo_tag 수정. W6."""
    row = db().execute(
        "SELECT author_id FROM posts WHERE post_id = ?", (post_id,)).fetchone()
    if row is None:
        abort(404)
    geo_tag = request.form.get("geo_tag", "").strip() or None
    db().execute(
        "UPDATE posts SET geo_tag = ? WHERE post_id = ?", (geo_tag, post_id))
    db().commit()
    return redirect(f"/posts/{post_id}")


@app.get("/u/<user_ref>")
def profile(user_ref: str):
    a = db().execute(
        "SELECT * FROM authors WHERE user_ref = ?", (user_ref,)).fetchone()
    if a is None:
        abort(404)
    posts = db().execute(
        "SELECT * FROM posts WHERE author_id = ? ORDER BY created_at DESC",
        (a["author_id"],)).fetchall()
    raw = db().execute(
        "SELECT CAST(substr(created_at, 12, 2) AS INTEGER) AS h, COUNT(*) AS cnt"
        " FROM posts WHERE author_id = ? GROUP BY h ORDER BY h",
        (a["author_id"],)).fetchall()
    hour_dist = {r["h"]: r["cnt"] for r in raw}
    try:
        return render_template("profile.html", a=a, posts=posts, hour_dist=hour_dist)
    except sqlite3.OperationalError:
        return _todo("프로필", "§4")


# ── ⭐ 내보내기 — 계층 경계. 계약: docs/contracts/sns-minimal-spec.md ──
import json as _json
from pathlib import Path as _Path

# 인물 설정 파일 — author_id 가 곧 persona_id (A01 ↔ A01.json). 저장소 밖에 두면 PERSONAS_DIR 로
PERSONAS_DIR = _Path(os.environ.get("PERSONAS_DIR") or (_Path(__file__).resolve().parents[2] / "data" / "corpus" / "v0" / "personas"))
_TRUTH_KEYS = ("age", "sex", "location", "occupation", "family", "commute", "income")


def _persona_brief(author_id: str) -> dict | None:
    """테스터용 정답지 — 글을 안 읽어도 「이 사람은 이런 사람」을 알게. 설계 메모·단서 계획은 내보내지 않는다."""
    p = PERSONAS_DIR / f"{author_id}.json"
    if not p.exists():
        return None
    try:
        d = _json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    gt, voice, kw = d.get("ground_truth") or {}, d.get("voice") or {}, d.get("scoring_keywords") or {}
    words: list[str] = []
    for axis in ("location", "age", "occupation", "family", "commute", "income", "sex"):
        for w in (kw.get(axis) or [])[:3]:
            if w not in words:
                words.append(w)
    return {
        "type": d.get("persona_type") or d.get("alias"),
        "truth": {k: gt.get(k) for k in _TRUTH_KEYS},
        "voice": {k: voice[k] for k in ("종결어미", "말버릇", "이모지", "제목", "소재") if voice.get(k)},
        "words": words[:14],
        "words_by_axis": {k: (kw.get(k) or [])[:3] for k in _TRUTH_KEYS if kw.get(k)},
        "topics": (d.get("noise_topics") or [])[:5],
        "hours": (d.get("account") or {}).get("typical_active_hours"),
    }


@app.get("/api/author/<author_id>/summary")
def author_summary(author_id: str):
    """글쓰기 화면 오른쪽 패널 — 테스터는 이 작성자를 모른다. 인물 설정 + 소개·글 수·자주 찍는 동네·최근 글(공개만)."""
    a = db().execute("SELECT * FROM authors WHERE author_id = ?", (author_id,)).fetchone()
    if a is None:
        abort(404)
    posts = db().execute(
        "SELECT post_id, title, body, created_at, geo_tag FROM posts"
        " WHERE author_id = ? AND visibility = 'public' ORDER BY created_at DESC", (author_id,)).fetchall()
    tags: dict[str, int] = {}
    for p in posts:
        if p["geo_tag"]:
            tags[p["geo_tag"]] = tags.get(p["geo_tag"], 0) + 1
    top = sorted(tags.items(), key=lambda kv: -kv[1])[:3]
    return jsonify({
        "author_id": a["author_id"], "user_ref": a["user_ref"], "nickname": a["nickname"],
        "hue": _hue(a["author_id"]),   # 피드 아바타와 같은 색
        "persona": _persona_brief(a["author_id"]),
        "bio": a["bio"], "joined_at": (a["joined_at"] or "")[:10],
        "n_posts": len(posts), "last": posts[0]["created_at"][:10] if posts else None,
        "top_tags": [{"geo_tag": t, "n": n} for t, n in top],
        "recent": [{"post_id": p["post_id"], "title": p["title"] or "",
                    "snippet": (p["body"] or "").replace("\n", " ")[:70], "created_at": p["created_at"][:10]}
                   for p in posts[:4]],
    })


@app.get("/api/export/<user_ref>")
def export(user_ref: str):
    """분석기가 보는 유일한 창구.

    계약이 요구하는 것만 내보낸다. 플랫폼 내부 값(author_id · source ·
    visibility)은 넘기지 않는다 — 그게 계층 경계의 뜻이다.

    ⚠️ visibility='public' 만 나간다. 조치 ③「비공개」의 효과가
       분석 결과에 그대로 반영되어야 하기 때문이다.
    """
    a = db().execute(
        "SELECT * FROM authors WHERE user_ref = ?", (user_ref,)).fetchone()
    if a is None:
        return jsonify({"error": "unknown user_ref"}), 404

    rows = db().execute(
        "SELECT * FROM posts WHERE author_id = ? AND visibility = 'public'"
        " ORDER BY created_at", (a["author_id"],)).fetchall()

    caps: dict[str, list[dict]] = {}
    for r in db().execute(
        "SELECT p.post_id, p.idx, p.caption FROM photos p"
        " JOIN posts o ON o.post_id = p.post_id"
        " WHERE o.author_id = ? AND o.visibility = 'public'"
        " ORDER BY p.post_id, p.idx", (a["author_id"],)
    ):
        caps.setdefault(r["post_id"], []).append({"caption": r["caption"]})

    return jsonify({
        "schema_version": "1.0",
        "user_ref": a["user_ref"],
        "nickname": a["nickname"],
        "profile_bio": a["bio"],          # 채널 profile_bio — 사용자 단위다
        "posts": [{
            "post_id": r["post_id"],
            "user_ref": a["user_ref"],
            "title": r["title"],          # 채널 title
            "body": r["body"],            # 채널 body
            "photos": caps.get(r["post_id"], []),   # 채널 photo_caption:N — 순서 보존
            # 작성 날짜만 (YYYY-MM-DD) — 「작성일 + n주차」 시점 역산의 기준점 (#332).
            # 시각은 넣지 않는다: 시각은 조치 ②가 감추는 activity_meta.post_time 하나에만 둔다
            "post_date": r["created_at"][:10],
            "activity_meta": {
                "nickname": a["nickname"],
                "geo_tag": r["geo_tag"],
                "post_time": r["created_at"][11:16],   # created_at 에서 파생
            },
        } for r in rows],
    })


if __name__ == "__main__":
    with connect() as c:
        init(c)
    app.run(port=int(os.getenv("SNS_PORT", "3000")), debug=True)
