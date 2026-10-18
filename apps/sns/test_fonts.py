"""Pretendard 공식 동적 서브셋 · 분석기 글꼴 공유 점검.

    PYTHONIOENCODING=utf-8 python -m pytest -q apps/sns/test_fonts.py

- 직접 자른 서브셋은 OFL 예약 이름(RFN) 'Pretendard' 를 쓸 수 없다 — 저작자 공식 동적 서브셋(1.3.9)만 둔다 (#366)
- pretendard.css 의 면마다 unicode-range 가 있고, 굵기(400·600·700)마다 공식 조각 92개가 다 있다
- css 가 가리키는 woff2 가 다 있고, css 가 안 가리키는 글꼴 파일(옛 전체 글꼴 · 직접 자른 서브셋)이 없다
- 라이선스 전문(OFL.txt)과 RFN 문구가 같이 있다
- 굵기마다 KS X 1001 한글 2,350자와 화면 기호가 어느 조각엔가 들어 있다
- 분석기는 글꼴 사본이 없고 style.css 에 글꼴 @import 가 없다 — head.js 가 Veilo 것을 붙인다
- /static/fonts/ 응답에 교차 출처 허용 헤더가 붙는다 (로컬 분리 실행용)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FONTS = HERE / "static" / "fonts"
CSS = FONTS / "pretendard.css"
ANALYZER_STATIC = HERE.parent / "analyzer" / "static"

sys.path.insert(0, str(HERE))

FACE_RE = re.compile(r"@font-face\s*\{(.*?)\}", re.S)
FILE_RE = re.compile(r"^woff2-dynamic-subset/Pretendard-(Regular|SemiBold|Bold)\.subset\.(\d+)\.woff2$")
WEIGHT = {"400": "Regular", "600": "SemiBold", "700": "Bold"}
PIECES = 92                       # 공식 배포본 dynamic-subset 조각 수 (1.3.9)
MAX_FONT_BYTES = 100 * 1024       # 공식 조각은 하나에 수십 KB — 전체 글꼴(약 770KB)이 섞이면 걸린다
# ⚠ · ✓ 는 공식 서브셋에 없어 시스템 글꼴로 그려진다(원본 글꼴엔 있었음) — 아이콘성 기호라 그대로 둔다
SCREEN_SYMBOLS = "·—→「」①≈"


def _ks_hangul() -> set[int]:
    return {cp for cp in range(0xAC00, 0xD7A4) if len(chr(cp).encode("euc-kr")) == 2}


def _faces() -> list[dict]:
    out = []
    for body in FACE_RE.findall(CSS.read_text(encoding="utf-8")):
        d = {}
        for m in re.finditer(r"([\w-]+)\s*:\s*([^;]+);", body):
            d[m.group(1)] = m.group(2).strip()
        urls = re.findall(r"url\(([^)]+)\)", d["src"])
        assert len(urls) == 1, f"woff2 하나만 가리킨다: {d['src']}"
        d["file"] = urls[0].strip("'\"").removeprefix("./")
        out.append(d)
    return out


def _parse_range(s: str) -> list[tuple[int, int]]:
    out = []
    for tok in s.split(","):
        tok = tok.strip().upper().removeprefix("U+")
        a, _, b = tok.partition("-")
        out.append((int(a, 16), int(b or a, 16)))
    return out


def test_faces_are_official_dynamic_subset_pieces():
    faces = _faces()
    by_weight: dict[str, set[int]] = {}
    for f in faces:
        assert f.get("unicode-range"), f"{f['file']}: unicode-range 없음 — 화면마다 통째로 받는다"
        assert f.get("font-display") == "swap"
        assert f.get("font-family") == "'Pretendard'"
        m = FILE_RE.match(f["file"])
        assert m, f"공식 동적 서브셋 조각이 아니다: {f['file']}"
        assert WEIGHT[f["font-weight"]] == m.group(1), f
        by_weight.setdefault(f["font-weight"], set()).add(int(m.group(2)))
    assert set(by_weight) == set(WEIGHT)
    for w, pieces in by_weight.items():
        assert pieces == set(range(PIECES)), (w, sorted(set(range(PIECES)) - pieces))


def test_referenced_fonts_exist_and_no_stray_or_large_fonts():
    referenced = {f["file"] for f in _faces()}
    for name in referenced:
        assert (FONTS / name).is_file(), f"css 가 가리키는 {name} 이 없다"
    font_ext = (".woff2", ".woff", ".ttf", ".otf")
    on_disk = {p.relative_to(FONTS).as_posix() for p in FONTS.rglob("*") if p.suffix in font_ext}
    assert on_disk == referenced, f"css 가 안 가리키는 글꼴이 있다: {sorted(on_disk - referenced)[:5]}"
    for p in HERE.rglob("*"):
        if p.suffix in font_ext:
            assert p.stat().st_size <= MAX_FONT_BYTES, f"{p.name} {p.stat().st_size} bytes — 공식 조각이 아니다"


def test_license_and_reserved_font_name_kept():
    ofl = (FONTS / "OFL.txt").read_text(encoding="utf-8")
    assert "Reserved Font Name Pretendard" in ofl and "SIL OPEN FONT LICENSE" in ofl.upper()
    css_head = CSS.read_text(encoding="utf-8")[:1500]
    assert "Reserved Font Name Pretendard" in css_head and "OFL.txt" in css_head


def test_every_weight_covers_ks_x_1001_and_screen_symbols():
    need = _ks_hangul() | {ord(c) for c in SCREEN_SYMBOLS}
    assert len(_ks_hangul()) == 2350
    for w in WEIGHT:
        rs = [r for f in _faces() if f["font-weight"] == w for r in _parse_range(f["unicode-range"])]
        missing = [cp for cp in need if not any(a <= cp <= b for a, b in rs)]
        assert not missing, f"{w}: 범위 밖 {len(missing)}자 (예: {chr(missing[0])})"


def test_declared_ranges_have_glyphs():
    """조각이 선언한 KS 음절 · 화면 기호는 그 조각 파일에 실제로 있다 — 없으면 대체 글꼴로 나온다."""
    ttLib = pytest.importorskip("fontTools.ttLib")
    pytest.importorskip("brotli")
    need = _ks_hangul() | {ord(c) for c in SCREEN_SYMBOLS}
    for f in _faces():
        declared = {cp for a, b in _parse_range(f["unicode-range"]) for cp in range(a, b + 1)} & need
        if not declared:
            continue
        cmap = set(ttLib.TTFont(str(FONTS / f["file"])).getBestCmap())
        lost = declared - cmap
        assert not lost, f"{f['file']}: 선언했지만 글리프 없음 {len(lost)}자 (예: {chr(min(lost))})"


def test_analyzer_has_no_font_copy_and_uses_veilo_fonts():
    assert not (ANALYZER_STATIC / "fonts").exists(), "분석기에 글꼴 사본이 있다 — Veilo 것과 캐시를 못 나눈다"
    assert not list(ANALYZER_STATIC.rglob("*.woff2"))
    style = (ANALYZER_STATIC / "style.css").read_text(encoding="utf-8")
    assert not re.search(r"@import[^;]*(font|pretendard)", style, re.I)
    head = (ANALYZER_STATIC / "head.js").read_text(encoding="utf-8")
    assert "window.VEILO_BASE + '/static/fonts/pretendard.css\"" in head


def test_fonts_route_allows_cross_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("SNS_DB_PATH", str(tmp_path / "sns.db"))
    monkeypatch.delenv("SNS_SEED_DB", raising=False)
    from app import app
    c = app.test_client()
    r = c.get("/static/fonts/pretendard.css")
    assert r.status_code == 200 and r.headers.get("Access-Control-Allow-Origin") == "*"
    r.close()
    name = _faces()[0]["file"]
    r = c.get(f"/static/fonts/{name}")
    assert r.status_code == 200 and r.headers.get("Access-Control-Allow-Origin") == "*"
    r.close()
    r = c.get("/static/veilo.css")
    assert "Access-Control-Allow-Origin" not in r.headers       # 글꼴만 연다
    r.close()


def test_cors_header_not_leaking_outside_fonts():
    """정규화한 경로가 글꼴 폴더 밖이면 CORS 를 붙이지 않는다 — %2e%2e%2f 로 꼬은 경로 (Codex 10/14)."""
    import app as appmod
    c = appmod.app.test_client()
    for path in ("/static/fonts/%2e%2e%2fveilo.css", "/static/fonts/../veilo.css", "/static/veilo.css"):
        r = c.get(path)
        assert "Access-Control-Allow-Origin" not in r.headers, path



def test_static_scripts_revalidate():
    """pado.js · veilo.css 는 Cache-Control: no-cache — Flask 정적 파일의 기본값(werkzeug send_file · max_age 없음)이다.
    분석기(Starlette StaticFiles)는 기본으로 안 붙어 서버에서 붙인다(#381 후속). 이 기본이 바뀌면 옛 파일이 남으니 고정해 둔다"""
    import app as appmod
    c = appmod.app.test_client()
    for path in ("/static/pado.js", "/static/veilo.css"):
        r = c.get(path)
        assert r.status_code == 200 and "no-cache" in r.headers.get("Cache-Control", ""), path
        r.close()
