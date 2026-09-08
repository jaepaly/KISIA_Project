"""시딩 글마다 어울리는 댓글을 Claude 로 한 번 만들어 apps/demo/data/comments.json 에 고정한다.

    ANTHROPIC_API_KEY=... PYTHONPATH=src python apps/demo/gen_comments.py            # 시딩 인물 전부 (없는 글만)
    ANTHROPIC_API_KEY=... PYTHONPATH=src python apps/demo/gen_comments.py D05 --force # 다시 만들기

댓글은 화면 장식이다 — 파도풀에 넘어가지 않고(export 에 없다) k 에 영향 없다. 하지만 심사자가 읽으니 글 내용·말투와 맞아야 한다.
규칙: 글에 없는 신상(지명·나이·직장·가족)을 새로 만들지 않는다 · 인물의 말투(voice)에 맞는 이웃이 단 것처럼 · 짧게.
댓글 수는 글 ID 에서 나오는 수(_n_comments_seed)와 같게 두어 좋아요·댓글 숫자가 안 흔들린다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
OUT = HERE / "data" / "comments.json"
MODEL = os.getenv("DEMO_EXTERNAL_MODEL", "claude-haiku-4-5-20251001")

from seed import DEFAULT_PERSONAS, load_persona, load_posts  # noqa: E402
from sns_ext import _n_comments_seed  # noqa: E402  (Flask 앱이 import 되지만 실행되진 않는다)

SYSTEM = """너는 한국 블로그 플랫폼의 이웃 댓글을 쓰는 사람이다. 주어진 글 한 편에 달릴 댓글 N개를 만든다.
- 글의 내용에 실제로 반응한다 (글에 나온 음식·날씨·상황·감정을 짚는다). 아무 글에나 붙는 인사말은 금지.
- 말투는 글쓴이의 문체와 그 블로그의 이웃 분위기에 맞춘다: 반말·ㅋㅋ·ㅠㅠ 커뮤형 글에는 친구 같은 반말, 격식체·존댓말 글에는 점잖은 존댓말, 시골 어르신 글에는 이웃 어르신 말투.
- 글에 없는 신상 정보(지명·나이·직장·가족·학교)를 댓글에서 새로 만들거나 추측하지 않는다. "OO 사시는군요" 같은 말 금지.
- 한 댓글 8~40자. 이모지는 글이 쓰면 조금, 아니면 안 쓴다.
- 댓글 단 사람의 닉네임도 만든다 (2~5자, 블로그 분위기에 맞게). 같은 글에 같은 닉네임 반복 금지.
JSON 배열만 출력: [{"who": "닉네임", "emoji": "아바타 이모지 1개", "text": "댓글", "when": "1일 전|2일 전|3일 전|5일 전|일주일 전"}]"""


def main() -> int:
    import anthropic

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    pids = args or DEFAULT_PERSONAS
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    client = anthropic.Anthropic()
    made = 0
    for pid in pids:
        persona = load_persona(pid)
        voice = json.dumps(persona.get("voice") or {}, ensure_ascii=False)
        acct = persona.get("account") or {}
        for post in sorted(load_posts(pid), key=lambda p: p["post_id"]):
            pid_ = post["post_id"]
            n = _n_comments_seed(pid_)
            if n == 0 or (pid_ in data and not force):
                continue
            t = post["texts"]
            user = (f"글쓴이 닉네임: {acct.get('nickname')}\n글쓴이 말투(voice): {voice}\n"
                    f"제목: {t.get('title') or '(없음)'}\n본문:\n{t['body']}\n\n댓글 {n}개.")
            try:
                msg = client.messages.create(model=MODEL, max_tokens=800, system=SYSTEM,
                                             messages=[{"role": "user", "content": user}])
                content = msg.content[0].text.strip()
                if content.startswith("```"):
                    content = content.strip("`").split("\n", 1)[1]
                arr = json.loads(content)
                items = [{"who": str(a["who"])[:8], "emoji": str(a.get("emoji") or "🙂")[:2],
                          "text": str(a["text"])[:80], "when": str(a.get("when") or "2일 전")} for a in arr][:n]
                if len(items) != n:
                    raise ValueError(f"{len(items)} != {n}")
                data[pid_] = items
                made += 1
                print(f"  {pid_}  {n}개  {items[0]['who']}: {items[0]['text'][:30]}")
            except Exception as e:  # noqa: BLE001
                print(f"  {pid_}  실패 — {e!r}")
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{made}편 생성 · 총 {len(data)}편 → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
