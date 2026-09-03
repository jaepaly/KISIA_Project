"""우리뜰 실행기 — `apps/sns` 를 **고치지 않고** 파도풀을 붙인 플랫폼으로 띄운다.

    python apps/demo/sns_ext.py            # http://localhost:3000 (SNS_PORT)
    PADOPOOL_URL=http://localhost:8000     # 파도풀 API. 우리뜰이 이 서비스를 «붙여 쓴다»

논지: 파도풀은 플랫폼에 붙는 서비스다. 우리뜰이 네이버·인스타 자리이고, 다른 SNS 도 같은 방식으로 붙일 수 있다.
경계는 그대로다 — 우리뜰이 파도풀에 보내는 것은 `/api/export` 와 같은 형식뿐이고, 파도풀은 저장하지 않는다.
조치 실행(비공개·태그·본문 수정)은 전부 우리뜰 라우트다. 파도풀은 권고만 한다.

apps/sns/app.py 는 E 소유라 손대지 않는다. 그 Flask 앱을 import 해서
  - GET  /u/<user_ref>/check    「내 글 점검」 — 파도풀 /api/scan 결과를 우리뜰 화면에 그린다. 조치 버튼도 여기
  - GET  /new  · POST /check-draft   글쓰기 에디터에 「🛟 점검」 — 올리기 전 1회 [MF-015]
  - GET  /u/<user_ref>  · /posts/<id>   프로필·글 화면 덮어쓰기 (진입 버튼 · 태그 지우기 · 본문 고치기)
  - POST /posts/<id>/geo_tag · /edit · /body   조치 ②③
를 더한다. 비공개 토글(조치 ①)과 /api/export 는 원본 그대로다.

E 의 W4~W6 «메타 관리» · W9 «에디터 경고» 가 나오면 이 파일과 templates/sns_ext/ 는 지운다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNS = HERE.parent / "sns"
sys.path.insert(0, str(SNS))          # apps/sns/app.py 가 `from db import ...` 를 쓴다

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


def ut_engage(post_id: str) -> dict:
    n = _seed(post_id, "eng")
    return {"likes": 3 + n % 38, "comments": (n >> 8) % 6, "views": 60 + (n >> 12) % 900}


def ut_comments(post_id: str) -> list[dict]:
    out = []
    for i in range(ut_engage(post_id)["comments"]):
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

    우리뜰에는 로그인이 없다. 데모에서는 «보고 있는 블로그의 주인» 을 내 계정처럼 다룬다.
    """
    me = None
    va = (request.view_args or {})
    if va.get("user_ref"):
        me = db().execute("SELECT * FROM authors WHERE user_ref = ?", (va["user_ref"],)).fetchone()
    elif va.get("post_id"):
        me = db().execute("SELECT a.* FROM authors a JOIN posts p ON p.author_id = a.author_id"
                          " WHERE p.post_id = ?", (va["post_id"],)).fetchone()
    if me is None:
        first = os.getenv("DEMO_PERSONAS", "D05").split(",")[0].strip()
        me = (db().execute("SELECT * FROM authors WHERE author_id = ?", (first,)).fetchone()
              or db().execute("SELECT * FROM authors ORDER BY author_id LIMIT 1").fetchone())
    nav = {"index": "home", "profile": "blog", "check": "check", "new": "new"}.get(request.endpoint or "")
    return {"me": me, "nav": nav}


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
    if res:
        if prev and prev.get("k") != res["k"]:
            now = {s["condition"] for s in res["steps"]}
            delta = {"k": prev["k"], "risk": prev["risk"], "cut": [c for c in prev.get("steps", []) if c not in now]}
        session[key] = {"k": res["k"], "risk": res["risk"],
                        "steps": [s["condition"] for s in res["steps"] if s["axis"] != "sex"]}
    return render_template("check.html", a=a, res=res, err=err, delta=delta, back=f"/u/{user_ref}/check")


# ── 에디터 점검 — 올리기 전 1회 ──────────────────────────────────────────────
def new_ext():
    authors = db().execute("SELECT * FROM authors ORDER BY nickname").fetchall()
    return render_template("new_ext.html", authors=authors, now=datetime.now(KST).strftime("%Y-%m-%dT%H:%M"),
                           draft=None, check=None, err=None)


app.view_functions["new"] = new_ext


@app.post("/check-draft")
def check_draft():
    f = request.form
    authors = db().execute("SELECT * FROM authors ORDER BY nickname").fetchall()
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
                           draft=draft, check=res, err=err)


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
