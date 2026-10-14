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
    new_id = r.headers["Location"].rsplit("/", 1)[1]

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
