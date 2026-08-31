"""인물 clue_plan → 2단 입력(스팬 목록). 두 모델에 같은 것을 준다.

    python experiments/exp05-model-size/build_input.py

⚠️ 글이 아니라 인물 JSON 을 읽는다. 글은 화~수에나 나오고 크기 결정은 그걸 기다릴 수 없다
   (README W3 D절 · D-stage2.md §4).

⚠️ 스팬에 attr 을 넣지 않는다. label-schema §8-1 이 「attr 은 스팬에 넣지 않는다 —
   유형-속성이 1:n 이라 §3-2 매핑표로 대신한다」로 못박았다. 2단은 type 을 받는다.
   그래서 clue_plan.attr 을 §3-2 매핑으로 type 으로 바꿔서 넣는다.
"""

from __future__ import annotations

import json
import glob
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")

# label-schema §3-2 매핑을 뒤집었다. 한 속성이 여러 유형에서 오므로 대표 하나를 고른다.
# 크기 «비교» 가 목적이라 두 모델에 같은 값만 가면 된다.
ATTR_TO_TYPE = {
    "age": "AGE", "sex": "SEX", "location": "LOC_ADMIN",
    "occupation": "JOB", "family": "FAM", "commute": "COMMUTE", "income": "INCOME",
}


def build(p: Path) -> dict | None:
    d = json.loads(p.read_text(encoding="utf-8-sig"))
    pid = d.get("id") or d.get("persona_id") or p.stem
    spans, seen = [], {}
    for c in d.get("clue_plan") or []:
        text = (c.get("clue") or "").strip()
        if not text:
            continue
        post = c.get("post") or "bio"
        n = seen.get(post, 0) + 1
        seen[post] = n
        spans.append({
            "span_id": f"{pid}_{post}_s{n:02d}",
            "text_id": c.get("text_id", "body"),
            "text": text,
            "type": ATTR_TO_TYPE.get(c.get("attr"), "OTHER"),
            "level": c.get("level", "inferential"),
            "subject": c.get("subject", "self"),
            # ↓ 채점용. 프롬프트에는 넣지 않는다
            "_attr": c.get("attr"),
        })
    if not spans:
        return None
    # 정답: 그 속성에 self 단서가 하나라도 있으면 「특정 시도 대상」, 없으면 abstain 기대
    has = {a: any(s["_attr"] == a and s["subject"] == "self" for s in spans) for a in ATTRS}
    return {
        "persona_id": pid,
        "spans": spans,
        "gold_has_clue": has,
        "ground_truth": d.get("ground_truth", {}),
        "scoring_keywords": d.get("scoring_keywords", {}),
        "n_trap": sum(1 for s in spans if s["subject"] == "other"),
    }


def main() -> int:
    out = []
    for f in sorted(glob.glob(str(ROOT / "data/corpus/v0/personas/*.json"))):
        item = build(Path(f))
        if item:
            out.append(item)
    dst = Path(__file__).resolve().parent / "input.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    ns = sum(len(x["spans"]) for x in out)
    nt = sum(x["n_trap"] for x in out)
    print(f"인물 {len(out)}명 · 스팬 {ns}건 (함정 subject=other {nt}건)")
    cov = {a: sum(1 for x in out if x["gold_has_clue"][a]) for a in ATTRS}
    print("속성별 단서 보유 인물 수 — 이게 주 지표의 분모다")
    for a in ATTRS:
        print(f"  {a:12}{cov[a]:3}/{len(out)}")
    print(f"\n{dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
