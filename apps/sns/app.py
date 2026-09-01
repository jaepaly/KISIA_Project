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
    q = ("SELECT p.*, a.nickname, a.user_ref FROM posts p"
         " JOIN authors a ON a.author_id = p.author_id")
    args: list[str] = []
    if author_id:
        q += " WHERE p.author_id = ?"
        args.append(author_id)
    q += " ORDER BY p.created_at DESC LIMIT 200"
    try:
        posts = db().execute(q, args).fetchall()
        authors = db().execute("SELECT * FROM authors ORDER BY nickname").fetchall()
        return render_template("list.html", posts=posts, authors=authors,
                                selected_author=author_id)
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

    post_id = f"{author_id}_m{os.urandom(4).hex()}"
    db().execute(
        "INSERT INTO posts(post_id, author_id, title, body, created_at,"
        " geo_tag, visibility, source) VALUES (?,?,?,?,?,?,'public','manual')",
        (post_id, author_id, f.get("title") or None, f["body"], created_at,
         f.get("geo_tag") or None))

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


@app.get("/u/<user_ref>")
def profile(user_ref: str):
    a = db().execute(
        "SELECT * FROM authors WHERE user_ref = ?", (user_ref,)).fetchone()
    if a is None:
        abort(404)
    posts = db().execute(
        "SELECT * FROM posts WHERE author_id = ? ORDER BY created_at DESC",
        (a["author_id"],)).fetchall()
    try:
        return render_template("profile.html", a=a, posts=posts)
    except sqlite3.OperationalError:
        return _todo("프로필", "§4")


# ── ⭐ 내보내기 — 계층 경계. 계약: docs/contracts/sns-minimal-spec.md ──
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
