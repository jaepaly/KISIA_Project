"""Pretendard 서브셋 생성기 — apps/sns/fonts-src/ 의 원본(전체 글리프)에서 화면용 woff2 를 잘라낸다.

    PYTHONIOENCODING=utf-8 python scripts/subset_fonts.py          # 다시 만들기
    PYTHONIOENCODING=utf-8 python scripts/subset_fonts.py --check  # 커밋된 파일이 생성 결과와 같은지만 확인

굵기(400 · 600 · 700)마다 다섯 파일로 나눈다 (unicode-range 분할).
  core       — 라틴 · 문장부호 · 화살표 · 수학 · 도형 · CJK 기호 · 호환 자모 · 전각 + KS X 1001 완성형 한글 2,350자.
               한국어 화면은 거의 이것 하나로 끝난다.
  ext1~ext3  — KS X 1001 밖 한글 8,822자(「똠 · 쀍 · 햏」 등)를 코드 순서로 셋으로 나눈 것.
  ext4       — 원본에 있는 나머지 (라틴 확장 · 키릴 · 그리스 확장 · CJK 호환 · 사용자 정의 영역 …).
  ext 는 그 범위의 글자가 화면(사용자가 쓴 글 포함)에 실제로 있을 때만 브라우저가 받는다.

unicode-range 규칙:
  - ext 는 실제 들어 있는 코드포인트를 정확하게 쓴다. KS 안 글자만 있는 화면에서 ext 를 받지 않게 하려면
    ext 범위에 KS 음절이 하나도 걸리면 안 된다. 원본에 없는 코드포인트로 다리를 놓지도 않는다
    (놓으면 예: 이모지 🌊 가 있는 화면에서 쓸 수도 없는 ext 를 받는다).
  - core 는 블록 단위로 넓게 쓰고 한글 음절 블록 전체(U+AC00-D7A3)를 덮는다. KS 밖 음절이면 core 를 열어 보고
    글리프가 없으니 다음 면(ext)으로 넘어간다 (CSS Fonts 4 의 합성 글꼴 규칙 — 같은 굵기의 면은 나중 선언부터 본다).
    그래서 css 에서 core 를 각 굵기의 마지막에 선언한다.
  - 정확한 범위의 비용은 css 크기다 (KS 밖 음절이 1,613 구간으로 흩어져 있다 — 굵기당 약 20KB).

원본은 정적 폴더 밖(apps/sns/fonts-src/)에 둔다 — 서빙되지 않고, 재생성에만 쓴다.
외부 다운로드는 하지 않는다. fonttools + brotli 만 있으면 된다.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "apps" / "sns" / "fonts-src"
OUT = ROOT / "apps" / "sns" / "static" / "fonts"

WEIGHTS = [(400, "Regular"), (600, "SemiBold"), (700, "Bold")]

HANGUL = (0xAC00, 0xD7A3)
EXTRA_FEATURES = ["tnum"]   # 화면 css 에서 쓰는 OpenType 기능 (font-variant-numeric: tabular-nums)
HANGUL_EXT_PARTS = 3          # KS 밖 한글을 몇 파일로 나누나 — 파일 하나가 400KB 를 넘지 않게

# core 에 넣는 한글 밖 블록. 화면 문구(apps/sns · apps/analyzer)에 쓰인 기호를 모두 덮는다
# — · → ← ↓ ↔ ① ⚠ ✓ ✗ ≈ ≤ 「」『』《》 ： 등. 원본 글꼴에 없는 코드포인트는 범위에 있어도 무해하다
# (core 는 한국어 화면이면 어차피 받는다).
CORE_BLOCKS = [
    (0x0000, 0x00FF),  # 기본 라틴 + 라틴-1 보충 (· × § « » ±)
    (0x0370, 0x03FF),  # 그리스 (α Π — 화면 설명문)
    (0x2000, 0x206F),  # 일반 문장부호 (— – … ‘ ’ “ ”)
    (0x20A0, 0x20CF),  # 통화 기호 (₩ €)
    (0x2100, 0x214F),  # 글자꼴 기호 (℃ № ™)
    (0x2150, 0x218F),  # 숫자 형태 (Ⅰ Ⅱ ½)
    (0x2190, 0x21FF),  # 화살표
    (0x2200, 0x22FF),  # 수학 연산자
    (0x2300, 0x23FF),  # 기타 기술 기호 (⏎ ⌃)
    (0x2460, 0x24FF),  # 둘러싼 영숫자 (① ②)
    (0x2500, 0x257F),  # 상자 그리기
    (0x25A0, 0x25FF),  # 도형 (■ △ ○)
    (0x2600, 0x27BF),  # 기타 기호 · 딩뱃 (⚠ ✓ ✗)
    (0x3000, 0x303F),  # CJK 기호 · 문장부호 (「」『』《》。)
    (0x3130, 0x318F),  # 한글 호환 자모 (ㅋㅋ ㅠㅠ)
    (0xFF00, 0xFFEF),  # 반각 · 전각
]


def ks_x_1001_hangul() -> set[int]:
    """KS X 1001 완성형 2,350자. CPython 의 euc_kr 코덱은 KS 밖 음절도 8바이트 조합 시퀀스로
    인코딩하므로 「인코딩되느냐」가 아니라 「2바이트로 인코딩되느냐」로 가른다."""
    out = set()
    for cp in range(HANGUL[0], HANGUL[1] + 1):
        try:
            if len(chr(cp).encode("euc-kr")) == 2:
                out.add(cp)
        except UnicodeEncodeError:
            pass
    assert len(out) == 2350, len(out)
    return out


def in_blocks(cp: int, blocks) -> bool:
    return any(a <= cp <= b for a, b in blocks)


def split(cmap: set[int]) -> dict[str, set[int]]:
    """{파트 이름: 코드포인트} — 파트끼리 겹치지 않고 합치면 cmap 전체다."""
    ks = ks_x_1001_hangul()
    core = {cp for cp in cmap if cp in ks or in_blocks(cp, CORE_BLOCKS)}
    rest = cmap - core
    hangul = sorted(cp for cp in rest if HANGUL[0] <= cp <= HANGUL[1])
    parts = {"core": core}
    n = HANGUL_EXT_PARTS
    for i in range(n):
        parts[f"ext{i + 1}"] = set(hangul[len(hangul) * i // n: len(hangul) * (i + 1) // n])
    parts[f"ext{n + 1}"] = rest - set(hangul)
    return parts


def runs(cps) -> list[tuple[int, int]]:
    """연속 구간으로 묶는다 (정확하게 — 없는 코드포인트로 다리를 놓지 않는다)."""
    out: list[list[int]] = []
    for cp in sorted(cps):
        if out and out[-1][1] == cp - 1:
            out[-1][1] = cp
        else:
            out.append([cp, cp])
    return [(a, b) for a, b in out]


def fmt_range(rs) -> str:
    return ",".join(f"U+{a:X}" if a == b else f"U+{a:X}-{b:X}" for a, b in rs)


def make_subset(src: Path, cps: set[int]) -> bytes:
    opts = subset.Options()
    opts.flavor = "woff2"
    # 기본 기능(kern · liga · calt · locl …) + 화면이 쓰는 tnum(font-variant-numeric: tabular-nums).
    # "*" 로 전부 두면(cv01~13 · ss01~15 등 스타일 변형) core 가 216KB → 기본만이면 197KB
    opts.layout_features = list(subset.Options._layout_features_default) + EXTRA_FEATURES
    opts.name_IDs = ["*"]
    opts.name_languages = ["*"]
    opts.notdef_outline = True
    opts.recalc_timestamp = False      # 다시 돌려도 같은 바이트가 나오게
    font = subset.load_font(str(src), opts)
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=sorted(cps))
    sub.subset(font)
    buf = io.BytesIO()
    subset.save_font(font, buf, opts)
    return buf.getvalue()


CSS_HEAD = """/*
Pretendard — 로컬 self-host (이슈 #274). 외부 CDN 없이 이 서버에서만 받는다 — 방문자 IP 가 제3자로 안 나간다.
원본: orioncactus/pretendard@1.3.9 (OFL). 원본 파일은 apps/sns/fonts-src/ (서빙 안 됨).

⚠️ 이 파일과 woff2 는 생성물이다 — 손으로 고치지 말고 다시 만든다:
    PYTHONIOENCODING=utf-8 python scripts/subset_fonts.py

굵기(400 · 600 · 700)마다 다섯 면:
  core      — 라틴 · 기호 · CJK 문장부호 · 호환 자모 · KS X 1001 한글 2,350자. 한국어 화면은 이것만 받는다
  ext1~3    — KS 밖 한글 8,822자. ext4 — 라틴 확장 · 키릴 등 나머지
              그 범위의 글자가 화면에 실제로 있을 때만 받는다 (그래서 범위가 길다 — 정확해야 한다)
core 는 한글 음절 블록 전체를 덮고 각 굵기의 마지막에 선언한다. 브라우저는 나중 선언부터 보므로
core 에 없는 KS 밖 음절만 ext 로 넘어간다.

파도풀 분석기(/check)도 이 파일을 그대로 쓴다 (apps/analyzer/static/head.js) — 같은 주소라 캐시를 나눠 쓴다.
*/
"""


def build_css(ranges: dict[str, list[tuple[int, int]]]) -> str:
    order = [p for p in ranges if p != "core"] + ["core"]
    parts = [CSS_HEAD]
    for weight, name in WEIGHTS:
        for part in order:
            parts.append(
                "\n@font-face {\n"
                "  font-family: 'Pretendard';\n"
                "  font-style: normal;\n"
                f"  font-weight: {weight};\n"
                "  font-display: swap;\n"
                f"  src: url('Pretendard-{name}.{part}.woff2') format('woff2');\n"
                f"  unicode-range: {fmt_range(ranges[part])};\n"
                "}\n")
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="파일을 쓰지 않고 커밋된 것과 같은지만 본다")
    args = ap.parse_args()

    outputs: dict[Path, bytes] = {}
    ref = None
    print(f"{'file':36} {'codepoints':>10} {'bytes':>9}")
    for _, name in WEIGHTS:
        src = SRC / f"Pretendard-{name}.woff2"
        cmap = set(TTFont(str(src)).getBestCmap())
        if ref is None:
            ref = cmap
        elif ref != cmap:
            raise SystemExit(f"{src.name}: 굵기마다 cmap 이 달라 unicode-range 를 공유할 수 없다")
        print(f"{src.name:36} {len(cmap):10} {src.stat().st_size:9}")
        for part, cps in split(cmap).items():
            data = make_subset(src, cps)
            path = OUT / f"Pretendard-{name}.{part}.woff2"
            outputs[path] = data
            print(f"  -> {path.name:32} {len(cps):10} {len(data):9}")

    parts = split(ref)
    ranges = {p: runs(cps) for p, cps in parts.items()}
    ranges["core"] = sorted(CORE_BLOCKS + [HANGUL])       # core 는 넓게 (위 설명)
    css = build_css(ranges).encode("utf-8")
    outputs[OUT / "pretendard.css"] = css

    if args.check:
        stale = sorted(p.name for p, d in outputs.items() if not p.exists() or p.read_bytes() != d)
        extra = sorted(p.name for p in OUT.glob("*.woff2") if p not in outputs)
        if stale or extra:
            print("생성 결과와 다르다:", ", ".join(stale + extra))
            return 1
        print("OK — 커밋된 파일이 생성 결과와 같다")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.glob("*.woff2"):
        if p not in outputs:
            p.unlink()                  # 이전 분할 방식의 찌꺼기 — 남으면 서빙된다
    for p, d in outputs.items():
        p.write_bytes(d)
    print(f"pretendard.css {len(css)} bytes · ext 구간 수 " +
          " · ".join(f"{p} {len(r)}" for p, r in ranges.items() if p != "core"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
