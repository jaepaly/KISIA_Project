"""처리방침 한 편을 그리기 위한 최소 마크다운 변환기.

의존성을 늘리지 않으려고 직접 쓴다 — `docs/privacy-policy.md` 가 실제로 쓰는 문법만 다룬다.
제목(#·##) · 인용(>) · 표 · 목록(-) · 굵게 · 인라인 코드 · 링크 · 수평선. 그 밖의 것은 문단으로 흘린다.
"""

from __future__ import annotations

import html
import re

_INLINE = (
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<b>\1</b>"),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)"), r'<a href="\2" rel="noopener">\1</a>'),
)


def _inline(t: str) -> str:
    t = html.escape(t)
    for rx, rep in _INLINE:
        t = rx.sub(rep, t)
    return t


def _is_row(line: str) -> bool:
    return line.startswith("|") and line.endswith("|")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip("|").split("|")]


def render(md: str) -> str:
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)          # 파일 머리의 주석은 빼고 그린다
    out: list[str] = []
    lines = md.replace("\r\n", "\n").split("\n")
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i].rstrip()
        if not ln.strip():
            i += 1
            continue
        if ln.startswith("---") and set(ln.strip()) == {"-"}:
            out.append("<hr>")
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            lv = len(m.group(1))
            out.append(f"<h{lv}>{_inline(m.group(2))}</h{lv}>")
            i += 1
            continue
        if _is_row(ln) and i + 1 < n and re.fullmatch(r"\|[\s:\-|]+\|", lines[i + 1].strip()):
            head = _cells(ln)
            i += 2
            body = []
            while i < n and _is_row(lines[i].strip()):
                body.append(_cells(lines[i].strip()))
                i += 1
            th = "".join(f"<th>{_inline(c)}</th>" for c in head)
            tr = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body)
            out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>")
            continue
        if ln.startswith(">"):
            block = []
            while i < n and lines[i].lstrip().startswith(">"):
                block.append(lines[i].lstrip()[1:].strip())
                i += 1
            inner = render("\n".join(block)) if any(b.startswith(("-", "#", "|")) for b in block) \
                else "".join(f"<p>{_inline(b)}</p>" for b in block if b)
            out.append(f"<blockquote>{inner}</blockquote>")
            continue
        if ln.lstrip().startswith("- "):
            items = []
            while i < n and lines[i].lstrip().startswith("- "):
                items.append(lines[i].lstrip()[2:].strip())
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + "</ul>")
            continue
        para = []
        while i < n and lines[i].strip() and not lines[i].lstrip().startswith(("#", ">", "-", "|")):
            para.append(lines[i].strip())
            i += 1
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)
