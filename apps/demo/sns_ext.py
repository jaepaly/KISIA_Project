"""우리뜰 실행기 — `apps/sns` 를 **고치지 않고** 파도풀을 붙인 플랫폼으로 띄운다.

    python apps/demo/sns_ext.py            # http://localhost:3000 (SNS_PORT)
    PADOPOOL_URL=http://localhost:8000     # 파도풀 API. 우리뜰이 이 서비스를 «붙여 쓴다»

논지: 파도풀은 플랫폼에 붙는 서비스다. 우리뜰이 네이버·인스타 자리이고, 다른 SNS 도 같은 방식으로 붙일 수 있다.
경계는 그대로다 — 우리뜰이 파도풀에 보내는 것은 `/api/export` 와 같은 형식뿐이고, 파도풀은 저장하지 않는다.
조치 실행(비공개·태그·본문 수정)은 전부 우리뜰 라우트다. 파도풀은 권고만 한다.

apps/sns/app.py 는 E 소유라 손대지 않는다. 그 Flask 앱을 import 해서
  - GET  /u/<user_ref>/check    「내 글 점검」 — 파도풀 /api/scan 결과를 우리뜰 화면에 그린다. 조치 버튼도 여기
  - GET  /new  · POST /check-draft   글쓰기 에디터에 「🌊 점검」 — 올리기 전 1회 [MF-015]
  - GET  /u/<user_ref>  · /posts/<id>   프로필·글 화면 덮어쓰기 (진입 버튼 · 태그 지우기 · 본문 고치기)
  - POST /posts/<id>/geo_tag · /edit · /body   조치 ②③
를 더한다. 비공개 토글(조치 ①)과 /api/export 는 원본 그대로다.

E 의 W4~W6 «메타 관리» · W9 «에디터 경고» 가 나오면 이 파일과 templates/sns_ext/ 는 지운다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNS = HERE.parent / "sns"
sys.path.insert(0, str(SNS))          # apps/sns/app.py 가 `from db import ...` 를 쓴다
sys.path.insert(0, str(HERE))         # /demo/reset 이 seed.py 를 import 한다

import jinja2  # noqa: E402
import requests  # noqa: E402
from flask import abort, redirect, render_template, request, send_from_directory, session  # noqa: E402

PADO = os.getenv("PADOPOOL_URL", "http://localhost:8000").rstrip("/")
KST = timezone(timedelta(hours=9))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sns = _load("sns_app", SNS / "app.py")
app, db = sns.app, sns.db
app.secret_key = os.getenv("SNS_SECRET", "urittle-demo-not-secret")   # 지난 점검 k 를 쿠키 세션에 둔다
app.jinja_loader = jinja2.ChoiceLoader([
    jinja2.FileSystemLoader(str(HERE / "templates" / "sns_ext")),
    app.jinja_loader,
])


@app.get("/pado-static/<path:fname>")
def pado_static(fname: str):
    return send_from_directory(HERE / "static", fname)


# 외부에 잠깐 노출할 때(터널·임시 배포) 링크 유출 대비 — DEMO_ACCESS_KEY 가 있으면 ?key= 로 한 번 들어와야 한다(쿠키로 기억)
ACCESS_KEY = os.getenv("DEMO_ACCESS_KEY", "")


_ACTION_PATH = re.compile(r"^/posts/[^/]+/(visibility|geo_tag|body)$")


@app.before_request
def _mark_action():
    """조치 라우트(비공개는 apps/sns 원본)를 지나면 표시해 둔다 — 점검 화면이 «방금 조치했다» 를 알 수 있게."""
    if request.method == "POST" and _ACTION_PATH.match(request.path):
        session["acted"] = True


@app.before_request
def _gate():
    if not ACCESS_KEY or request.path.startswith("/pado-static/"):
        return None
    if request.args.get("key") == ACCESS_KEY:
        resp = redirect(request.path)
        resp.set_cookie("pado_key", ACCESS_KEY, max_age=60 * 60 * 24 * 30, samesite="Lax")
        return resp
    if request.cookies.get("pado_key") == ACCESS_KEY:
        return None
    return ("<h2 style='font-family:sans-serif;margin:40px'>초대 링크로 들어와 주세요</h2>", 403)


# ── 화면 장식 — 좋아요·댓글·이웃 수. 글 ID 에서 결정론적으로 만든다 ──────────
#    시연 때마다 숫자가 흔들리면 어제 캡처와 달라져 설명이 꼬인다. 저장하지 않는다.
_AVATARS = ["🌾", "🌻", "🌿", "🪴", "🌱", "🍀", "🌷", "🧺", "🪺", "🫖"]
_CMT_WHO = [("뜰지기", "🪵"), ("이쁜할매", "🌷"), ("감나무집", "🍂"), ("바람꽃", "🌾"),
            ("옆집총각", "🧢"), ("도시댁", "🧺"), ("산딸기", "🍓")]
_CMT_TEXT = ["잘 보고 갑니다 ^^", "사진이 참 곱네요", "저도 오늘 그랬어요", "오늘도 잘 읽었습니다",
             "다음 글도 기다릴게요", "정겹습니다 ~", "읽으니 마음이 놓이네요", "저희 동네도 비슷해요"]
_CMT_WHEN = ["1일 전", "2일 전", "3일 전", "5일 전", "일주일 전"]


def _seed(key: str, salt: str = "") -> int:
    return int(hashlib.sha1((salt + key).encode()).hexdigest()[:8], 16)


def ut_avatar(author_id: str | None) -> str:
    return _AVATARS[_seed(author_id or "?", "av") % len(_AVATARS)]


def _load_comments() -> dict[str, list[dict]] | None:
    """gen_comments.py 가 만든 글별 댓글. 파일이 없으면 None → 옛 장식 문구로 떨어진다."""
    f = HERE / "data" / "comments.json"
    if not f.exists():
        return None
    import json
    return json.loads(f.read_text(encoding="utf-8"))


_COMMENTS = _load_comments()


def _n_comments_seed(post_id: str) -> int:
    return (_seed(post_id, "eng") >> 8) % 6


def ut_engage(post_id: str) -> dict:
    n = _seed(post_id, "eng")
    # 댓글 수 — 생성된 댓글이 있으면 그 수(심사자가 새로 쓴 글은 0), 없으면 글 ID 에서
    n_cmt = len(_COMMENTS.get(post_id, [])) if _COMMENTS is not None else _n_comments_seed(post_id)
    return {"likes": 3 + n % 38, "comments": n_cmt, "views": 60 + (n >> 12) % 900}


def ut_comments(post_id: str) -> list[dict]:
    if _COMMENTS is not None:
        return _COMMENTS.get(post_id, [])
    out = []
    for i in range(_n_comments_seed(post_id)):
        n = _seed(f"{post_id}:{i}", "cmt")
        who, emoji = _CMT_WHO[n % len(_CMT_WHO)]
        out.append({"who": who, "emoji": emoji, "text": _CMT_TEXT[(n >> 6) % len(_CMT_TEXT)],
                    "when": _CMT_WHEN[(n >> 12) % len(_CMT_WHEN)]})
    return out


def ut_stats(author_id: str) -> dict:
    n = _seed(author_id, "st")
    return {"neighbors": 12 + n % 60, "visits": 300 + (n >> 8) % 4000}


app.jinja_env.globals.update(ut_avatar=ut_avatar, ut_engage=ut_engage, ut_comments=ut_comments,
                             ut_stats=ut_stats)


@app.context_processor
def _chrome():
    """헤더가 쓰는 것 — 지금 보고 있는 계정(me)과 활성 메뉴(nav).

    우리뜰에는 로그인이 없다. 데모에서는 «보고 있는 블로그의 주인» 을 내 계정처럼 다룬다. 홈에서는 없다.
    """
    me = None
    va = (request.view_args or {})
    if va.get("user_ref"):
        me = db().execute("SELECT * FROM authors WHERE user_ref = ?", (va["user_ref"],)).fetchone()
    elif va.get("post_id"):
        me = db().execute("SELECT a.* FROM authors a JOIN posts p ON p.author_id = a.author_id"
                          " WHERE p.post_id = ?", (va["post_id"],)).fetchone()
    # 홈·글쓰기처럼 아무 블로그도 안 보고 있으면 «나» 는 없다 — 마당일기를 기본값으로 두면 심사자가 헷갈린다
    nav = {"index": "home", "profile": "blog", "check": "check", "new": "new", "login": "login", "signup": "login"}.get(request.endpoint or "")
    neighbors = db().execute("SELECT * FROM authors WHERE author_id != 'GUEST' ORDER BY author_id").fetchall()
    n_posts = {r["author_id"]: r["n"] for r in
               db().execute("SELECT author_id, COUNT(*) n FROM posts WHERE visibility = 'public' GROUP BY author_id")}
    return {"me": me, "nav": nav, "neighbors": neighbors, "n_posts_by": n_posts}


# ── 파도풀 호출 — 보내는 것은 export 형식뿐 ─────────────────────────────────
def export_json(user_ref: str) -> dict | None:
    resp = sns.export(user_ref)                 # 원본 뷰 함수를 그대로 부른다 — 같은 경계
    if isinstance(resp, tuple):                 # (jsonify(error), 404)
        return None
    return resp.get_json()


def pado(path: str, payload: dict) -> tuple[dict | None, str | None]:
    try:
        r = requests.post(f"{PADO}{path}", json=payload, timeout=60)
        r.raise_for_status()
        return r.json(), None
    except requests.RequestException as e:
        return None, f"파도풀({PADO})에 연결하지 못했습니다 — 서비스가 떠 있나요? ({e.__class__.__name__})"


def _author(user_ref: str):
    a = db().execute("SELECT * FROM authors WHERE user_ref = ?", (user_ref,)).fetchone()
    if a is None:
        abort(404)
    return a


def _post_row(post_id: str):
    p = db().execute(
        "SELECT p.*, a.nickname, a.user_ref FROM posts p JOIN authors a ON a.author_id = p.author_id"
        " WHERE p.post_id = ?", (post_id,)).fetchone()
    if p is None:
        abort(404)
    photos = db().execute("SELECT idx, caption FROM photos WHERE post_id = ? ORDER BY idx", (post_id,)).fetchall()
    return p, photos


# ── 프로필 · 글 화면 덮어쓰기 ────────────────────────────────────────────────
def profile_ext(user_ref: str):
    a = _author(user_ref)
    posts = db().execute("SELECT * FROM posts WHERE author_id = ? ORDER BY created_at DESC", (a["author_id"],)).fetchall()
    return render_template("profile_ext.html", a=a, posts=posts)


def post_ext(post_id: str):
    p, photos = _post_row(post_id)
    return render_template("post_ext.html", p=p, photos=photos, flash=request.args.get("done"),
                           back=request.args.get("back"))


app.view_functions["profile"] = profile_ext
app.view_functions["post"] = post_ext


# ── 내 글 점검 — 파도풀 결과를 우리뜰 안에 그린다 ─────────────────────────────
@app.get("/u/<user_ref>/check")
def check(user_ref: str):
    a = _author(user_ref)
    export = export_json(user_ref)
    res, err = pado("/api/scan", export) if export else (None, "내보낼 글이 없습니다")
    key = f"chk:{user_ref}"
    prev = session.get(key)
    delta = None
    # «조치 직후» 에만 변화 배너 — 시딩을 되돌린 뒤 옛 k 가 쿠키에 남아 있어도 배너가 뜨지 않게 (투어 6단계 오작동)
    acted = session.pop("acted", False)
    if res:
        if acted and prev and prev.get("k") != res["k"]:
            now = {s["condition"] for s in res["steps"]}
            delta = {"k": prev["k"], "risk": prev["risk"], "cut": [c for c in prev.get("steps", []) if c not in now]}
        session[key] = {"k": res["k"], "risk": res["risk"],
                        "steps": [s["condition"] for s in res["steps"] if s["axis"] != "sex"]}
    return render_template("check.html", a=a, res=res, err=err, delta=delta, back=f"/u/{user_ref}/check")


@app.get("/u/<user_ref>/check.json")
def check_json(user_ref: str):
    """레일 위젯용 요약 — 프로필·글 화면이 비동기로 부른다. 파도풀 응답에서 숫자만 추린다."""
    from flask import jsonify
    _author(user_ref)
    export = export_json(user_ref)
    res, err = pado("/api/scan", export) if export else (None, "내보낼 글이 없습니다")
    if not res:
        return jsonify({"error": err}), 502
    return jsonify({"k": res["k"], "risk": res["risk"], "label": res["label"], "css": res["css"],
                    "k_level": res["k_level"], "n_posts": res["n_posts"], "n_direct": res["n_direct"],
                    "n_leaking": len(res["leaking"]), "nation": res["steps"][0]["n_after"],
                    "n_actions": len(res["actions"]), "projected_k": res["projected_k"]})


# ── 에디터 점검 — 올리기 전 1회 ──────────────────────────────────────────────
def _editor_authors():
    """글쓰기 드롭다운 — 체험 계정(글 0편)이 맨 앞. 나머지는 공개 글 수를 붙여 «이미 드러난 계정» 임을 알고 고르게."""
    rows = db().execute(
        "SELECT a.*, (SELECT COUNT(*) FROM posts p WHERE p.author_id = a.author_id AND p.visibility='public') n_posts"
        " FROM authors a ORDER BY (a.author_id != 'GUEST'), a.nickname").fetchall()
    return rows


def new_ext():
    return render_template("new_ext.html", authors=_editor_authors(), now=datetime.now(KST).strftime("%Y-%m-%dT%H:%M"),
                           draft=None, check=None, err=None)


app.view_functions["new"] = new_ext


@app.post("/check-draft")
def check_draft():
    f = request.form
    authors = _editor_authors()
    a = db().execute("SELECT * FROM authors WHERE author_id = ?", (f["author_id"],)).fetchone()
    if a is None:
        abort(400)
    draft = {"author_id": f["author_id"], "title": f.get("title") or "", "body": f.get("body") or "",
             "geo_tag": f.get("geo_tag") or "", "captions": f.get("captions") or "", "created_at": f.get("created_at") or ""}
    export = export_json(a["user_ref"]) or {"schema_version": "1.0", "user_ref": a["user_ref"], "nickname": a["nickname"],
                                             "profile_bio": a["bio"], "posts": []}
    payload = {"export": export, "draft": {
        "title": draft["title"] or None, "body": draft["body"],
        "photos": [{"caption": c.strip()} for c in draft["captions"].splitlines() if c.strip()],
        "activity_meta": {"geo_tag": draft["geo_tag"] or None}}}
    res, err = pado("/api/check", payload)
    return render_template("new_ext.html", authors=authors, now=draft["created_at"] or datetime.now(KST).strftime("%Y-%m-%dT%H:%M"),
                           draft=draft, check=res, err=err, author=a)


@app.post("/check-draft.json")
def check_draft_json():
    """같은 초안을 «다른 작성자» 로 점검했을 때의 숫자만 — 에디터의 「작성자별로 비교」 가 부른다.
    같은 글이라도 이미 올린 글이 다르면 결과가 다르다는 것을 보여주는 용도 (9/10 피드백)."""
    from flask import jsonify
    f = request.get_json(silent=True) or {}
    a = db().execute("SELECT * FROM authors WHERE author_id = ?", (f.get("author_id"),)).fetchone()
    if a is None:
        abort(400)
    export = export_json(a["user_ref"]) or {"schema_version": "1.0", "user_ref": a["user_ref"], "nickname": a["nickname"],
                                             "profile_bio": a["bio"], "posts": []}
    payload = {"export": export, "draft": {
        "title": f.get("title") or None, "body": f.get("body") or "",
        "photos": [{"caption": c.strip()} for c in (f.get("captions") or "").splitlines() if c.strip()],
        "activity_meta": {"geo_tag": f.get("geo_tag") or None}}}
    res, err = pado("/api/check", payload)
    if not res:
        return jsonify({"error": err}), 502
    b, af = res["before"], res["after"]
    return jsonify({"author_id": a["author_id"], "nickname": a["nickname"], "n_posts": b["n_posts"],
                    "before_k": b["k"], "after_k": af["k"], "label": af["label"], "css": af["css"],
                    "n_spans": res["draft"]["n_spans"]})


# ── 처음부터 — 투어만이 아니라 글 데이터도 시딩 값으로 되돌린다 (9/10 피드백) ────────
@app.post("/demo/reset")
def demo_reset():
    """위치태그 끄기·비공개·본문 수정·새 글을 전부 되돌린다. seed.py 와 같은 코드를 같은 프로세스에서 돌린다."""
    import seed as seeder   # apps/demo/seed.py — HERE 가 sys.path 에 있다
    c = db()
    c.executescript("DELETE FROM photos; DELETE FROM posts; DELETE FROM authors;")
    c.commit()
    seeder.seed(c, seeder.DEFAULT_PERSONAS)
    session.clear()          # 지난 점검 k(delta 배너) 도 지운다
    return redirect("/")


# ── 로그인·회원가입 — 형식만 있는 화면. 실제 인증은 없다 (9/10 피드백: 있어 보이면 좋겠다) ──
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        return redirect("/")
    return render_template("login.html", mode="login")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        return redirect("/")
    return render_template("login.html", mode="signup")


# ── 조치 ②③ — 플랫폼에서 실행한다 ──────────────────────────────────────────
@app.post("/posts/<post_id>/geo_tag")
def clear_geo_tag(post_id: str):
    _post_row(post_id)
    db().execute("UPDATE posts SET geo_tag = NULL WHERE post_id = ?", (post_id,))
    db().commit()
    back = request.form.get("back")
    return redirect(back if back else f"/posts/{post_id}?done=geo")


@app.route("/posts/<post_id>/edit", methods=["GET", "POST"])
def edit_post(post_id: str):
    """수정 화면. POST 로 오면(파도풀 제안) 그 값을 채워서 보여주기만 하고 저장은 안 한다."""
    p, photos = _post_row(post_id)
    proposal = None
    if request.method == "POST":
        proposal = {"body": request.form.get("body"), "title": request.form.get("title"),
                    "captions": {int(k[7:]): v for k, v in request.form.items() if k.startswith("caption")},
                    "note": request.form.get("note", ""), "source": request.form.get("from", "")}
    return render_template("edit_post.html", p=p, photos=photos, proposal=proposal,
                           back=request.form.get("back") or request.args.get("back"))


@app.post("/posts/<post_id>/body")
def save_body(post_id: str):
    p, photos = _post_row(post_id)
    f = request.form
    db().execute("UPDATE posts SET title = ?, body = ? WHERE post_id = ?", (f.get("title") or None, f["body"], post_id))
    for ph in photos:
        key = f"caption{ph['idx']}"
        if key in f:
            db().execute("UPDATE photos SET caption = ? WHERE post_id = ? AND idx = ?", (f[key], post_id, ph["idx"]))
    db().commit()
    back = f.get("back")
    return redirect(back if back else f"/posts/{post_id}?done=edit")


if __name__ == "__main__":
    # `with` 는 sqlite 연결을 닫지 않는다(커밋만). 열어 두면 Windows 에서 seed --reset 이 파일을 못 지운다
    c = sns.connect()
    sns.init(c)
    c.close()
    app.run(port=int(os.getenv("SNS_PORT", "3000")), debug=os.getenv("DEMO_DEBUG") == "1")
