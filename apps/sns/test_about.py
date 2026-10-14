"""「파도풀이란?」 소개 화면(/about) — 열리고, ?view=static 이면 핀(sticky) 없는 정지 화면으로 그린다.
첫 접속(소개 쿠키 없음)에 홈(/)을 열면 /about 으로 보낸다 · 첫 방문 소개 창(dialog)은 없다."""
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
    assert 'aria-label="소개 건너뛰고 Veilo 로">건너뛰기</a>' in html   # 처음부터 건너뛸 수 있다 — 상단바의 작은 글자 하나
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


def test_sticky_total_within_480svh(client):
    """핀 장면 높이 합계는 화면 4.8개(480svh) 이내 — 네 단계가 단계마다 멈춰 보이도록 늘렸다(10/14 · 160 → 240)."""
    import re
    html = client.get("/about").get_data(as_text=True)
    pins = [int(x) for x in re.findall(r'class="ps-pin[^"]*"[^>]*style="--pin:(\d+)"', html)]
    assert pins and sum(pins) <= 480


def test_nav_links_to_about(client):
    client.get("/about")   # 소개를 본 방문자 — 홈이 열린다
    html = client.get("/").get_data(as_text=True)
    assert 'href="/about" class="intro-btn"' in html
    assert html.count('href="/about"') == 1   # 상단바 하나 — 왼쪽 레일 · 피드 위 띠의 같은 링크는 뺐다 (10/14)


def test_home_has_one_entry_each(client):
    """홈에서 글쓰기 · 내 글 점검 · 파도풀이란? 은 상단바 하나씩(+ 휴대폰 하단 탭) — 같은 버튼이 세 번씩 나오던 것 (10/14)."""
    client.get("/about")
    html = client.get("/").get_data(as_text=True)
    body = html[html.index('class="ut-shell'):html.index('class="ut-tabs"')]   # 상단바 · 하단 탭을 뺀 본문
    assert 'href="/new"' not in body.replace('href="/new">첫 글을 써보세요', "")   # 글이 없을 때 안내 링크만 예외
    assert "scan.html" not in body and 'href="/about"' not in body
    assert "pado-strip" not in html and "pado-go" not in html


# ── 첫 접속 = /about ──────────────────────────────────────────────────
def _about_cookie(r) -> str:
    return next((c for c in r.headers.getlist("Set-Cookie") if c.startswith("pado_about_seen=")), "")


def test_first_visit_home_redirects_to_about(client):
    r = client.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/about")
    assert _about_cookie(r) == ""   # 보내기만 한다 — 쿠키는 소개를 연 뒤에


def test_about_sets_seen_cookie_then_home_opens(client):
    r = client.get("/about")
    c = _about_cookie(r)
    assert c.startswith("pado_about_seen=1;")
    assert "Max-Age=31536000" in c and "SameSite=Lax" in c and "HttpOnly" in c and "Path=/" in c
    r = client.get("/")   # 같은 브라우저(쿠키 있음) — 홈
    assert r.status_code == 200 and _about_cookie(r) == ""   # 이미 있으면 다시 심지 않는다


def test_home_with_cookie_is_200(client):
    client.set_cookie("pado_about_seen", "1")
    assert client.get("/").status_code == 200


def test_skip_about_query_opens_home_and_sets_cookie(client):
    r = client.get("/?skip_about=1")
    assert r.status_code == 200 and _about_cookie(r).startswith("pado_about_seen=1;")
    assert client.get("/").status_code == 200   # 그 뒤로는 쿼리 없이도


def test_other_paths_never_redirect(client):
    for path in ("/new", "/about", "/u/u_00000000", "/posts/NOPE", "/api/me", "/?partial=1"):
        r = client.get(path)
        assert r.status_code != 302 or "/about" not in r.headers.get("Location", ""), path


def test_intro_dialog_is_gone(client):
    client.get("/about")
    here = Path(__file__).resolve().parent
    for path in ("/", "/new", "/about"):
        html = client.get(path).get_data(as_text=True)
        assert "<dialog" not in html and 'id="intro"' not in html and "data-intro-" not in html, path
    for f in ("static/veilo.js", "static/veilo.css", "templates/base.html", "templates/about.html", "templates/list.html"):
        t = (here / f).read_text(encoding="utf-8")
        assert "padopool_intro_v1" not in t and "dialog.intro" not in t and "initIntro" not in t, f


