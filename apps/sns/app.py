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

# 파도풀(분석 앱) 주소 — 「내 계정 진단」 · 「이 글 점검」 · 글쓰기 실시간 점검이 부른다.
# 기본값 /check 는 인스턴스(veilo.site)의 nginx 프록시 경로. 저장소만 받아 로컬에서 돌리면
# PADO_BASE=http://localhost:8000 처럼 분석 앱 주소를 넘긴다 (#324 리뷰 · 정한 대로 (가))
PADO_BASE = os.environ.get("PADO_BASE", "/check").rstrip("/")


@app.context_processor
def _inject_pado_base() -> dict:
    return {"pado_base": PADO_BASE}


@app.template_filter("hue")
def _hue(s: str) -> int:
    """작성자마다 같은 아바타 색 — 문자열을 0~359 색상각으로. 사진이 없는 가상 SNS 라 이니셜 아바타를 쓴다.
    글자 합이 아니라 해시다 — B18·B19 처럼 연번 ID 는 합으로 하면 1도 차이라 전부 같은 색이 된다."""
    import hashlib
    return int.from_bytes(hashlib.md5((s or "").encode("utf-8")).digest()[:2], "big") % 360


# ── 방문자별 격리 — 공용 테스트 서버에서 한 사람의 수정(비공개·위치태그·프로필·새 글)이 남에게 보이지 않게 ──
# 첫 방문에 쿠키 veilo_sid 를 주고, 그 방문자의 요청은 시드 사본을 복사한 sessions/<sid>.db 로 보낸다.
# 시드 사본(sns.seed.db)이 없으면 꺼진다 — 로컬 개발은 지금처럼 DB 하나.
# 파도풀 분석기는 같은 도메인이라 쿠키를 받고, export 를 부를 때 X-Veilo-Session 헤더로 넘긴다.
import re as _re
import shutil as _shutil
import time as _time
import uuid as _uuid
from pathlib import Path as _Path

SESSION_COOKIE = "veilo_sid"
_SID_RE = _re.compile(r"^[0-9a-f]{16,32}$")
SESSION_IDLE_SECONDS = 48 * 3600


def _seed_path() -> _Path:
    from db import db_path
    return _Path(os.environ.get("SNS_SEED_DB") or db_path().with_name("sns.seed.db"))


def _session_dir() -> _Path:
    from db import db_path
    return _Path(os.environ.get("SNS_SESSION_DIR") or db_path().with_name("sessions"))


def isolation_on() -> bool:
    return _seed_path().exists()


def _sid() -> str | None:
    """쿠키 → 헤더(분석기가 넘김) 순. 형식이 어긋나면 없는 것으로.

    주소의 ?sid= 는 받지 않는다 — 주소를 공유하면 받은 사람이 그 방문자의 사본을 보고 고칠 수 있다 (#337 E 리뷰)."""
    s = request.cookies.get(SESSION_COOKIE) or request.headers.get("X-Veilo-Session")
    return s if s and _SID_RE.match(s) else None


def _session_db_path(sid: str) -> _Path:
    d = _session_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{sid}.db"
    if not p.exists():
        _shutil.copyfile(_seed_path(), p)
        _sweep_sessions(d)
    return p


