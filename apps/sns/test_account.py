"""내 계정 · 조치 이력 · 되돌리기 — 세션 사본의 me · action_log 표.

    python -m pytest -q apps/sns/test_account.py

되돌리면 /api/export 가 조치 전과 같아야 한다 (재점검하면 숫자가 돌아온다).
이력 자체는 export 에 나가지 않는다 — export 계약은 test_export.py 가 지킨다.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

REF = "u_0123456789ab"


def _seed(path: Path, *, visitor_tables: bool = True) -> None:
    """visitor_tables=False 면 me · action_log 가 생기기 전의 옛 스키마로 만든다."""
    import db as dbmod
    c = sqlite3.connect(path)
    sql = (Path(dbmod.__file__).parent / "schema.sql").read_text(encoding="utf-8")
    if not visitor_tables:
        sql = sql[:sql.index(dbmod._VISITOR_MARK)]
    c.executescript(sql)
    c.execute("INSERT INTO authors(author_id,user_ref,nickname,bio,joined_at) VALUES ('S01',?,'시드닉','소개','2024-01-01')", (REF,))
    c.execute("INSERT INTO authors(author_id,user_ref,nickname,bio,joined_at) VALUES ('S02','u_aaaaaaaaaaaa','둘째','','2024-01-01')")
    c.executemany("INSERT INTO posts(post_id,author_id,title,body,created_at,geo_tag,visibility,source) VALUES (?,?,?,?,?,?,?,'seed')", [
        ("S01_b01", "S01", "첫 글", "성수동 출근길", "2026-01-01T10:00:00+09:00", "성동구 성수동", "public"),
        ("S01_b02", "S01", "둘째 글", "점심 먹음", "2026-01-02T12:00:00+09:00", None, "public"),
    ])
    c.execute("INSERT INTO photos(post_id,idx,caption) VALUES ('S01_b01',0,'골목')")
    c.commit()
    c.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    _seed(tmp_path / "sns.db")
    _seed(tmp_path / "sns.seed.db", visitor_tables=False)   # 운영 시드 사본엔 새 표가 없다
    monkeypatch.setenv("SNS_DB_PATH", str(tmp_path / "sns.db"))
    monkeypatch.delenv("SNS_SEED_DB", raising=False)
    monkeypatch.delenv("SNS_SESSION_DIR", raising=False)
    import app as appmod
    appmod.app.config["TESTING"] = True
    return appmod.app, tmp_path


def _sid(client) -> str:
    return client.get("/").headers["Set-Cookie"].split("veilo_sid=")[1].split(";")[0]


def _export(app, sid):
    return app.test_client().get(f"/api/export/{REF}", headers={"X-Veilo-Session": sid}).get_json()


def test_pick_me_is_saved_per_session(env):
    app, _ = env
    a = app.test_client()
    _sid(a)
    assert "내 계정 시드닉" not in a.get("/").get_data(as_text=True)   # 고르기 전엔 아바타 없음 — 그래도 화면은 뜬다
    r = a.post("/me", data={"author_id": "S01", "back": f"/u/{REF}"})
    assert r.status_code == 302 and "done=me" in r.headers["Location"]
    home = a.get("/").get_data(as_text=True)
    assert "내 계정 시드닉" in home and f"scan.html?u={REF}" in home   # 상단바 아바타 · 내 글 점검이 나로
    assert 'value="S01" selected' in a.get("/new").get_data(as_text=True)   # 글쓰기 기본 작성자
    # 다른 방문자에겐 없다
    assert "내 계정 시드닉" not in app.test_client().get("/").get_data(as_text=True)
    # fetch 로 바꾸기 (글쓰기 화면) · 풀기
    j = a.post("/me", data={"author_id": "S02"}, headers={"X-Requested-With": "fetch"}).get_json()
    assert j["me"]["nickname"] == "둘째"
    a.post("/me", data={"author_id": ""})
    assert "내 계정 둘째" not in a.get("/").get_data(as_text=True)
    assert a.post("/me", data={"author_id": "NOPE"}).status_code == 404


def test_old_session_db_is_migrated(env):
    """새 표가 생기기 전에 만든 세션 사본 — 열면 표가 생기고 내 계정·이력이 그대로 동작한다."""
    app, root = env
    sid = "0123456789abcdef01234567"
    (root / "sessions").mkdir()
    old = root / "sessions" / f"{sid}.db"
    _seed(old, visitor_tables=False)
    c = app.test_client()
    c.set_cookie(key="veilo_sid", value=sid)
    assert c.get(f"/u/{REF}").status_code == 200
    c.post("/me", data={"author_id": "S01"})
    c.post("/posts/S01_b01/visibility", data={"back": f"/u/{REF}"})
    con = sqlite3.connect(old)
    assert con.execute("SELECT author_id FROM me").fetchone()[0] == "S01"
    assert con.execute("SELECT kind FROM action_log").fetchall() == [("private",)]


def test_log_and_undo_restore_export(env):
    app, _ = env
    a = app.test_client()
    sid = _sid(a)
    before = _export(app, sid)

    a.post("/posts/S01_b01/visibility", data={"back": f"/u/{REF}"})          # 비공개
    a.post("/posts/S01_b02/edit", data={"geo_tag": "성동구"})                 # 위치 태그
    a.post("/posts/S01_b02/edit", data={"geo_tag": "성동구"})                 # 같은 값 — 기록하지 않는다
    r = a.post("/posts", data={"author_id": "S01", "title": "첫 글", "body": "출근길",       # 고쳐 쓰기
                               "created_at": "2026-01-03T09:00", "from_post": "S01_b01"})
    new_id = r.headers["Location"].split("?")[0].rsplit("/", 1)[1]

    after = _export(app, sid)
    assert after != before
    page = a.get(f"/u/{REF}").get_data(as_text=True)
    assert "바꾼 것 3개" in page and "모두 되돌리기" in page
    assert "action_log" not in str(after) and "undone" not in str(after)   # 이력은 export 에 섞이지 않는다

    # 항목별 되돌리기 — 위치 태그만
    ids = _log_ids(app, sid)
    a.post(f"/changes/{ids['geo']}/undo", data={"back": f"/u/{REF}"})
    assert [p["activity_meta"]["geo_tag"] for p in _export(app, sid)["posts"] if p["post_id"] == "S01_b02"] == [None]
    assert "바꾼 것 2개" in a.get(f"/u/{REF}").get_data(as_text=True)

    # 모두 되돌리기 — 비공개와 고쳐 쓴 새 글까지
    r = a.post("/changes/undo-all", data={"author_id": "S01", "back": f"/u/{REF}"})
    assert "done=undo" in r.headers["Location"]
    assert _export(app, sid) == before
    assert a.get(f"/posts/{new_id}").status_code == 404
    assert "모두 되돌리기" not in a.get(f"/u/{REF}").get_data(as_text=True)


def test_undo_one_toggle_closes_later_toggles(env):
    """비공개 → 공개 → 비공개 뒤 첫 조치를 되돌리면 처음 값(공개)으로, 뒤의 둘도 같이 닫힌다."""
    app, _ = env
    a = app.test_client()
    sid = _sid(a)
    before = _export(app, sid)
    for _ in range(3):
        a.post("/posts/S01_b01/visibility", data={"back": f"/u/{REF}"})
    first = min(_log_ids(app, sid, all_ids=True))
    a.post(f"/changes/{first}/undo", data={"back": f"/u/{REF}"})
    assert _export(app, sid) == before
    assert _log_ids(app, sid) == {}


def test_reset_closes_history(env):
    app, _ = env
    a = app.test_client()
    sid = _sid(a)
    a.post("/posts/S01_b01/visibility", data={"back": f"/u/{REF}"})
    a.post(f"/u/{REF}/reset")
    assert _log_ids(app, sid) == {}
    assert "모두 되돌리기" not in a.get(f"/u/{REF}").get_data(as_text=True)


def _log_ids(app, sid, all_ids=False):
    import app as appmod
    p = appmod._session_dir() / f"{sid}.db"
    con = sqlite3.connect(p)
    rows = con.execute("SELECT id, kind FROM action_log" + ("" if all_ids else " WHERE undone_at IS NULL")).fetchall()
    con.close()
    return [r[0] for r in rows] if all_ids else {k: i for i, k in rows}


# ── 위험 배지 · /api/me · 고쳐 쓰기 짝 (3차) ──

def _rewrite(a, src, title="고친 글"):
    r = a.post("/posts", data={"author_id": "S01", "title": title, "body": "출근길",
                               "created_at": "2026-01-03T09:00", "from_post": src})
    return r.headers["Location"].split("?")[0].rsplit("/", 1)[1]


def _visibility(app, sid, post_id):
    con = sqlite3.connect(_session_db(sid))
    v = con.execute("SELECT visibility FROM posts WHERE post_id = ?", (post_id,)).fetchone()
    con.close()
    return v[0] if v else None


def test_rewrite_undo_also_reopens_original(env):
    """고쳐 쓴 글 화면의 「원래 글 비공개로」(pair)는 한 묶음 — 고쳐 쓰기를 되돌리면 원래 글도 다시 공개된다."""
    app, _ = env
    a = app.test_client()
    sid = _sid(a)
    before = _export(app, sid)
    new_id = _rewrite(a, "S01_b01")
    page = a.get(f"/posts/{new_id}?done=posted").get_data(as_text=True)
    assert "아직 공개입니다" in page and "원래 글 비공개로" in page        # N2 안내
    rid = _log_ids(app, sid)["rewrite"]
    assert f'name="pair" value="{rid}"' in page
    a.post("/posts/S01_b01/visibility", data={"back": f"/posts/{new_id}", "pair": rid})
    assert "아직 공개입니다" not in a.get(f"/posts/{new_id}").get_data(as_text=True)
    page = a.get(f"/u/{REF}").get_data(as_text=True)
    assert page.count("고쳐 쓰기와 한 묶음") == 2
    a.post(f"/changes/{rid}/undo", data={"back": f"/u/{REF}"})
    assert _export(app, sid) == before and _log_ids(app, sid) == {}


def test_rewrite_undo_keeps_separate_private(env):
    """S1 회귀 — 고쳐 쓰기 전에 따로 한 비공개(토글 여러 번 포함)는 고쳐 쓰기를 되돌려도 그대로다."""
    app, _ = env
    a = app.test_client()
    sid = _sid(a)
    for _ in range(3):                                   # 비공개 → 공개 → 비공개 (따로 한 조치)
        a.post("/posts/S01_b01/visibility", data={"back": "/"})
    assert _visibility(app, sid, "S01_b01") == "private"
    mid = _export(app, sid)
    new_id = _rewrite(a, "S01_b01")                      # 이미 비공개인 글을 옮겨 고쳐 씀
    assert "아직 공개입니다" not in a.get(f"/posts/{new_id}").get_data(as_text=True)
    page = a.get(f"/u/{REF}").get_data(as_text=True)
    assert "고쳐 쓰기와 한 묶음" not in page            # 시간·글만 같다고 짝으로 보이지 않는다
    a.post(f"/changes/{_log_ids(app, sid)['rewrite']}/undo", data={"back": "/"})
    assert _visibility(app, sid, "S01_b01") == "private"  # 앞서 한 비공개는 그대로
    assert _export(app, sid) == mid
    assert sorted(_log_ids(app, sid, all_ids=True)) and "private" in _log_ids(app, sid)
    # 묶음 표시 없이 나중에 따로 누른 비공개도 묶이지 않는다 (pair 없이)
    a.post("/posts/S01_b02/visibility", data={"back": "/", "pair": 99999})
    assert "고쳐 쓰기와 한 묶음" not in a.get(f"/u/{REF}").get_data(as_text=True)


def test_rewrite_chain_undo_first(env):
    """B1 회귀 — A→B→C 에서 A→B 를 되돌리면 B→C 도 함께 되돌려 C 가 이력 없이 남지 않는다."""
    app, _ = env
    a = app.test_client()
    sid = _sid(a)
    before = _export(app, sid)
    b = _rewrite(a, "S01_b01", "B")
    c = _rewrite(a, b, "C")
    page = a.get(f"/u/{REF}").get_data(as_text=True)
    assert "다시 고쳐 쓴 글과 이어짐" in page
    first = min(_log_ids(app, sid, all_ids=True))
    a.post(f"/changes/{first}/undo", data={"back": "/"})
    assert a.get(f"/posts/{b}").status_code == 404 and a.get(f"/posts/{c}").status_code == 404
    assert _export(app, sid) == before and _log_ids(app, sid) == {}


def test_rewrite_chain_undo_all(env):
    app, _ = env
    a = app.test_client()
    sid = _sid(a)
    before = _export(app, sid)
    b = _rewrite(a, "S01_b01", "B")
    rid = _log_ids(app, sid)["rewrite"]
    a.post("/posts/S01_b01/visibility", data={"back": "/", "pair": rid})
    _rewrite(a, b, "C")
    a.post("/changes/undo-all", data={"author_id": "S01", "back": "/"})
    assert _export(app, sid) == before and _log_ids(app, sid) == {}


def test_old_action_log_gets_group_column(env):
    """group_id 칸이 생기기 전에 만든 action_log — 열 때 칸만 더한다."""
    app, root = env
    sid = "fedcba9876543210fedcba98"
    (root / "sessions").mkdir(exist_ok=True)
    old = root / "sessions" / f"{sid}.db"
    _seed(old, visitor_tables=False)
    con = sqlite3.connect(old)
    con.execute("CREATE TABLE action_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL,"
                " author_id TEXT NOT NULL, post_id TEXT NOT NULL, before_val TEXT, after_val TEXT,"
                " new_post_id TEXT, undone_at TEXT)")
    con.commit(); con.close()
    c = app.test_client()
    c.set_cookie(key="veilo_sid", value=sid)
    c.post("/posts/S01_b01/visibility", data={"back": "/"})
    assert sqlite3.connect(old).execute("SELECT kind, group_id FROM action_log").fetchall() == [("private", None)]


def test_api_me(env):
    app, _ = env
    a = app.test_client()
    _sid(a)
    assert a.get("/api/me").get_json() == {"me": None}
    a.post("/me", data={"author_id": "S01"})
    a.post("/posts/S01_b01/visibility", data={"back": "/"})
    me = a.get("/api/me").get_json()["me"]
    assert me["user_ref"] == REF and me["nickname"] == "시드닉" and me["changes"] == 1
    assert "author_id" not in me                     # 플랫폼 내부 값은 내보내지 않는다
    assert app.test_client().get("/api/me").get_json() == {"me": None}   # 쿠키 없는 다른 방문자


def test_api_me_cors_only_for_pado_origin(env, monkeypatch):
    app, _ = env
    import app as appmod
    monkeypatch.setattr(appmod, "PADO_BASE", "http://localhost:8000")
    c = app.test_client()
    ok = c.get("/api/me", headers={"Origin": "http://localhost:8000"})
    assert ok.headers.get("Access-Control-Allow-Origin") == "http://localhost:8000"
    assert ok.headers.get("Access-Control-Allow-Credentials") == "true"
    bad = c.get("/api/me", headers={"Origin": "http://evil.example"})
    assert "Access-Control-Allow-Origin" not in bad.headers


def test_clue_badge_cache_and_invalidation(env):
    app, _ = env
    a = app.test_client()
    sid = _sid(a)
    # 내 계정이 없으면 배지도 빈 자리도 없다 (점검을 부르지 않는다)
    page = a.get(f"/u/{REF}").get_data(as_text=True)
    assert "data-clue-need" not in page and "clues.js" not in page
    assert a.post("/api/clues/S01_b01", json={"n": 3}).status_code == 403

    a.post("/me", data={"author_id": "S01"})
    page = a.get(f"/u/{REF}").get_data(as_text=True)
    assert page.count("data-clue-need") == 2 and "clues.js" in page and "CLUE_PER_PAGE = 5" in page
    assert a.post("/api/clues/S01_b01", json={"n": 3}).status_code == 200
    assert a.post("/api/clues/S01_b02", json={"n": 0}).status_code == 200
    assert a.post("/api/clues/S01_b01", json={"n": "3"}).status_code == 400
    for path in (f"/u/{REF}", "/"):
        page = a.get(path).get_data(as_text=True)
        assert "📍 단서 3곳" in page and "/posts/S01_b01#pado" in page
        assert "단서 0곳" not in page                 # 0곳은 배지 없음 — 안전으로 읽히지 않게
        assert "data-clue-need" not in page           # 둘 다 저장됨 → 다시 세지 않는다

    # 본문이 바뀌면 저장된 값은 무효 — 다시 셀 자리로 돌아간다
    con = sqlite3.connect(Path(_session_db(sid)))
    con.execute("UPDATE posts SET body = '바뀐 본문' WHERE post_id = 'S01_b01'")
    con.commit(); con.close()
    page = a.get(f"/u/{REF}").get_data(as_text=True)
    assert "📍 단서 3곳" not in page and 'data-clue-need="S01_b01"' in page

    # 남의 글 · 비공개 글은 배지 대상이 아니다
    assert a.post("/api/clues/S02_x", json={"n": 1}).status_code == 403
    a.post("/posts/S01_b02/visibility", data={"back": "/"})
    assert 'data-clue-need="S01_b02"' not in a.get(f"/u/{REF}").get_data(as_text=True)


def _session_db(sid):
    import app as appmod
    return appmod._session_dir() / f"{sid}.db"
