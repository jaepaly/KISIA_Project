"""Pretendard 서브셋 · 분석기 글꼴 공유 점검.

    PYTHONIOENCODING=utf-8 python -m pytest -q apps/sns/test_fonts.py

- pretendard.css 의 면마다 unicode-range 가 있고, 굵기(400·600·700)마다 core + ext 가 있다
- css 가 가리키는 woff2 가 다 있고, 정적 폴더에 css 가 안 가리키는 woff2(옛 전체 글꼴)가 없다
- 정적 폴더의 글꼴 파일은 하나도 400KB 를 넘지 않는다
- core 에 KS X 1001 한글 2,350자가 전부 있고, ext 범위에는 KS 음절이 하나도 걸리지 않는다
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
MAX_FONT_BYTES = 400 * 1024


def _ks_hangul() -> set[int]:
    return {cp for cp in range(0xAC00, 0xD7A4) if len(chr(cp).encode("euc-kr")) == 2}


def _faces() -> list[dict]:
    out = []
    for body in FACE_RE.findall(CSS.read_text(encoding="utf-8")):
        d = {}
        for m in re.finditer(r"([\w-]+)\s*:\s*([^;]+);", body):
            d[m.group(1)] = m.group(2).strip()
        d["file"] = re.search(r"url\('([^']+)'\)", d["src"]).group(1)
        out.append(d)
    return out


def _parse_range(s: str) -> list[tuple[int, int]]:
    out = []
    for tok in s.split(","):
        tok = tok.strip().upper().removeprefix("U+")
        a, _, b = tok.partition("-")
        out.append((int(a, 16), int(b or a, 16)))
    return out


def test_every_face_has_unicode_range_and_core_ext_per_weight():
    faces = _faces()
    assert faces, "pretendard.css 에 @font-face 가 없다"
    by_weight: dict[str, list[str]] = {}
    for f in faces:
        assert f.get("unicode-range"), f"{f['file']}: unicode-range 없음 — 화면마다 통째로 받는다"
        assert f.get("font-display") == "swap"
        assert f.get("font-family") == "'Pretendard'"
        by_weight.setdefault(f["font-weight"], []).append(f["file"].split(".")[1])
    assert set(by_weight) == {"400", "600", "700"}
    for w, parts in by_weight.items():
        assert "core" in parts and any(p.startswith("ext") for p in parts), (w, parts)
        assert parts[-1] == "core", f"{w}: core 는 굵기마다 마지막에 선언해야 KS 밖 음절이 ext 로 넘어간다"


def test_referenced_fonts_exist_and_no_stray_or_large_fonts():
    referenced = {f["file"] for f in _faces()}
    for name in referenced:
        assert (FONTS / name).is_file(), f"css 가 가리키는 {name} 이 없다"
    on_disk = {p.name for p in FONTS.iterdir() if p.suffix in (".woff2", ".woff", ".ttf", ".otf")}
    assert on_disk == referenced, f"css 가 안 가리키는 글꼴이 서빙된다: {sorted(on_disk - referenced)}"
    for p in (HERE / "static").rglob("*"):
        if p.suffix in (".woff2", ".woff", ".ttf", ".otf"):
            assert p.stat().st_size <= MAX_FONT_BYTES, f"{p.name} {p.stat().st_size} bytes — 서브셋이 아니다"


def test_core_has_all_ks_x_1001_and_ext_ranges_skip_ks():
    ttLib = pytest.importorskip("fontTools.ttLib")
    pytest.importorskip("brotli")
    ks = _ks_hangul()
    assert len(ks) == 2350
    for f in _faces():
        rs = _parse_range(f["unicode-range"])
        covered = lambda cp: any(a <= cp <= b for a, b in rs)  # noqa: E731
        part = f["file"].split(".")[1]
        if part == "core":
            cmap = set(ttLib.TTFont(str(FONTS / f["file"])).getBestCmap())
            missing = ks - cmap
            assert not missing, f"{f['file']}: KS 음절 {len(missing)}자 빠짐 (예: {chr(min(missing))})"
            assert all(covered(cp) for cp in ks)
            assert covered(ord("·")) and covered(ord("—")) and covered(ord("「")) and covered(ord("→"))
        else:
            hit = [cp for cp in ks if covered(cp)]
            assert not hit, f"{f['file']}: ext 범위에 KS 음절 {chr(hit[0])} — 한국어 화면마다 ext 를 받는다"


def test_ext_ranges_match_ext_cmaps():
    """ext 범위가 그 파일에 실제 있는 글자와 정확히 같다 — 넓으면 쓸데없이 받고, 좁으면 그 글자가 대체 글꼴로 나온다."""
    ttLib = pytest.importorskip("fontTools.ttLib")
    pytest.importorskip("brotli")
    for f in _faces():
        if f["file"].split(".")[1] == "core":
            continue
        declared = {cp for a, b in _parse_range(f["unicode-range"]) for cp in range(a, b + 1)}
        cmap = set(ttLib.TTFont(str(FONTS / f["file"])).getBestCmap())
        assert declared == cmap, f"{f['file']}: 범위 {len(declared)} vs 글리프 {len(cmap)}"


def test_rare_hangul_is_covered_by_some_ext():
    rare = "똠쀍햏뷁"
    faces = [f for f in _faces() if f["font-weight"] == "400" and f["file"].split(".")[1] != "core"]
    for ch in rare:
        assert any(any(a <= ord(ch) <= b for a, b in _parse_range(f["unicode-range"])) for f in faces), ch


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
    name = next(f["file"] for f in _faces() if f["file"].endswith(".core.woff2"))
    r = c.get(f"/static/fonts/{name}")
    assert r.status_code == 200 and r.headers.get("Access-Control-Allow-Origin") == "*"
    r.close()
    r = c.get("/static/veilo.css")
    assert "Access-Control-Allow-Origin" not in r.headers       # 글꼴만 연다
    r.close()

