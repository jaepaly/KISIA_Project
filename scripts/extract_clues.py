"""인물 JSON 의 clue_plan 을 베이스라인 비교용 입력으로 뽑는다.

W2 첫 비교(README B 파트 「수~금」)의 목적은 수치가 아니라
«기존 도구가 무엇을 놓치는지» 를 보는 것이다. 그러려면 입력에
«무엇이 심겼는지» 가 붙어 있어야 한다.

clue_plan 은 그 조건을 이미 만족한다 — 문장마다 attr(속성) ·
level(명시성) · subject(귀속) 가 설계 단계에서 붙어 있다.
생성된 글은 아직 라벨이 없으므로 이쪽이 첫 비교에 더 낫다.

    python scripts/extract_clues.py                    # 요약만
    python scripts/extract_clues.py -o clues.jsonl     # 파일로

출력 한 줄:
    {"id": "B01_b16", "text": "...", "attr": "income",
     "level": "implicit", "subject": "other", "persona": "B01",
     "text_id": "body"}
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os

DEFAULT_DIR = os.path.join("data", "corpus", "v0", "personas")


def extract(persona_dir: str) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(glob.glob(os.path.join(persona_dir, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            p = json.load(fh)
        pid = p.get("id") or os.path.basename(path)[:-5]
        for i, c in enumerate(p.get("clue_plan") or []):
            text = (c.get("clue") or "").strip()
            if not text:
                continue
            post = c.get("post") or "profile"
            rows.append({
                "id": f"{pid}_{post}_{i:02d}",
                "text": text,
                "attr": c.get("attr"),
                "level": c.get("level"),
                "subject": c.get("subject"),
                "persona": pid,
                "text_id": c.get("text_id"),
            })
    return rows


def summarize(rows: list[dict]) -> None:
    print(f"단서 문장 {len(rows)}개 / 인물 {len({r['persona'] for r in rows})}명\n")
    for key, label in (("attr", "속성"), ("level", "명시성"), ("subject", "귀속")):
        c = collections.Counter(r[key] for r in rows)
        body = " · ".join(f"{k} {v}" for k, v in c.most_common())
        print(f"  {label:5s} {body}")
    print()
    print("  ⭐ 기존 도구는 explicit 일부만 잡는다. 갈리는 곳은 implicit 이다.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--dir", default=DEFAULT_DIR, help="인물 JSON 디렉터리")
    ap.add_argument("-o", "--out", help="JSONL 출력 경로. 생략하면 요약만")
    ap.add_argument("--level", help="명시성으로 거른다 (explicit/implicit/inferential)")
    ap.add_argument("--attr", help="속성으로 거른다 (location/age/...)")
    a = ap.parse_args()

    rows = extract(a.dir)
    if a.level:
        rows = [r for r in rows if r["level"] == a.level]
    if a.attr:
        rows = [r for r in rows if r["attr"] == a.attr]

    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{a.out} — {len(rows)}줄\n")
    summarize(rows)


if __name__ == "__main__":
    main()
