"""우리뜰 확장 실행기 — `apps/sns` 를 **고치지 않고** 조치 버튼 2개를 덧씌워 띄운다.

    python apps/demo/sns_ext.py            # http://localhost:3000 (SNS_PORT)

apps/sns/app.py 는 E 소유라 손대지 않는다. 대신 그 Flask 앱을 import 해서
  - GET  /posts/<id>            글 화면을 덮어쓴다 (조치 버튼이 있는 템플릿)
  - POST /posts/<id>/geo_tag    위치태그 지우기        ← 조치 ②
  - GET/POST /posts/<id>/edit   본문·캡션 수정 화면     ← 조치 ③ (파도풀이 제안을 채워 보낸다)
  - POST /posts/<id>/body       저장
를 더한다. 비공개 토글(조치 ①)과 /api/export 는 원본 그대로다.

E 의 W4~W6 «메타 관리» 화면이 나오면 이 파일과 templates/sns_ext/ 는 지운다.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNS = HERE.parent / "sns"
sys.path.insert(0, str(SNS))          # apps/sns/app.py 가 `from db import ...` 를 쓴다

import jinja2  # noqa: E402
from flask import abort, redirect, render_template, request  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sns = _load("sns_app", SNS / "app.py")
app, db = sns.app, sns.db
app.jinja_loader = jinja2.ChoiceLoader([
    jinja2.FileSystemLoader(str(HERE / "templates" / "sns_ext")),
    app.jinja_loader,
])


def _post_row(post_id: str):
    p = db().execute(
        "SELECT p.*, a.nickname, a.user_ref FROM posts p JOIN authors a ON a.author_id = p.author_id"
        " WHERE p.post_id = ?", (post_id,)).fetchone()
    if p is None:
        abort(404)
    photos = db().execute("SELECT idx, caption FROM photos WHERE post_id = ? ORDER BY idx", (post_id,)).fetchall()
    return p, photos


def post_ext(post_id: str):
    p, photos = _post_row(post_id)
    return render_template("post_ext.html", p=p, photos=photos, flash=request.args.get("done"))


app.view_functions["post"] = post_ext   # 기존 라우트 규칙은 그대로, 뷰 함수만 교체


@app.post("/posts/<post_id>/geo_tag")
def clear_geo_tag(post_id: str):
    """조치 ② — 사용자가 플랫폼에서 누른다. 파도풀은 «끄라» 고만 했다."""
    _post_row(post_id)
    db().execute("UPDATE posts SET geo_tag = NULL WHERE post_id = ?", (post_id,))
    db().commit()
    return redirect(f"/posts/{post_id}?done=geo")


@app.route("/posts/<post_id>/edit", methods=["GET", "POST"])
def edit_post(post_id: str):
    """조치 ③ — 수정 화면. POST 로 오면(파도풀 제안) 그 값을 채워서 보여주기만 하고 저장은 안 한다."""
    p, photos = _post_row(post_id)
    proposal = None
    if request.method == "POST":
        proposal = {"body": request.form.get("body"), "title": request.form.get("title"),
                    "captions": {int(k[7:]): v for k, v in request.form.items() if k.startswith("caption")},
                    "note": request.form.get("note", ""), "source": request.form.get("from", "")}
    return render_template("edit_post.html", p=p, photos=photos, proposal=proposal)


@app.post("/posts/<post_id>/body")
def save_body(post_id: str):
    p, photos = _post_row(post_id)
    f = request.form
    db().execute("UPDATE posts SET title = ?, body = ? WHERE post_id = ?",
                 (f.get("title") or None, f["body"], post_id))
    for ph in photos:
        key = f"caption{ph['idx']}"
        if key in f:
            db().execute("UPDATE photos SET caption = ? WHERE post_id = ? AND idx = ?", (f[key], post_id, ph["idx"]))
    db().commit()
    return redirect(f"/posts/{post_id}?done=edit")


if __name__ == "__main__":
    # `with` 는 sqlite 연결을 닫지 않는다(커밋만). 열어 두면 Windows 에서 seed --reset 이 파일을 못 지운다
    c = sns.connect()
    sns.init(c)
    c.close()
    app.run(port=int(os.getenv("SNS_PORT", "3000")), debug=os.getenv("DEMO_DEBUG") == "1")
