"""exp15 — 조사 맞춤 바꿔 쓰기 검증: 골드 본인 스팬 전체에 후보를 만들어 원문에 끼워 넣고 이음새를 검사한다.

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp15-rewrite/run.py

- 이음새 검사 (기계적 · 전수): 바꾼 말 뒤 조사가 새 말의 끝소리에 맞는가
  · 스팬 안 조사 — 다시 붙인 조사가 fit(새 말) 과 같은가
  · 스팬 밖 조사 — 바깥 조사가 새 말의 끝소리와 맞는가
- 덮음: 유형·등급별로 후보가 1개 이상 나온 스팬 비율
- 표본: 무작위 60개 (seed 고정) — 사람·Codex 가 자연스러움을 본다 (results/sample.md)
"""
from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from kopl.c4_stage2 import josa
from kopl.c4_stage2.rewrite import suggest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GOLD = ROOT / "data/corpus/v0/gold"
POSTS = ROOT / "data/corpus/v0/posts"


def junction_ok(original: str, cand: dict, after: str, stype: str = "") -> tuple[bool, str]:
    sp = josa.split_tail(original, copula_in=stype == "AGE")
    new = cand["suggestion"]
    core = cand["core"]
    if sp.tail:
        plural = sp.tail[: len(sp.tail) - len(sp.particle)] if sp.particle else sp.tail
        expect = core + plural + (josa.fit(core + plural, sp.particle) if sp.particle else "")
        return new == expect, f"안쪽 조사 {sp.particle!r} → {new!r} (기대 {expect!r})"
    return josa.fits_outside(core, after), f"바깥 조사 {josa.leading_particle(after)!r} · 새 말 {core!r}"


def main() -> int:
    stats: dict[tuple[str, str], Counter] = defaultdict(Counter)
    bad: list[str] = []
    samples: list[tuple[str, str, str, list[str]]] = []
    n_cands = 0
    for g in sorted(GOLD.glob("[A-E]*_spans.jsonl")):
        pid = g.stem.replace("_spans", "")
        path = POSTS / f"{pid}.jsonl"
        if not path.exists():
            continue
        posts = {json.loads(l)["post_id"]: json.loads(l) for l in path.read_text(encoding="utf-8-sig").splitlines() if l.strip()}
        for line in g.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            post = posts.get(r.get("post_id"))
            if not post:
                continue
            for s in r.get("spans") or []:
                if s.get("subject") != "self":
                    continue
                text = (post.get("texts") or {}).get(s["text_id"])
                if text is None or text[s["start"]:s["end"]] != s["text"]:
                    continue
                key = (s["type"], s["level"])
                stats[key]["spans"] += 1
                cands = suggest(s, text)
                after = text[s["end"]:]
                if cands:
                    stats[key]["covered"] += 1
                for c in cands:
                    n_cands += 1
                    ok, why = junction_ok(s["text"], c, after, s["type"])
                    if not ok:
                        bad.append(f"{r['post_id']} {s['type']} «{s['text']}» → «{c['suggestion']}» | {why}")
                ls = max(0, s["start"] - 18)
                ctx = text[ls:s["start"]].replace("\n", " ")
                tail = after[:18].replace("\n", " ")
                samples.append((s["type"], f"…{ctx}[{s['text']}]{tail}…",
                                f"…{ctx}[{{}}]{tail}…", [c["suggestion"] for c in cands]))
    rng = random.Random(20261005)
    pick = rng.sample([x for x in samples if x[3]], 60)
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    lines = ["# exp15 표본 60 — 원문 → 바꾼 문장\n"]
    for typ, orig, frame, cands in pick:
        lines.append(f"- **{typ}** {orig}")
        for c in cands:
            lines.append(f"  - {frame.format(c)}")
    (out / "sample.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    table = {f"{t}/{lv}": {"spans": c["spans"], "covered": c["covered"],
                           "rate": round(c["covered"] / c["spans"], 3) if c["spans"] else None}
             for (t, lv), c in sorted(stats.items())}
    total = sum(c["spans"] for c in stats.values())
    covered = sum(c["covered"] for c in stats.values())
    res = {"spans": total, "covered": covered, "coverage": round(covered / total, 4), "candidates": n_cands,
           "junction_errors": len(bad), "junction_error_examples": bad[:30], "by_type_level": table}
    (out / "metrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("spans", "covered", "coverage", "candidates", "junction_errors")}, ensure_ascii=False))
    for e in bad[:10]:
        print("  ✗", e)
    for k, v in table.items():
        print(f"  {k:24s} {v['covered']:4d}/{v['spans']:4d} {v['rate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
