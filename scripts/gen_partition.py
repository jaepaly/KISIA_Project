"""생성 대상 인물을 「지금 돌릴 것」과 「뒤로 뺄 것」으로 가른다.

    python scripts/gen_partition.py data/corpus/v0/personas ready
    python scripts/gen_partition.py data/corpus/v0/personas defer

D 몫은 D · E · S 다 (README W3 — E 인물 21명분과 오버플로를 D 가 흡수한다).

⚠️ 뒤로 빼는 기준은 「subject: other 함정이 없는 인물」이다.
   generate.py 의 classify_posts 는 post_plan.trap 을 읽지 않는다. clue_plan 에
   subject:other 항목이 있어야 함정 글이 나온다. 없으면 그 자리는 잡담이 되고
   검증기 산술(noise+ambient+clue+trap == total)은 그대로 맞아서 통과한다.
   그대로 돌리면 함정을 넣은 뒤 그 인물 글을 통째로 다시 뽑아야 한다.

   persona-design.md §4-4-1 · §8 체크리스트가 요구하는 것과 같은 조건이다.
   목록을 박아두지 않고 매번 파일을 읽는다 — 고쳐지면 다음 실행에서 ready 로 넘어간다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# D 가 도는 몫. GEN_ROLES 로 덮는다 — 흡수 대상은 주마다 달라진다.
#   2026-09-02: A 추가. A 계정의 ChatGPT 플랜이 codex 에서 gpt-5.6-sol 을
#   못 써서(「model is not supported when using Codex with a ChatGPT account」)
#   README 「한도 초과분 → D」 조항으로 흡수했다.
MINE = tuple(os.environ.get("GEN_ROLES", "A,D,E,S").split(","))


def has_other_trap(persona: dict) -> bool:
    return any(c.get("subject") == "other"
               for c in persona.get("clue_plan") or [])


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[2] not in ("ready", "defer"):
        print(__doc__)
        return 2
    root, which = Path(sys.argv[1]), sys.argv[2]

    for f in sorted(root.glob("*.json")):
        if not f.name.startswith(MINE):
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            print(f"  ✗ {f.name} 파싱 실패: {e}", file=sys.stderr)
            continue
        ok = has_other_trap(p)
        if (which == "ready") == ok:
            print(f.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