def _sweep_sessions(d: _Path) -> None:
    """이틀 안 쓴 사본은 지운다 — 새 세션이 생길 때만 돈다."""
    cutoff = _time.time() - SESSION_IDLE_SECONDS
    for f in d.glob("*.db"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


@app.before_request
def _ensure_session() -> None:
    if not isolation_on():
        return
    sid = _sid()
    if sid is None and not request.path.startswith("/api/"):   # 분석기 호출(/api/export)은 헤더가 없으면 공용 DB
        sid = _uuid.uuid4().hex[:24]
        g.new_sid = sid
    g.sid = sid


@app.after_request
def _set_session_cookie(resp):
    if getattr(g, "new_sid", None):
        resp.set_cookie(SESSION_COOKIE, g.new_sid, max_age=7 * 24 * 3600, path="/", samesite="Lax",
                        httponly=True, secure=request.is_secure)
    return resp


# ── 첫 접속 = 1분 소개(/about) ── 「봤음」 쿠키가 없는 방문자가 홈(/)으로 오면 소개로 보낸다.
# 소개 화면을 열면(또는 ?skip_about=1 — 시연 · 테스트용) 쿠키를 심는다. 그 뒤로는 로고 · 「둘러보기」로 홈에 바로 간다.
# 홈 말고 다른 경로(/posts/… · /new · /u/… · /api/*)는 보내지 않는다 — 공유받은 글 주소로 바로 온 사람을 막지 않게.
ABOUT_COOKIE = "pado_about_seen"


def _about_seen() -> bool:
    return request.cookies.get(ABOUT_COOKIE) == "1" or request.args.get("skip_about") == "1"


@app.after_request
def _set_about_cookie(resp):
    if (request.path == "/about" or request.args.get("skip_about") == "1") and request.cookies.get(ABOUT_COOKIE) != "1":
        resp.set_cookie(ABOUT_COOKIE, "1", max_age=365 * 24 * 3600, path="/", samesite="Lax",
                        httponly=True, secure=request.is_secure)   # 서버만 읽는다 — 스크립트가 볼 일이 없다
    return resp


def db() -> sqlite3.Connection:
    if "db" not in g:
        sid = getattr(g, "sid", None)
        g.db = connect(_session_db_path(sid)) if (sid and isolation_on()) else connect()
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
    """글 목록. 최신순 · 작성자 필터 · private 는 회색. 처음 온 사람(소개 쿠키 없음)은 /about 으로."""
    if not _about_seen() and not request.args.get("partial"):
        return redirect("/about", code=302)
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
            _attach_clues(posts)
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
        # 왼쪽 레일 숫자 — 공개 글 수 · 위치 태그를 단 공개 글 비율(가상 데이터 그대로)
        st = db().execute(
            "SELECT COUNT(*) AS n, SUM(CASE WHEN geo_tag IS NOT NULL AND geo_tag != '' THEN 1 ELSE 0 END) AS g"
            " FROM posts WHERE visibility = 'public'").fetchone()
        stats = {"authors": len(authors), "posts": st["n"] or 0,
                 "geo_pct": round(100 * (st["g"] or 0) / st["n"]) if st["n"] else 0}
        return render_template("list.html", posts=posts, authors=authors,
                                selected_author=author_id, next_url=next_url,
                                recent_authors=recent_authors, top_tags=top_tags, stats=stats)
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
    # 고쳐 쓰기로 올린 글이면 원래 글 — 원래 글이 아직 공개면 「원래 글 비공개로」 띠 (같은 묶음으로 기록)
    rw = None
    try:
        rw = db().execute(
            "SELECT l.id, l.post_id, o.visibility, o.title FROM action_log l JOIN posts o ON o.post_id = l.post_id"
            " WHERE l.kind = 'rewrite' AND l.new_post_id = ? AND l.undone_at IS NULL ORDER BY l.id DESC LIMIT 1",
            (post_id,)).fetchone()
    except sqlite3.Error:
        pass
    try:
        return render_template("post.html", p=p, photos=photos, rw=rw)
    except sqlite3.OperationalError:
        return _todo("글 본문", "§4")


@app.get("/about")
def about():
    """「파도풀이란?」 1분 소개 — 스크롤 연출(pado-scene.js). ?view=static 이면 움직임 없이 다 펼친 화면."""
    return render_template("about.html", static=request.args.get("view") == "static")


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
    # 형식이 틀린 값이 들어오면 export 의 post_date([:10]) · post_time([11:16])이 둘 다 깨진다 (#334 Codex 검토)
    # strptime 은 전각 숫자(「２０２６」)도 받는다 — 그대로 저장되면 post_date 비교가 어긋난다 (#335 E 리뷰)
    if not created_at.isascii():
        abort(400)
    try:
        datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        abort(400)

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

    # 글 화면 「이 글을 옮겨 고쳐 쓰기」로 온 새 글이면 — 원래 글과 묶어 이력에 남긴다 (되돌리면 새 글을 지운다)
    src = f.get("from_post") or ""
    if src and db().execute("SELECT 1 FROM posts WHERE post_id = ? AND author_id = ?", (src, author_id)).fetchone():
        _log("rewrite", author_id, src, new_post_id=post_id)

    db().commit()
    return redirect(f"/posts/{post_id}?done=posted")


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
    # 고쳐 쓴 글 화면의 「원래 글 비공개로」 — 그 고쳐 쓰기(pair)와 한 묶음으로 남긴다. 따로 누른 비공개는 묶지 않는다 (S1)
    group = None
    pair = request.form.get("pair", type=int)
    if pair and new_v == "private" and db().execute(
            "SELECT 1 FROM action_log WHERE id = ? AND kind = 'rewrite' AND post_id = ? AND undone_at IS NULL",
            (pair, post_id)).fetchone():
        group = pair
    db().execute(
        "UPDATE posts SET visibility = ? WHERE post_id = ?", (new_v, post_id))
    _log(new_v, row["author_id"], post_id, row["visibility"], new_v, group_id=group)
    db().commit()

    # 돌아갈 곳은 이 사이트 안의 경로만 (//evil.example 같은 바깥 주소 차단) · ?done= 은 화면 맨 위 「다시 점검」 띠
    back = request.form.get("back") or ""
    if not back.startswith("/") or back.startswith("//"):
        back = f"/posts/{post_id}"
    return redirect(f"{back}{'&' if '?' in back else '?'}done={new_v}")


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
        "SELECT author_id, geo_tag FROM posts WHERE post_id = ?", (post_id,)).fetchone()
    if row is None:
        abort(404)
    geo_tag = request.form.get("geo_tag", "").strip() or None
    db().execute(
        "UPDATE posts SET geo_tag = ? WHERE post_id = ?", (geo_tag, post_id))
    if geo_tag != row["geo_tag"]:
        _log("geo", row["author_id"], post_id, row["geo_tag"], geo_tag)
    db().commit()
    return redirect(f"/posts/{post_id}?done=geo")


