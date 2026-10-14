"""「파도풀이란?」 소개 화면(/about) — 열리고, ?view=static 이면 핀(sticky) 없는 정지 화면으로 그린다."""
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


def test_about_opens(client):
    r = client.get("/about")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert '<html lang="ko" class="ps-page">' in html          # 기본은 움직임 모드 — 정지 클래스 없음
    for sid in ('id="hero"', 'id="narrow"', 'id="steps"', 'id="end"'):
        assert sid in html
    assert "건너뛰고 써 보기" in html and 'href="/new"' in html   # 처음부터 건너뛸 수 있다
    assert "예시" in html                                         # 숫자는 가상 예시라고 적는다
    assert "/static/motion-core.js" in html and "/static/pado-scene.js" in html


def test_about_static_view_has_no_pin(client):
    html = client.get("/about?view=static").get_data(as_text=True)
    # .ps-static → CSS 가 sticky 를 푼다 · .no-motion → 공통 효과(.reveal · 호버 · 부드러운 스크롤)도 끈다
    assert '<html lang="ko" class="ps-page ps-static no-motion">' in html
    css = (Path(__file__).resolve().parent / "static" / "pado-scene.css").read_text(encoding="utf-8")
    assert ".ps-static .ps-sticky{position:static" in css
    veilo = (Path(__file__).resolve().parent / "static" / "veilo.css").read_text(encoding="utf-8")
    assert "html.no-motion{scroll-behavior:auto}" in veilo and ".no-motion .reveal" in veilo
    # 실제 브라우저 동작(계산 스타일 · 캔버스 루프 · 키보드)은 tools/check_motion.mjs 가 본다 — CI 에 크롬이 없어 pytest 밖


def test_pin_condition_same_in_js_and_css():
    """핀 조건(폭 + 높이)은 JS pinned() 와 CSS 정지 미디어쿼리가 같은 문자열이다 — 어긋나면 낮은 화면에서 내용이 잘린다."""
    import re
    here = Path(__file__).resolve().parent / "static"
    js = (here / "motion-core.js").read_text(encoding="utf-8")
    css = (here / "pado-scene.css").read_text(encoding="utf-8")
    mq = re.search(r'const PIN_MQ = "([^"]+)"', js).group(1)
    assert "min-height" in mq and "min-width:768px" in mq
    assert f"@media not all and {mq}" in css


def test_sticky_total_within_400svh(client):
    """핀 장면 높이 합계는 화면 4개(400svh) 이내."""
    import re
    html = client.get("/about").get_data(as_text=True)
    pins = [int(x) for x in re.findall(r'class="ps-pin[^"]*"[^>]*style="--pin:(\d+)"', html)]
    assert pins and sum(pins) <= 400


def test_nav_links_to_about(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="/about" class="intro-btn"' in html
    assert "1분 소개 보기 →" in html
