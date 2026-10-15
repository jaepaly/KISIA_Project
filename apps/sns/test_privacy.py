"""개인정보 처리방침(/privacy) — 홈 왼쪽 카드에서 열리고, 화면에 적은 보관 기간 · 쿠키가 코드 값과 같다.
코드 값을 바꾸면(SESSION_MAX_AGE · SESSION_MAX · 쿠키 이름) 이 테스트가 깨진다 — 처리방침 문구도 같이 고친다."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import db as dbmod
    live = tmp_path / "sns.db"
    c = dbmod.connect(live)
    dbmod.init(c)
    c.close()
    monkeypatch.setenv("SNS_DB_PATH", str(live))
    monkeypatch.delenv("SNS_SEED_DB", raising=False)
    monkeypatch.delenv("SNS_SESSION_DIR", raising=False)
    import app as appmod
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def _html(client, path):
    r = client.get(path)
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_home_links_privacy(client):
    assert 'href="/privacy"' in _html(client, "/?skip_about=1")


def test_privacy_matches_code(client):
    import app as appmod
    html = _html(client, "/privacy")
    days = appmod.SESSION_MAX_AGE // (24 * 3600)
    assert appmod.SESSION_IDLE_SECONDS == appmod.SESSION_MAX_AGE   # 쿠키 기간 = 사본 보관 기간 (둘 다 「7일」로 적는다)
    assert f"마지막으로 연 때부터 {days}일" in html
    assert f"{appmod.SESSION_MAX}개" in html
    for cookie in (appmod.SESSION_COOKIE, appmod.ABOUT_COOKIE, "padopool_motion"):
        assert f"<code>{cookie}</code>" in html


def test_privacy_opens_without_about_redirect(client):
    """처음 온 사람도 소개로 보내지 않고 바로 연다 — 처리방침은 소개를 보기 전에도 읽을 수 있어야 한다."""
    r = client.get("/privacy")
    assert r.status_code == 200


def test_profile_notice_matches_session_age(client):
    import app as appmod
    tpl = (Path(__file__).resolve().parent / "templates" / "profile.html").read_text(encoding="utf-8")
    assert f"{appmod.SESSION_IDLE_SECONDS // (24 * 3600)}일 동안 사용하지 않으면" in tpl


def test_privacy_has_no_pending_marks(client):
    """[확인 중] 표시(class="tbd")가 남은 채로 내보내지 않는다 — 팀 확인을 받아 문구를 채우면 통과한다."""
    assert 'class="tbd"' not in _html(client, "/privacy")