# ── 내 계정 · 조치 이력 — 방문자 체험용. 세션 사본의 me · action_log 표 (schema.sql 끝) ──
# 고르지 않아도 모든 화면이 지금처럼 돈다. 이력은 export 에 섞지 않는다 — 분석기는 글의 지금 상태만 본다.
def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _log(kind: str, author_id: str, post_id: str, before: str | None = None,
         after: str | None = None, new_post_id: str | None = None, group_id: int | None = None) -> None:
    db().execute(
        "INSERT INTO action_log(at, kind, author_id, post_id, before_val, after_val, new_post_id, group_id)"
        " VALUES (?,?,?,?,?,?,?,?)", (_now(), kind, author_id, post_id, before, after, new_post_id, group_id))


def _me() -> dict | None:
    r = db().execute(
        "SELECT a.author_id, a.user_ref, a.nickname FROM me JOIN authors a ON a.author_id = me.author_id"
        " WHERE me.id = 1").fetchone()
    return dict(r) if r else None


def _changes(author_id: str | None = None) -> list[dict]:
    """살아 있는(되돌리지 않은) 조치 — 최근 것부터. 글 제목을 붙여 화면에 그대로 쓴다."""
    q = ("SELECT l.*, p.title AS title, p.body AS body FROM action_log l"
         " LEFT JOIN posts p ON p.post_id = l.post_id WHERE l.undone_at IS NULL")
    args: list = []
    if author_id:
        q += " AND l.author_id = ?"
        args.append(author_id)
    out = []
    for r in db().execute(q + " ORDER BY l.id DESC", args).fetchall():
        d = dict(r)
        d["label"] = d["title"] or (d["body"] or "").replace("\n", " ")[:24] or "(지워진 글)"
        d["time"] = d["at"][11:16]
        out.append(d)
    # 한 묶음 — 고쳐 쓴 글 화면에서 누른 「원래 글 비공개로」만 그 고쳐 쓰기에 묶인다(group_id). 화면에 짝 표시
    # 사슬 — 고쳐 쓴 글을 다시 고쳐 쓴 항목이 있으면 앞 항목을 되돌릴 때 뒤 항목도 함께 되돌린다 (_undo)
    active = {d["id"] for d in out}
    grouped = {d["group_id"] for d in out if d.get("group_id") in active}
    rewrites_of = {d["post_id"] for d in out if d["kind"] == "rewrite"}
    for d in out:
        d["paired"] = (d["kind"] == "private" and d.get("group_id") in active) or \
                      (d["kind"] == "rewrite" and d["id"] in grouped)
        d["chained"] = d["kind"] == "rewrite" and d["new_post_id"] in rewrites_of
    return out


