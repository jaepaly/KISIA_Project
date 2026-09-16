"""시딩된 글의 «다르게 쓰기» 후보를 미리 만들어 둔다 — apps/demo/data/rewrites.json

    DEMO_EXTERNAL_REWRITE=true PYTHONPATH=src python apps/demo/tools/bake_rewrites.py
    ... --check          바꾸지 않고 빠진 항목만 센다 (배포 전 점검용)

왜: 시딩된 글은 심사위원 모두에게 똑같다. 그 답을 여기서 한 번 만들어 두면 점검 화면이 1초 안에 뜨고,
게이트웨이가 죽어도 시연이 돌고, 사람마다 다른 문구가 뜨지 않는다. 심사위원이 «직접 쓴 글» 은
여기 없으므로 그대로 모델을 부른다 — 그 자리가 실제로 도는 것을 보여준다.

모델이 낸 답을 그대로 담는다. 사람이 고르거나 손보지 않는다 (그건 recommend.py 의 _CACHE 가 하는 일).
위치태그 ON/OFF 두 상태를 모두 굽는다 — 시연에서 태그를 끄면 사다리가 달라져 열쇠가 바뀌기 때문.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent
ROOT = DEMO.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(DEMO))

from engine import external                                  # noqa: E402
from engine.pipeline import analyze, compute                 # noqa: E402
from engine.recommend import (_CACHE, _bake_key, _line_of, ladder_candidates,  # noqa: E402
                              leading_particle, others_in_sentence, sentence_context)
from probe import DEFAULT, export_for                        # noqa: E402

OUT = DEMO / "data" / "rewrites.json"


def spans_to_bake():
    """인물 × 위치태그 상태마다 (문장, 구간, 사다리, 말투) 를 모은다. 중복 열쇠는 한 번만."""
    seen, out = set(), []
    for pid in DEFAULT:
        for geo in (True, False):
            view = analyze(export_for(pid, geo))
            for p in view["posts"]:
                for sp in p["spans"]:
                    if sp["subject"] != "self" or p["notes"].get(sp["span_id"], {}).get("exclude"):
                        continue
                    if sp["text"] in _CACHE:      # 손으로 다듬어 둔 후보가 이긴다 — 구울 필요가 없다
                        continue
                    text = p["texts"][sp["text_id"]]
                    ls, le = _line_of(text, sp["start"], sp["end"])
                    sentence = text[ls:le]
                    widen = ladder_candidates(view, p["post_id"], sp, p["notes"].get(sp["span_id"], {}))
                    ladder = [w["text"] for w in widen]
                    key = _bake_key(sentence, sp["text"], ladder)
                    if key in seen:
                        continue
                    seen.add(key)
                    ctx = {**sentence_context(text, sp["start"], sp["end"]), "ladder": ladder,
                           "particle": leading_particle(text[sp["end"]:]),
                           "others": others_in_sentence(p, sp, ls, le),
                           "after": text[sp["end"]:sp["end"] + 16]}
                    out.append((key, pid, sentence, sp["text"], ctx))
    return out


def main() -> int:
    check = "--check" in sys.argv
    items = json.loads(OUT.read_text(encoding="utf-8"))["items"] if OUT.exists() else {}
    todo = spans_to_bake()
    missing = [t for t in todo if t[0] not in items]
    print(f"구간 {len(todo)}개 · 이미 구운 것 {len(todo) - len(missing)}개 · 새로 구울 것 {len(missing)}개")
    if check:
        return 1 if missing else 0
    if missing and not external.enabled():
        print("DEMO_EXTERNAL_REWRITE=true 와 키가 있어야 굽는다", file=sys.stderr)
        return 2
    for n, (key, pid, sentence, span, ctx) in enumerate(missing, 1):
        cands = external.rewrite_candidates(sentence, span, "평서형 · 구어체 어미 · 방언 유지", ctx)
        if not cands:
            # «없음» 도 적어 둔다 — 안 적으면 실행할 때마다 모델을 다시 불러 화면이 느려진다
            items[key] = {"persona": pid, "span": span, "sentence": sentence,
                          "ladder": ctx.get("ladder") or [], "candidates": []}
            print(f"  [{n}/{len(missing)}] {pid} 「{span}」 — 쓸 만한 답 없음 → 규칙으로 간다")
            continue
        items[key] = {"persona": pid, "span": span, "sentence": sentence,
                      "ladder": ctx.get("ladder") or [], "candidates": cands}
        print(f"  [{n}/{len(missing)}] {pid} 「{span}」 → {[c['text'] for c in cands]}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"model": external.MODEL, "items": items}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"저장: {OUT.relative_to(ROOT)} · 항목 {len(items)}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
