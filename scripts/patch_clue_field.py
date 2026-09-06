"""기존 posts/*.jsonl 의 clue 필드가 전부 null 인 결함을 수정한다.

인물 JSON 의 clue_plan 을 읽어 post_id 별로 단서 목록을 만들고,
글 레코드의 kind == "clue" 인 행에 그 목록을 채운다.
재생성 없이 메타만 패치한다.

사용법:
    python scripts/patch_clue_field.py
    python scripts/patch_clue_field.py --dry-run
"""

import argparse
import json
from pathlib import Path


def build_clue_map(persona: dict) -> dict[str, list]:
    m: dict[str, list] = {}
    for c in persona.get("clue_plan", []):
        m.setdefault(c["post"], []).append(c)
    return m


def patch_file(posts_path: Path, personas_dir: Path, dry: bool) -> tuple[int, int]:
    pid = posts_path.stem
    persona_path = personas_dir / f"{pid}.json"
    if not persona_path.exists():
        return 0, 0

    persona = json.loads(persona_path.read_text(encoding="utf-8-sig"))
    clue_map = build_clue_map(persona)

    lines = posts_path.read_text(encoding="utf-8-sig").splitlines()
    patched, skipped = 0, 0
    out = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        rec = json.loads(raw)
        if rec.get("kind") == "clue" and rec.get("clue") is None:
            post_key = rec["post_id"].split("_", 1)[1]  # A01_b02 → b02
            clues = clue_map.get(post_key)
            if clues:
                rec["clue"] = clues
                patched += 1
            else:
                skipped += 1
        out.append(json.dumps(rec, ensure_ascii=False))

    if not dry and patched:
        posts_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return patched, skipped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts", default="data/corpus/v0/posts")
    ap.add_argument("--personas", default="data/corpus/v0/personas")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    posts_dir = Path(args.posts)
    personas_dir = Path(args.personas)
    total_p = total_s = 0

    for f in sorted(posts_dir.glob("*.jsonl")):
        if f.name.startswith("_"):
            continue
        p, s = patch_file(f, personas_dir, args.dry_run)
        if p or s:
            print(f"  {f.name}  패치 {p}건  못찾음 {s}건")
        total_p += p
        total_s += s

    tag = "(dry-run)" if args.dry_run else ""
    print(f"\n합계: 패치 {total_p}건 · 못찾음 {total_s}건 {tag}")


if __name__ == "__main__":
    main()