_FIELD = {"private": "visibility", "public": "visibility", "geo": "geo_tag"}


def _undo(entry, cascade: bool = True) -> None:
    """조치 하나를 되돌린다. 같은 글 같은 칸의 그 뒤 조치도 함께 닫는다 — 값이 이 조치 전으로 돌아가니까.

    cascade=False 는 고쳐 쓰기 묶음을 따라 되돌릴 때다 — 그 뒤에 같은 칸을 따로 바꾼 조치가 살아 있으면
    이 조치의 효과는 이미 덮였으므로 값은 두고 이 항목만 닫는다 (뒤의 독립 조치를 취소하지 않는다 · S1)."""
    now, c = _now(), db()
    if entry["kind"] == "rewrite":
        nid = entry["new_post_id"]
        # ① 사슬 — 새 글(B)을 다시 고쳐 쓴 항목(B→C)부터 끝에서 되돌린다. C 가 이력 없이 남지 않게 (B1)
        for dep in c.execute("SELECT * FROM action_log WHERE kind = 'rewrite' AND post_id = ? AND undone_at IS NULL"
                             " ORDER BY id DESC", (nid,)).fetchall():
            _undo(dep)
        # ② 묶음 — 이 고쳐 쓰기 화면에서 누른 「원래 글 비공개로」만 함께 되돌린다. 따로 한 비공개는 그대로 (S1)
        for g in c.execute("SELECT * FROM action_log WHERE group_id = ? AND undone_at IS NULL ORDER BY id",
                           (entry["id"],)).fetchall():
            if c.execute("SELECT undone_at FROM action_log WHERE id = ?", (g["id"],)).fetchone()["undone_at"] is None:
                _undo(g, cascade=False)
        # ③ 새 글을 지우고, 새 글에 했던 조치(비공개·위치)는 글이 없어졌으니 같이 닫는다
        c.execute("DELETE FROM photos WHERE post_id = ?", (nid,))
        c.execute("DELETE FROM posts WHERE post_id = ?", (nid,))
        c.execute("UPDATE action_log SET undone_at = ? WHERE (post_id = ? OR id = ?) AND undone_at IS NULL",
                  (now, nid, entry["id"]))
        return
    field = _FIELD[entry["kind"]]
    kinds = ("private", "public") if field == "visibility" else ("geo",)
    kind_in = f"kind IN ({','.join('?' * len(kinds))})"
    nxt = None if cascade else c.execute(
        f"SELECT id FROM action_log WHERE post_id = ? AND id > ? AND undone_at IS NULL AND {kind_in} ORDER BY id LIMIT 1",
        (entry["post_id"], entry["id"], *kinds)).fetchone()
    if nxt:
        # 이 조치를 이력에서 빼면 바로 다음 조치의 「바꾸기 전 값」은 이 조치 전의 값이 된다 — 나중에 그것을 되돌려도 원래로 간다
        c.execute("UPDATE action_log SET before_val = ? WHERE id = ?", (entry["before_val"], nxt["id"]))
        c.execute("UPDATE action_log SET undone_at = ? WHERE id = ?", (now, entry["id"]))
        return
    c.execute(f"UPDATE posts SET {field} = ? WHERE post_id = ?", (entry["before_val"], entry["post_id"]))
    c.execute(
        f"UPDATE action_log SET undone_at = ? WHERE post_id = ? AND id >= ? AND undone_at IS NULL"
        f" AND kind IN ({','.join('?' * len(kinds))})", (now, entry["post_id"], entry["id"], *kinds))


