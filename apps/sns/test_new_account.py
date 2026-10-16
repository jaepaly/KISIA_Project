"""새 빈 계정 — 가상 인물 대신 「내 글」로 시험하기. 그 방문자의 체험용 사본에만 생기고, 만들자마자 내 계정이 된다."""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_sessions import app_iso  # noqa: F401  — 같은 격리 준비(시드 사본 · 세션 사본)를 쓴다

FETCH = {"X-Requested-With": "fetch"}


def _new(client, name=""):
    return client.post("/me/new", data={"nickname": name}, headers=FETCH)


def test_new_account_is_empty_mine_and_listed_first(app_iso):  # noqa: F811
    app, root = app_iso
    a = app.test_client()
    a.get("/?skip_about=1")
    r = _new(a, "  내   블로그  ")
    assert r.status_code == 200
    me = r.get_json()["me"]
    assert re.fullmatch(r"M[0-9a-f]{8}", me["author_id"]) and re.fullmatch(r"u_[0-9a-f]{12}", me["user_ref"])
    assert me["nickname"] == "내 블로그"                     # 공백은 하나로
    # 글쓰기 화면 — 맨 위 · 내 계정 · 「내가 만든 계정」 표시
    html = a.get("/new").get_data(as_text=True)
    first = re.search(r'<option value="([^"]+)"', html).group(1)
    assert first == me["author_id"] and "내 블로그 (내 계정) · 내가 만든 계정" in html
    # 오른쪽 패널 — 정답지 없음 · 글 0편
    s = a.get(f"/api/author/{me['author_id']}/summary").get_json()
    assert s["is_new"] is True and s["persona"] is None and s["n_posts"] == 0
    # 글을 올리면 그 계정의 공개 글로 내보낸다(분석기 창구 그대로)
    r = a.post("/posts", data={"author_id": me["author_id"], "title": "첫 글", "body": "오늘 처음 써 봐요",
                               "created_at": "2026-10-16T09:00", "visibility": "public"})
    assert r.status_code in (302, 303)
    sid = a.get_cookie("veilo_sid").value
    ex = a.get(f"/api/export/{me['user_ref']}", headers={"X-Veilo-Session": sid}).get_json()
    assert [p["body"] for p in ex["posts"]] == ["오늘 처음 써 봐요"]


def test_new_account_stays_in_this_visitors_copy(app_iso):  # noqa: F811
    app, root = app_iso
    a, b = app.test_client(), app.test_client()
    a.get("/?skip_about=1"); b.get("/?skip_about=1")
    me = _new(a, "비밀 계정").get_json()["me"]
    assert "비밀 계정" not in b.get("/new").get_data(as_text=True)                # 다른 방문자에게 안 보인다
    assert b.get(f"/api/author/{me['author_id']}/summary").status_code == 404
    live = sqlite3.connect(root / "sns.db")
    assert live.execute("SELECT COUNT(*) FROM authors WHERE author_id LIKE 'M%'").fetchone()[0] == 0   # 공용 DB 그대로
    live.close()


def test_default_name_limit_and_long_name(app_iso):  # noqa: F811
    app, _ = app_iso
    a = app.test_client()
    a.get("/?skip_about=1")
    me = _new(a).get_json()["me"]
    assert me["nickname"] == f"새 계정 {me['author_id'][1:5]}"
    assert _new(a, "가" * 21).status_code == 413                                 # 이름 20자까지
    for _ in range(4):
        assert _new(a).status_code == 200
    r = _new(a)                                                                   # 5개까지
    assert r.status_code == 429 and "5개까지" in r.get_data(as_text=True)


def test_new_account_rejects_other_origin(app_iso):  # noqa: F811
    app, _ = app_iso
    a = app.test_client()
    a.get("/?skip_about=1")
    assert a.post("/me/new", headers={**FETCH, "Origin": "http://evil.example"}).status_code == 403


def test_reset_new_account_empties_posts(app_iso):  # noqa: F811
    """새 계정의 「계정 초기화」 — 시드에 없으니 글 · 조치 이력만 비우고 계정은 둔다 (Codex P2 · 전엔 500)."""
    app, _ = app_iso
    a = app.test_client()
    a.get("/?skip_about=1")
    me = _new(a, "초기화 시험").get_json()["me"]
    a.post("/posts", data={"author_id": me["author_id"], "body": "지울 글", "created_at": "2026-10-16T09:00",
                           "visibility": "public"})
    assert a.get(f"/api/author/{me['author_id']}/summary").get_json()["n_posts"] == 1
    r = a.post(f"/u/{me['user_ref']}/reset")
    assert r.status_code in (302, 303)
    s = a.get(f"/api/author/{me['author_id']}/summary").get_json()
    assert s["n_posts"] == 0 and s["nickname"] == "초기화 시험"


def test_new_account_refused_without_isolation(tmp_path, monkeypatch):
    """체험용 사본이 꺼진 환경(시드 사본 없음)에서는 공용 DB 에 남으니 만들지 않고, 화면에도 안 보인다 (Codex P1)."""
    from test_sessions import _seed
    live = tmp_path / "sns.db"
    _seed(live)
    monkeypatch.setenv("SNS_DB_PATH", str(live))
    monkeypatch.delenv("SNS_SEED_DB", raising=False)
    import app as appmod
    appmod.app.config["TESTING"] = True
    a = appmod.app.test_client()
    assert 'id="newAcct"' not in a.get("/new").get_data(as_text=True)
    assert _new(a).status_code == 409
    c = sqlite3.connect(live)
    assert c.execute("SELECT COUNT(*) FROM authors WHERE author_id LIKE 'M%'").fetchone()[0] == 0
    c.close()


def test_concurrent_creates_do_not_pass_limit(app_iso):  # noqa: F811
    """동시에 눌러도 상한(5개)을 넘지 않는다 — 세기 · 넣기가 한 쓰기 트랜잭션 (Codex P2)."""
    import threading
    app, _ = app_iso
    a = app.test_client()
    a.get("/?skip_about=1")
    for _ in range(3):
        assert _new(a).status_code == 200
    sid = a.get_cookie("veilo_sid").value
    codes = []

    def hit():
        c = app.test_client()
        c.set_cookie("veilo_sid", sid)
        codes.append(_new(c).status_code)
    ts = [threading.Thread(target=hit) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    html = a.get("/new").get_data(as_text=True)
    assert html.count("· 내가 만든 계정</option>") == 5 and codes.count(200) == 2, codes