def test_about_end_leads_into_veilo(client):
    html = client.get("/about").get_data(as_text=True)
    assert "이제 Veilo 에서" in html and "직접 해 보세요" in html
    assert 'href="/?skip_about=1">Veilo 둘러보기' in html


# ── 첫 화면 = 이해시키기 — Veilo 로 나가는 길은 「건너뛰기」 하나 · 로고는 파도풀 ─────────────────
def _hero(html: str) -> str:
    return html[html.index('id="hero"'):html.index('id="narrow"')]


def _top(html: str) -> str:
    return html[html.index('id="utTop"'):html.index('<main')]


def test_about_header_is_minimal(client):
    html = client.get("/about").get_data(as_text=True)
    top = _top(html)
    assert 'class="ut-top ps-top"' in html
    assert '<a class="ut-logo" href="/about">' in top            # 파도풀 소개 화면이라 로고도 파도풀 — 이 화면 맨 위로
    assert '<span class="wm">파도풀</span>' in top and "padopool-symbol.svg" in top
    assert '<span class="wm">Veilo</span>' not in top
    assert '<a class="ps-skipnav" href="/?skip_about=1" aria-label="소개 건너뛰고 Veilo 로">건너뛰기</a>' in top
    for gone in ('class="intro-btn"', 'class="chk"', 'class="write"', "/static/scan.html", 'href="/new"'):
        assert gone not in top, gone
    assert 'class="ut-tabs"' not in html                       # 모바일 하단 탭바도 뺀다
    assert 'id="psBar"' in top                                  # 읽기 진행 막대는 상단바 선 위에


def test_other_pages_keep_full_header(client):
    client.get("/about")
    for path in ("/", "/new"):
        html = client.get(path).get_data(as_text=True)
        assert 'class="ut-top" id="utTop"' in html and 'ps-top' not in html, path
        assert '<a class="ut-logo" href="/">' in html and 'class="intro-btn"' in html and 'class="write"' in html, path
        assert '<span class="wm">Veilo</span>' in html, path     # 다른 화면은 그대로 Veilo 로고
        assert 'class="ut-tabs"' in html and "ps-skipnav" not in html, path


def test_hero_has_no_jump_button_and_scroll_cue(client):
    import re
    html = client.get("/about").get_data(as_text=True)
    hero = _hero(html)
    hrefs = re.findall(r'href="([^"]+)"', hero)
    assert hrefs == [], hrefs                                   # 할 일은 스크롤 하나 — 아래로 끌어내리는 버튼 · 바로 써 보기 없음
    assert "어떻게 좁혀지는지 보기" not in html and "ps-down" not in html and "ps-peek" not in html
    assert "바로 써 보기" not in html and "건너뛰고 써 보기" not in html
    assert 'id="psField"' in hero and "/static/pado-hero.js" in html   # 마우스를 따라오는 돋보기 들판
    assert "아래로 내려 보세요" in hero and "예시" in hero        # 안내 한 줄 · 숫자는 예시
    assert 'id="psCue"' in html and "아래로 스크롤" in html
    assert html.count("Veilo 둘러보기") == 1 and html.index("Veilo 둘러보기") > html.index('id="end"')   # 끝 화면에만
    css = (Path(__file__).resolve().parent / "static" / "pado-scene.css").read_text(encoding="utf-8")
    assert ".no-motion .ps-cue i{animation:none" in css          # 정지 상태 — 멈춘 화살표
    js = (Path(__file__).resolve().parent / "static" / "pado-scene.js").read_text(encoding="utf-8")
    assert "CUE_GONE = 40" in js