def _back(default: str) -> str:
    """돌아갈 곳은 이 사이트 안의 경로만 (//evil.example 같은 바깥 주소 차단)."""
    back = request.form.get("back") or ""
    return back if back.startswith("/") and not back.startswith("//") else default


def _with_done(url: str, done: str) -> str:
    return f"{url}{'&' if '?' in url else '?'}done={done}"


@app.context_processor
def _inject_me() -> dict:
    """상단바 「내 계정」 — 고른 사람과 그 사람이 바꾼 것 수. 표·DB 가 아직 없으면 빈 값 (고르지 않아도 다 돈다)."""
    try:
        me = _me()
        n = len(_changes(me["author_id"])) if me else 0
    except sqlite3.Error:
        me, n = None, 0
    return {"me": me, "me_changes": n, "clue_per_page": CLUE_PER_PAGE}


@app.post("/me")
def set_me():
    """이 사람으로 체험하기 — author_id 가 비어 있으면 「내 계정」을 푼다."""
    aid = (request.form.get("author_id") or "").strip()
    if aid:
        if db().execute("SELECT 1 FROM authors WHERE author_id = ?", (aid,)).fetchone() is None:
            abort(404)
        db().execute("INSERT INTO me(id, author_id, chosen_at) VALUES (1, ?, ?)"
                     " ON CONFLICT(id) DO UPDATE SET author_id = excluded.author_id, chosen_at = excluded.chosen_at",
                     (aid, _now()))
    else:
        db().execute("DELETE FROM me")
    db().commit()
    if request.headers.get("X-Requested-With") == "fetch":   # 글쓰기 화면 — 쓰던 글을 날리지 않게 새로고침 없이
        return jsonify({"me": _me()})
    return redirect(_with_done(_back("/"), "me" if aid else "me_off"))


@app.post("/changes/<int:log_id>/undo")
def undo_change(log_id: int):
    e = db().execute("SELECT * FROM action_log WHERE id = ? AND undone_at IS NULL", (log_id,)).fetchone()
    if e is None:
        abort(404)
    _undo(e)
    db().commit()
    return redirect(_with_done(_back("/"), "undo"))


@app.post("/changes/undo-all")
def undo_all():
    """모두 되돌리기 — 최근 것부터 차례로. author_id 를 주면 그 계정만."""
    aid = request.form.get("author_id") or None
    q, args = "SELECT * FROM action_log WHERE undone_at IS NULL", []
    if aid:
        q += " AND author_id = ?"
        args.append(aid)
    for row in db().execute(q + " ORDER BY id DESC", args).fetchall():
        # 앞서 되돌린 조치가 이 줄을 이미 닫았을 수 있다 (같은 글 같은 칸)
        if db().execute("SELECT undone_at FROM action_log WHERE id = ?", (row["id"],)).fetchone()["undone_at"] is None:
            _undo(row)
    db().commit()
    return redirect(_with_done(_back("/"), "undo"))


# ── 위험 배지 「📍 단서 N곳」 — 내 계정 글에만. 서버 부담이 핵심 제약이다(글 하나 점검 ≈ 2초 · 운영 서버 하나) ──
# Veilo 는 점검하지 않는다. 브라우저(clues.js)가 글쓰기 실시간 점검과 같은 글 점검 API 로 센 값을 여기 저장하고,
# 다음부터는 저장된 값으로 배지만 그린다. 본문이 바뀌면(해시가 다르면) 무효라 다시 센다.
CLUE_PER_PAGE = 5   # 한 화면에서 브라우저가 새로 세는 글 수 상한 — clues.js 가 이 값을 받는다


def _body_hash(body: str | None) -> str:
    import hashlib
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()[:16]


def _attach_clues(posts: list[dict]) -> None:
    """내 계정의 공개 글에 p['clues'](저장된 단서 수) 또는 p['clue_need'](아직 안 셈)를 붙인다. 내 계정이 없으면 아무것도 안 한다."""
    try:
        me = _me()
    except sqlite3.Error:
        return
    mine = [p for p in posts if me and p["author_id"] == me["author_id"] and p["visibility"] == "public"]
    if not mine:
        return
    ids = [p["post_id"] for p in mine]
    cache = {r["post_id"]: r for r in db().execute(
        f"SELECT * FROM clue_cache WHERE post_id IN ({','.join('?' * len(ids))})", ids)}
    for p in mine:
        c = cache.get(p["post_id"])
        if c is not None and c["body_hash"] == _body_hash(p["body"]):
            p["clues"] = c["n_clues"]
        else:
            p["clue_need"] = True


