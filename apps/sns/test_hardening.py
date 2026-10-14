"""Veilo 보안 · 운영 보강 (A5 · A6 · A7) — 세션 사본 수명 · 청소 주기 · 상한 · HEAD · 같은 출처 확인 · 쿠키 Secure · 바꾼 것 수.

    python -m pytest -q apps/sns/test_hardening.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_sessions import _seed  # noqa: E402

REF = "u_0123456789ab"


@pytest.fixture
def env(tmp_path, monkeypatch):
    _seed(tmp_path / "sns.db")
    _seed(tmp_path / "sns.seed.db")
    monkeypatch.setenv("SNS_DB_PATH", str(tmp_path / "sns.db"))
    monkeypatch.delenv("SNS_SEED_DB", raising=False)
    monkeypatch.delenv("SNS_SESSION_DIR", raising=False)
    import app as appmod
    appmod.app.config["TESTING"] = True
    monkeypatch.setitem(appmod._sweep_state, "at", 0.0)
    return appmod, tmp_path


def _new_visitor(app):
    c = app.test_client()
    sid = " ".join(c.get("/?skip_about=1").headers.getlist("Set-Cookie")).split("veilo_sid=")[1].split(";")[0]
    return c, sid


def _age(p: Path, days: float) -> None:
    t = time.time() - days * 86400
    os.utime(p, (t, t))


# ── A5a 열 때마다 마지막 사용 시각을 갱신 · 보관 기간 = 쿠키 수명
def test_reading_refreshes_copy_and_idle_matches_cookie(env):
    appmod, root = env
    assert appmod.SESSION_IDLE_SECONDS == appmod.SESSION_MAX_AGE == 7 * 24 * 3600
    c, sid = _new_visitor(appmod.app)
    copy = root / "sessions" / f"{sid}.db"
    _age(copy, 3)                        # 사흘 동안 글만 읽었다 — 예전(이틀)이면 지워질 사본
    assert c.get(f"/u/{REF}").status_code == 200
    assert time.time() - copy.stat().st_mtime < 60
    cookie = appmod.app.test_client().get("/about").headers.getlist("Set-Cookie")
    assert any(v.startswith("veilo_sid=") and "Max-Age=604800" in v for v in cookie)


# ── A5b 청소는 N분에 한 번
def test_sweep_runs_at_most_once_per_interval(env, monkeypatch):
    appmod, root = env
    monkeypatch.setattr(appmod, "SESSION_SWEEP_SECONDS", 600)
    _new_visitor(appmod.app)                                   # 첫 사본 — 이때 청소가 한 번 돈다
    stale = root / "sessions" / ("a" * 24 + ".db")
    stale.write_bytes(b"")
    _age(stale, 30)
    _new_visitor(appmod.app)                                   # 10분이 안 지났다 — 폴더를 다시 훑지 않는다
    assert stale.exists()
    appmod._sweep_state["at"] = time.time() - 601              # 10분이 지났다
    _new_visitor(appmod.app)
    assert not stale.exists()


# ── A5c 사본 수 상한 — 넘으면 가장 오래 안 연 사본부터 지운다
def test_copy_cap_evicts_least_recently_used(env, monkeypatch):
    appmod, root = env
    monkeypatch.setattr(appmod, "SESSION_MAX", 5)
    monkeypatch.setattr(appmod, "SESSION_SWEEP_SECONDS", 3600)
    d = root / "sessions"
    d.mkdir()
    olds = []
    for i in range(5):
        f = d / (f"{i:x}" * 24 + ".db")
        f.write_bytes(b"")
        _age(f, 5 - i * 0.5)                                    # 0번이 가장 오래 안 열렸다
        olds.append(f)
    c, sid = _new_visitor(appmod.app)                          # 상한(5)에 닿았다 — 청소 후 4(90%)개 + 새 사본
    alive = sorted(p.name for p in d.glob("*.db"))
    assert (d / f"{sid}.db").exists() and len(alive) <= 5
    assert not olds[0].exists() and olds[-1].exists()
    # 남은 수를 기억해 두었다가 상한에 닿을 때만 다시 센다 — 새 방문자가 와도 여전히 상한 이하
    for _ in range(4):
        _new_visitor(appmod.app)
    assert len(list(d.glob("*.db"))) <= 5
    # 지워진 방문자는 다음 방문에 시드 상태의 새 사본을 받는다 (오류 없이)
    assert c.get(f"/u/{REF}").status_code == 200


def test_new_copy_has_visitor_tables_and_no_temp_files(env):
    appmod, root = env
    _, sid = _new_visitor(appmod.app)
    con = sqlite3.connect(root / "sessions" / f"{sid}.db")
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"me", "action_log"} <= names
    assert not list((root / "sessions").glob("*.tmp"))


# ── A5d HEAD 는 사본도 쿠키도 만들지 않는다
def test_head_creates_no_copy(env):
    appmod, root = env
    r = appmod.app.test_client().head("/?skip_about=1")
    assert r.status_code == 200
    assert "veilo_sid" not in " ".join(r.headers.getlist("Set-Cookie"))
    sessions = root / "sessions"
    assert not sessions.exists() or not list(sessions.glob("*.db"))


def test_sid_must_match_fully(env):
    appmod, root = env
    c = appmod.app.test_client()
    c.set_cookie(key="veilo_sid", value="0123456789abcdef0123\n")   # 끝에 줄바꿈 — match 로는 통과하던 값
    r = c.get("/?skip_about=1")
    assert "veilo_sid=" in " ".join(r.headers.getlist("Set-Cookie"))   # 새 세션을 받는다
    assert not any("\n" in p.name for p in (root / "sessions").glob("*"))


# ── A6 같은 출처 확인
POSTS = [
    ("/posts/S01_b01/visibility", {"back": f"/u/{REF}"}),
    ("/posts/S01_b01/edit", {"geo_tag": "성수동"}),
    (f"/u/{REF}/edit", {"nickname": "바꾼닉"}),
    ("/me", {"author_id": "S01"}),
    ("/changes/undo-all", {}),
    (f"/u/{REF}/reset", {}),
    ("/posts", {"author_id": "S01", "body": "새 글", "created_at": "2026-01-03T09:00"}),
]


@pytest.mark.parametrize("path, data", POSTS)
def test_cross_origin_post_rejected(env, path, data):
    appmod, _ = env
    c, _ = _new_visitor(appmod.app)
    assert c.post(path, data=data, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post(path, data=data, headers={"Referer": "https://evil.example/page"}).status_code == 403
    assert c.post(path, data=data, headers={"Origin": "null"}).status_code == 403
    assert c.post(path, data=data, headers={"Origin": "http://localhost"}).status_code in (200, 302)


def test_cross_origin_does_not_change_state(env):
    appmod, _ = env
    c, _ = _new_visitor(appmod.app)
    c.post("/posts/S01_b01/visibility", data={"back": f"/u/{REF}"}, headers={"Origin": "https://evil.example"})
    assert "🔒 비공개로" in c.get(f"/u/{REF}").get_data(as_text=True)   # 여전히 공개
    assert c.post("/api/clues/S01_b01", json={"n": 1}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_forwarded_host_and_allowed_origins(env, monkeypatch):
    appmod, _ = env
    c, _ = _new_visitor(appmod.app)
    h = {"Origin": "https://veilo.site"}
    assert c.post("/me", data={"author_id": ""}, headers=h).status_code == 403
    assert c.post("/me", data={"author_id": ""}, headers={**h, "X-Forwarded-Host": "veilo.site"}).status_code == 302
    monkeypatch.setattr(appmod, "_ALLOWED_HOSTS", {"veilo.site"})
    assert c.post("/me", data={"author_id": ""}, headers=h).status_code == 302


# ── A7 쿠키 Secure · 바꾼 것 수 · 인물 요약 기억
def test_cookie_secure_flag(env, monkeypatch):
    appmod, _ = env
    r = appmod.app.test_client().get("/about")
    assert all("Secure" not in v for v in r.headers.getlist("Set-Cookie"))   # 로컬 기본값 — http 에서도 쿠키가 붙게
    monkeypatch.setattr(appmod, "COOKIE_SECURE", True)
    r = appmod.app.test_client().get("/about")
    cookies = r.headers.getlist("Set-Cookie")
    assert len(cookies) == 2 and all("Secure" in v for v in cookies)


def test_change_count_matches_changes(env):
    appmod, _ = env
    c, sid = _new_visitor(appmod.app)
    c.post("/me", data={"author_id": "S01"})
    c.post("/posts/S01_b01/visibility", data={"back": "/"})
    c.post("/posts/S01_b01/edit", data={"geo_tag": "성수동"})
    with appmod.app.test_request_context(headers={"Cookie": f"veilo_sid={sid}"}):
        appmod._ensure_session()
        assert appmod._change_count("S01") == len(appmod._changes("S01")) == 2
    assert c.get("/api/me").get_json()["me"]["changes"] == 2


def test_debug_off_by_default():
    src = (Path(__file__).resolve().parent / "app.py").read_text(encoding="utf-8")
    assert 'debug=os.getenv("FLASK_DEBUG") == "1"' in src and "debug=True" not in src


# ── Codex 검토 반례
def test_install_never_overwrites_existing_copy(env, monkeypatch):
    """같은 쿠키의 두 요청이 사본을 만들 때 — 늦은 쪽이 먼저 만든 사본(그 사이 저장한 수정)을 덮지 않는다.
    하드 링크를 못 쓰는 파일 시스템(대체 경로)에서도 같다."""
    appmod, root = env
    d = root / "sessions"
    d.mkdir()
    target = d / ("ab" * 12 + ".db")
    target.write_bytes(b"first")
    for link_fails in (False, True):
        tmp = d / "x.tmp"
        tmp.write_bytes(b"second")
        if link_fails:
            def no_link(*a, **k):
                raise OSError("no hard links")
            monkeypatch.setattr(appmod.os, "link", no_link)
        appmod._install(tmp, target)
        assert target.read_bytes() == b"first"
        tmp.unlink()


def test_cap_one_allows_only_one_new_copy(env, monkeypatch):
    """상한 1 — 새 방문자 둘이 연달아 와도 사본은 하나 (예전엔 청소가 셈을 다시 세며 예약을 잊어 둘 다 받았다)."""
    appmod, root = env
    monkeypatch.setattr(appmod, "SESSION_MAX", 1)
    monkeypatch.setattr(appmod, "SESSION_SWEEP_SECONDS", 0)     # 매번 청소 — 다시 세도 넘지 않아야 한다
    first, _ = _new_visitor(appmod.app)
    assert appmod.app.test_client().get("/?skip_about=1").status_code == 503
    assert appmod.app.test_client().get("/?skip_about=1").status_code == 503
    assert len(list((root / "sessions").glob("*.db"))) == 1
    assert first.get(f"/u/{REF}").status_code == 200


def test_cap_counts_copies_made_by_other_processes(env, monkeypatch):
    """사본 수는 디스크에서 센다 — 다른 프로세스(워커)가 만든 사본도 상한에 들어간다."""
    appmod, root = env
    monkeypatch.setattr(appmod, "SESSION_MAX", 2)
    monkeypatch.setattr(appmod, "SESSION_SWEEP_SECONDS", 3600)
    _new_visitor(appmod.app)                                    # 이 프로세스가 하나
    (root / "sessions" / ("c" * 24 + ".db")).write_bytes(b"")  # 다른 프로세스가 방금 하나
    assert appmod.app.test_client().get("/?skip_about=1").status_code == 503


def test_sessions_lock_is_exclusive_across_handles(env):
    """잠금 파일은 다른 핸들(다른 프로세스와 같은 조건)에서 잡으려 하면 막힌다."""
    import subprocess
    appmod, root = env
    d = root / "sessions"
    d.mkdir()
    code = chr(10).join([
        "import sys, os",
        "f = open(sys.argv[1], 'a+b')",
        "try:",
        "    if os.name == 'nt':",
        "        import msvcrt; f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)",
        "    else:",
        "        import fcntl; fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)",
        "    print('got')",
        "except OSError:",
        "    print('blocked')",
    ])
    with appmod._sessions_locked(d):
        out = subprocess.run([sys.executable, "-c", code, str(d / ".lock")], capture_output=True, text=True).stdout.strip()
    assert out == "blocked"
    out = subprocess.run([sys.executable, "-c", code, str(d / ".lock")], capture_output=True, text=True).stdout.strip()
    assert out == "got"


def test_cap_is_hard_when_all_copies_are_in_use(env, monkeypatch):
    """상한에 닿았는데 전부 방금 쓴 사본이면 — 지우지 않고, 새 방문자에게 사본 대신 503 (디스크를 채우지 않는다)."""
    appmod, root = env
    monkeypatch.setattr(appmod, "SESSION_MAX", 2)
    a, _ = _new_visitor(appmod.app)
    b, _ = _new_visitor(appmod.app)
    r = appmod.app.test_client().get("/?skip_about=1")
    assert r.status_code == 503 and "잠시 뒤" in r.get_data(as_text=True)
    assert len(list((root / "sessions").glob("*.db"))) == 2
    assert a.get(f"/u/{REF}").status_code == 200 and b.get(f"/u/{REF}").status_code == 200   # 있던 방문자는 그대로


def test_sec_fetch_site_same_origin_passes_behind_proxy(env):
    appmod, _ = env
    c, _ = _new_visitor(appmod.app)
    h = {"Origin": "https://veilo.site", "Host": "127.0.0.1:3000"}
    assert c.post("/me", data={"author_id": ""}, headers=h).status_code == 403
    assert c.post("/me", data={"author_id": ""}, headers={**h, "Sec-Fetch-Site": "same-origin"}).status_code == 302
    assert c.post("/me", data={"author_id": ""}, headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}).status_code == 403


# ── 글쓰기 한도 — 파도풀 점검 상한과 같은 값 (2차 Codex 검토)
def _write(c, **kw):
    data = {"author_id": "S01", "body": "새 글", "created_at": "2026-01-03T09:00", **kw}
    return c.post("/posts", data=data)


def test_post_field_limits_give_korean_message(env):
    appmod, _ = env
    c, _ = _new_visitor(appmod.app)
    for kw, word in ((dict(body="가" * (appmod.MAX_BODY_CHARS + 1)), "본문"),
                     (dict(title="가" * (appmod.MAX_TITLE_CHARS + 1)), "제목"),
                     (dict(geo_tag="가" * (appmod.MAX_GEO_CHARS + 1)), "위치 태그"),
                     (dict(captions="\n".join(f"사진{i}" for i in range(appmod.MAX_CAPTIONS + 1))), "사진 설명")):
        r = _write(c, **kw)
        assert r.status_code == 413 and word in r.get_data(as_text=True), (kw.keys(), r.status_code)
    assert _write(c, body="가" * appmod.MAX_BODY_CHARS).status_code == 302   # 한도까지는 된다
    assert c.post(f"/u/{REF}/edit", data={"nickname": "가" * 51}).status_code == 413
    assert c.post("/posts/S01_b01/edit", data={"geo_tag": "가" * 201}).status_code == 413


def test_per_author_total_matches_scan_cap(env, monkeypatch):
    appmod, _ = env
    monkeypatch.setattr(appmod, "MAX_CHARS_PER_AUTHOR", 50)
    c, _ = _new_visitor(appmod.app)
    assert _write(c, body="가" * 30).status_code == 302
    r = _write(c, body="가" * 30)
    assert r.status_code == 413 and "모두 합쳐" in r.get_data(as_text=True)
    monkeypatch.setattr(appmod, "MAX_CHARS_PER_AUTHOR", 150_000)
    monkeypatch.setattr(appmod, "MAX_POSTS_PER_AUTHOR", 2)
    assert _write(c).status_code == 413     # 시드 1편 + 위의 1편 = 2편 — 3편째는 막힌다
    assert appmod.MAX_CHARS_PER_AUTHOR >= 97_074 + appmod.MAX_BODY_CHARS // 4   # 가장 긴 시드 계정(E15)에도 글을 더 쓸 수 있다


def test_too_large_form_is_korean_413(env):
    appmod, _ = env
    c, _ = _new_visitor(appmod.app)
    r = _write(c, body="a" * (300 * 1024))
    assert r.status_code == 413 and "너무 큽니다" in r.get_data(as_text=True)