# ── 장면 그림 — 좁혀지기 지도 · 네 단계 그림판 · 끝 화면 배경 ─────────────────
def test_scene_pictures(client):
    html = client.get("/about").get_data(as_text=True)
    narrow = html[html.index('id="narrow"'):html.index('id="steps"')]
    assert 'class="ps-mapbg"' in narrow and narrow.count('class="ps-pinm') == 5
    assert '<span class="ps-pinm r" data-card="2"' in narrow       # 오른쪽 끝 핀(차고지)은 라벨을 왼쪽으로 — 좁은 화면에서 안 잘리게
    assert "실제 장소나 실제 사람이 아닙니다" in narrow             # 지도도 가상이라고 적는다
    steps = html[html.index('id="steps"'):html.index('id="end"')]
    assert [f'data-vis="{i}"' in steps for i in range(4)] == [True] * 4
    end = html[html.index('id="end"'):]
    assert 'class="ps-waves"' in end and 'class="ps-demo reveal" aria-hidden="true"' in end
    css = (Path(__file__).resolve().parent / "static" / "pado-scene.css").read_text(encoding="utf-8")
    assert ".no-motion .ps-waves path{animation:none}" in css      # 정지 상태 — 물결도 멈춘다


def test_hero_field_has_no_external_requests():
    js = (Path(__file__).resolve().parent / "static" / "pado-hero.js").read_text(encoding="utf-8")
    for bad in ("http://", "https://", "fetch(", "XMLHttpRequest", "import("):
        assert bad not in js, bad
    assert 'classList.contains("no-motion")' in js               # 정지 상태면 한 장면만


def test_home_head_stats_and_no_pado_box(client):
    """홈 — 피드 머리(돋보기 들판) · 왼쪽 레일 숫자 · 위치 태그 막대 · 파도풀 설명 카드 없음 (10/14)."""
    client.get("/about")
    html = client.get("/").get_data(as_text=True)
    assert 'class="feed-head" data-field-host' in html and "<canvas class=\"feed-field\" data-field" in html
    assert "/static/pado-hero.js" in html
    assert 'class="rail-stats"' in html
    tpl = (Path(__file__).resolve().parent / "templates" / "list.html").read_text(encoding="utf-8")
    assert 'class="tag-bars"' in tpl                           # 위치 태그 막대 — 글이 없는 테스트 DB 에선 카드째 안 그린다
    assert "pado-box" not in html and "tag-cloud" not in html
    assert '<span class="ic" aria-hidden="true">🌊</span> 내 글 점검' in html   # 상단바 「내 글 점검」 — 출렁이는 🌊
    js = (Path(__file__).resolve().parent / "static" / "pado-hero.js").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in js                     # 홈엔 motion-core 가 없다 — 시스템 「동작 줄이기」를 직접 본다


def test_background_paper_and_map(client):
    """배경 — 종이 질감 + 가장자리 가상 지도(스크롤 시차). 비교용 ?bg= 는 없다 · 소개 화면은 끈다 (10/14)."""
    client.get("/about")
    html = client.get("/").get_data(as_text=True)
    assert '<div class="ut-bg" aria-hidden="true">' in html and '<svg class="map"' in html
    assert "data-bg" not in html and "?bg=" not in html and 'class="wave"' not in html
    assert 'setProperty("--bgp"' in html and "prefers-reduced-motion" in html   # 시차 · 동작 줄이기면 멈춤
    css = (Path(__file__).resolve().parent / "static" / "veilo.css").read_text(encoding="utf-8")
    assert ".ps-page .ut-bg{display:none}" in css and ".ps-page body::after{display:none}" in css


def test_post_page_has_head_section():
    """글 보기 — 머리 구역(작성자 줄 · 큰 제목)을 본문과 가른다 (10/14). 스타일이 템플릿이 아닌 veilo.css 에 있는지도 본다."""
    here = Path(__file__).resolve().parent
    tpl = (here / "templates" / "post.html").read_text(encoding="utf-8")
    assert '<header class="post-head">' in tpl and 'class="post-title"' in tpl and 'class="post-who"' in tpl
    assert 'id="postBody" class="post-body"' in tpl          # 파도풀 「이 글 점검」이 읽는 자리 그대로
    assert tpl.count("<article") == tpl.count("</article>") == 1
    assert ".post-head{" not in tpl                          # CSS 는 템플릿이 아니라 veilo.css
    css = (here / "static" / "veilo.css").read_text(encoding="utf-8")
    assert ".post-head{" in css and ".post-title{" in css and ".post-body{" in css