@app.post("/api/clues/<post_id>")
def save_clues(post_id: str):
    """브라우저가 센 단서 수를 저장한다 — 내 계정 글만. 해시는 서버가 지금 본문으로 계산한다."""
    me = _me()
    row = db().execute("SELECT author_id, body FROM posts WHERE post_id = ?", (post_id,)).fetchone()
    if me is None or row is None or row["author_id"] != me["author_id"]:
        return jsonify({"error": "not my post"}), 403
    n = (request.get_json(silent=True) or {}).get("n")
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= 500:
        return jsonify({"error": "bad n"}), 400
    db().execute("INSERT INTO clue_cache(post_id, body_hash, n_clues, at) VALUES (?,?,?,?)"
                 " ON CONFLICT(post_id) DO UPDATE SET body_hash = excluded.body_hash,"
                 " n_clues = excluded.n_clues, at = excluded.at",
                 (post_id, _body_hash(row["body"]), n, _now()))
    db().commit()
    return jsonify({"ok": True, "n": n})


@app.get("/api/me")
def api_me():
    """파도풀 화면 상단바의 내 계정 아바타 — 세션의 내 계정. 없으면 {"me": null}.
    export 와 같은 규칙으로 플랫폼 내부 값(author_id)은 내보내지 않는다."""
    try:
        me = _me()
        n = len(_changes(me["author_id"])) if me else 0
    except sqlite3.Error:
        me = None
    if me is None:
        return jsonify({"me": None})
    return jsonify({"me": {"user_ref": me["user_ref"], "nickname": me["nickname"],
                           "hue": _hue(me["author_id"]), "changes": n}})


@app.after_request
def _cors_api_me(resp):
    """로컬 분리 실행(파도풀 :8000 · Veilo :3000)에서 파도풀 화면이 /api/me 를 쿠키와 함께 부를 수 있게 —
    PADO_BASE 의 출처 하나만 허용한다. 운영은 같은 도메인(/check)이라 필요 없다."""
    if request.path == "/api/me" and PADO_BASE.startswith(("http://", "https://")):
        from urllib.parse import urlsplit
        o = urlsplit(PADO_BASE)
        origin = f"{o.scheme}://{o.netloc}"
        if request.headers.get("Origin") == origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Vary"] = "Origin"
    return resp


@app.get("/u/<user_ref>")
def profile(user_ref: str):
    a = db().execute(
        "SELECT * FROM authors WHERE user_ref = ?", (user_ref,)).fetchone()
    if a is None:
        abort(404)
    posts = [dict(r) for r in db().execute(
        "SELECT * FROM posts WHERE author_id = ? ORDER BY created_at DESC",
        (a["author_id"],)).fetchall()]
    _attach_clues(posts)
    raw = db().execute(
        "SELECT CAST(substr(created_at, 12, 2) AS INTEGER) AS h, COUNT(*) AS cnt"
        " FROM posts WHERE author_id = ? GROUP BY h ORDER BY h",
        (a["author_id"],)).fetchall()
    hour_dist = {r["h"]: r["cnt"] for r in raw}
    try:
        return render_template("profile.html", a=a, posts=posts, hour_dist=hour_dist,
                               changes=_changes(a["author_id"]), today=datetime.now(KST).date().isoformat())
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


