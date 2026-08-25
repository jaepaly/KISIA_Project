"""생성된 글을 사람이 읽는 형태로 출력한다.

jsonl 을 그대로 열면 한 줄에 다 붙어 있어서 리얼리즘 검수를 할 수 없다.
Windows PowerShell 의 Get-Content 는 UTF-8 을 CP949 로 읽어 한글이 깨지기도 한다.
파이썬이 직접 읽어서 콘솔에 쓰면 둘 다 피할 수 있다.

    python read.py 경로\\S01.jsonl                 콘솔에 보기 좋게
    python read.py 경로\\*.jsonl --md 검수.md      마크다운으로 저장 (에디터에서 읽기)
    python read.py 경로\\S01.jsonl --kind clue     단서 글만
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

# Windows 콘솔이 CP949 로 잡혀 있어도 한글이 깨지지 않게
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

BAR = "─" * 60


def load(paths: list[str]) -> list[dict]:
    recs = []
    for pat in paths:
        for f in sorted(glob.glob(pat)) or [pat]:
            p = Path(f)
            if not p.is_file():
                print(f"(없음: {f})", file=sys.stderr)
                continue
            for line in p.read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    recs.append(json.loads(line))
    return recs


def fmt(r: dict) -> str:
    head = f"{r['post_id']}  [{r.get('kind', '?')}]  {r.get('n_chars', 0)}자"
    clue = r.get("clue")
    if clue:
        head += f"  · 심은 단서: {clue.get('attr')}/{clue.get('level')}"
        if clue.get("subject") == "other":
            head += "  ⚠함정(본인 아님)"
    out = [BAR, head, BAR, f"제목: {r.get('title', '(없음)')}", "", r.get("body", "")]
    if clue:
        out += ["", f"  └ 설계: {clue.get('clue')}"]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl", nargs="+")
    ap.add_argument("--kind", choices=["clue", "ambient", "noise"], help="이 종류만")
    ap.add_argument("--md", help="마크다운 파일로 저장")
    ap.add_argument("--no-answer", action="store_true",
                    help="심은 단서를 숨긴다 — blind 검수용")
    args = ap.parse_args()

    recs = load(args.jsonl)
    if args.kind:
        recs = [r for r in recs if r.get("kind") == args.kind]
    if not recs:
        print("읽을 글이 없다")
        return 1

    if args.no_answer:
        for r in recs:
            r.pop("clue", None)
            r["kind"] = "?"

    if args.md:
        lines = [f"# 생성 글 검수 ({len(recs)}편)", ""]
        for r in recs:
            lines.append(f"## {r['post_id']} · {r.get('kind')} · {r.get('n_chars')}자")
            lines.append("")
            lines.append(f"**{r.get('title', '')}**")
            lines.append("")
            lines.append(r.get("body", ""))
            if r.get("clue"):
                lines.append("")
                lines.append(f"> 설계: {r['clue'].get('clue')} "
                             f"({r['clue'].get('attr')}/{r['clue'].get('level')})")
            lines.append("")
        Path(args.md).write_text("\n".join(lines), encoding="utf-8")
        print(f"{args.md} 저장 ({len(recs)}편) — 에디터에서 여세요")
        return 0

    try:
        for r in recs:
            print(fmt(r))
            print()
        print(f"{BAR}\n{len(recs)}편 · 모델 {recs[0].get('gen_model', '?')} "
              f"· 프롬프트 {recs[0].get('prompt_version', '?')}")
    except BrokenPipeError:
        pass  # more / head 로 넘길 때 중간에 끊기는 건 정상
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
