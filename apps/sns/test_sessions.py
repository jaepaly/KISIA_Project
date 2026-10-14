"""방문자별 격리 — 시드 사본이 있으면 쿠키마다 DB 사본을 쓴다. 한 사람의 수정이 남에게 보이지 않는다."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _seed(path: Path) -> None:
    import db as dbmod
    c = dbmod.connect(path)
    dbmod.init(c)
    c.execute("INSERT INTO authors(author_id,user_ref,nickname,bio,joined_at) VALUES ('S01','u_0123456789ab','시드닉','소개','2024-01-01')")
    c.execute("INSERT INTO posts(post_id,author_id,title,body,created_at,geo_tag,visibility,source)"
              " VALUES ('S01_b01','S01','제목','본문입니다','2026-01-01T10:00:00+09:00',NULL,'public','seed')")
    c.commit()
    c.close()


@pytest.fixture
def app_iso(tmp_path, monkeypatch):
    live = tmp_path / "sns.db"
    _seed(live)
    _seed(tmp_path / "sns.seed.db")
    monkeypatch.setenv("SNS_DB_PATH", str(live))
    monkeypatch.delenv("SNS_SEED_DB", raising=False)
    monkeypatch.delenv("SNS_SESSION_DIR", raising=False)
    import app as appmod
    appmod.app.config["TESTING"] = True
    return appmod.app, tmp_path


def _toggle(client, headers=None):
    return client.post("/posts/S01_b01/visibility", data={"back": "/u/u_0123456789ab"}, headers=headers or {})


def test_first_visit_sets_cookie_and_edits_do_not_leak(app_iso):
    app, root = app_iso
    a = app.test_client()
    r = a.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/about")   # 첫 접속은 소개로 — 세션 쿠키는 그때 이미 받는다
    cookie = r.headers.get("Set-Cookie", "")
    assert "veilo_sid=" in cookie and "HttpOnly" in cookie
    assert a.get("/?skip_about=1").status_code == 200   # 소개를 건너뛰고 홈 — 이때 이 방문자의 DB 사본이 생긴다
    assert (root / "sessions").exists()

    _toggle(a)   # 방문자 A 가 비공개로
    body_a = a.get("/u/u_0123456789ab").get_data(as_text=True)
    assert "🌐 공개로" in body_a and "🔒 비공개로" not in body_a   # A 에게는 지금 비공개 → 「공개로」 버튼

    b = app.test_client()   # 다른 브라우저
    body_b = b.get("/u/u_0123456789ab").get_data(as_text=True)
    assert "🔒 비공개로" in body_b and "🌐 공개로" not in body_b   # B 에게는 여전히 공개

    # 공용(라이브) DB 는 그대로
    live = sqlite3.connect(root / "sns.db")
    assert live.execute("SELECT visibility FROM posts WHERE post_id='S01_b01'").fetchone()[0] == "public"


def test_export_follows_session_header(app_iso):
    app, _ = app_iso
    a = app.test_client()
    sid = a.get("/").headers["Set-Cookie"].split("veilo_sid=")[1].split(";")[0]
    _toggle(a)
    # 분석기처럼 쿠키 없이 헤더로 — 그 사람의 사본을 읽는다 (비공개 글은 export 에서 빠진다)
    plain = app.test_client()
    with_sid = plain.get("/api/export/u_0123456789ab", headers={"X-Veilo-Session": sid}).get_json()
    without = plain.get("/api/export/u_0123456789ab").get_json()
    assert len(with_sid["posts"]) == 0 and len(without["posts"]) == 1
    # 주소의 ?sid= 로는 남의 사본에 들어가지 못한다 (#337 E 리뷰)
    via_query = plain.get(f"/api/export/u_0123456789ab?sid={sid}").get_json()
    assert len(via_query["posts"]) == 1


def test_reset_restores_only_this_session(app_iso):
    app, _ = app_iso
    a = app.test_client()
    a.get("/")
    _toggle(a)
    r = a.post("/u/u_0123456789ab/reset")
    assert r.status_code == 302
    assert "🔒 비공개로" in a.get("/u/u_0123456789ab").get_data(as_text=True)   # 다시 공개


def test_without_seed_isolation_is_off(tmp_path, monkeypatch):
    live = tmp_path / "sns.db"
    _seed(live)
    monkeypatch.setenv("SNS_DB_PATH", str(live))
    import app as appmod
    r = appmod.app.test_client().get("/?skip_about=1")
    assert r.status_code == 200 and "veilo_sid" not in " ".join(r.headers.getlist("Set-Cookie"))
    assert not (tmp_path / "sessions").exists()