@app.post("/u/<user_ref>/reset")
def reset_author(user_ref: str):
    """이 계정만 시드 상태로 — 공용 테스트 서버라 한 사람의 수정(비공개·위치태그·프로필·새 글)이 모두에게 보인다.
    시드 사본은 라이브 DB 옆 sns.seed.db (SNS_SEED_DB 로 바꿀 수 있다). 다른 계정은 건드리지 않는다."""
    a = db().execute("SELECT * FROM authors WHERE user_ref = ?", (user_ref,)).fetchone()
    if a is None:
        abort(404)
    seed = _seed_path()
    if not seed.exists():
        abort(503, "시드 사본(sns.seed.db)이 없어 되돌릴 수 없습니다")
    aid, c = a["author_id"], db()
    c.execute("ATTACH DATABASE ? AS seed", (str(seed),))
    try:
        # authors 행은 지우지 않고 덮어쓴다 — posts 가 FK 로 물고 있어 DELETE 가 막힌다
        c.execute("UPDATE authors SET nickname = (SELECT nickname FROM seed.authors WHERE author_id = ?),"
                  " bio = (SELECT bio FROM seed.authors WHERE author_id = ?),"
                  " joined_at = (SELECT joined_at FROM seed.authors WHERE author_id = ?) WHERE author_id = ?", (aid, aid, aid, aid))
        c.execute("DELETE FROM photos WHERE post_id IN (SELECT post_id FROM posts WHERE author_id = ?)", (aid,))
        c.execute("DELETE FROM posts WHERE author_id = ?", (aid,))
        c.execute("INSERT INTO posts SELECT * FROM seed.posts WHERE author_id = ?", (aid,))
        c.execute("INSERT INTO photos SELECT * FROM seed.photos"
                  " WHERE post_id IN (SELECT post_id FROM seed.posts WHERE author_id = ?)", (aid,))
        # 처음 상태로 돌아갔으니 이 계정의 조치 이력도 모두 되돌린 것으로
        c.execute("UPDATE action_log SET undone_at = ? WHERE author_id = ? AND undone_at IS NULL", (_now(), aid))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.execute("DETACH DATABASE seed")
    return redirect(f"/u/{user_ref}")


@app.get("/api/authors")
def authors_search():
    """닉네임으로 계정 찾기 — 파도풀 스캔 화면의 「가상 SNS 계정에서 가져오기」가 쓴다 (식별자를 외워 오게 하지 않는다).

    export 다음의 두 번째 창구다 (sns-minimal-spec §6). 분석기에 넘기는 값이라 export 와 같은 규칙으로
    플랫폼 내부 값(author_id)은 내보내지 않는다 — user_ref · nickname · n_posts 만 (#337 리뷰 (나))."""
    q = (request.args.get("q") or "").strip()
    # 처음 온 사람은 계정 이름을 모른다 — 빈 검색어는 「둘러보기」(공개 글 많은 순). limit 으로 더 보기 (기본 12 · 최대 200)
    try:
        limit = max(1, min(200, int(request.args.get("limit") or 12)))
    except ValueError:
        limit = 12
    sql = ("SELECT a.author_id, a.nickname, a.user_ref, a.bio, COUNT(p.post_id) AS n"
           " FROM authors a LEFT JOIN posts p ON p.author_id = a.author_id AND p.visibility = 'public'")
    args: list = []
    if q:
        sql += " WHERE a.nickname LIKE ? OR a.user_ref LIKE ?"
        args += [f"%{q}%", f"{q}%"]
    if q:
        sql += " GROUP BY a.author_id ORDER BY (a.nickname LIKE ?) DESC, a.nickname LIMIT ?"
        args += [f"{q}%", limit]
    else:
        sql += " GROUP BY a.author_id ORDER BY n DESC, a.nickname LIMIT ?"
        args.append(limit)
    rows = db().execute(sql, args).fetchall()
    return jsonify([{"user_ref": r["user_ref"], "nickname": r["nickname"], "n_posts": r["n"]} for r in rows])


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


@app.errorhandler(404)
def not_found(_):
    """영어 기본 화면 대신 Veilo 꾸밈의 한국어 안내 (분석기 API 404 는 JSON 그대로 — export 는 직접 jsonify 한다)."""
    if request.path.startswith("/api/"):
        return jsonify({"error": "not found"}), 404
    return render_template("404.html"), 404


if __name__ == "__main__":
    with connect() as c:
        init(c)
    app.run(port=int(os.getenv("SNS_PORT", "3000")), debug=True)
