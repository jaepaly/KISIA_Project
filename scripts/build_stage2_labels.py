"""2단 학습 라벨 v0 — 인물 JSON(clue_plan) → data/corpus/v0/gold/stage2/<pid>.json (결정적 · seed 없음).

    python scripts/build_stage2_labels.py                      # 115명 전부
    python scripts/build_stage2_labels.py --persona D05 D17    # 일부만

규칙은 data/corpus/v0/gold/stage2/README.md §2·§3-1 그대로다. 교사 라벨 원본이 아직 없어
설계(clue_plan)에서 유도한다. rewrites 는 v0 빌드에서 비운다 (§3-2 교사 LLM 몫 — 별도 인자).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PERSONAS = ROOT / "data/corpus/v0/personas"
OUT = ROOT / "data/corpus/v0/gold/stage2"

ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")
TYPE_OF = {"age": "AGE", "sex": "SEX", "location": "LOC_ADMIN", "occupation": "JOB",
           "family": "FAM", "commute": "COMMUTE", "income": "INCOME"}
LEVELS = ("explicit", "implicit", "inferential")
LEVEL_DOWN = {"explicit": "implicit", "implicit": "inferential", "inferential": "inferential"}
CONF = {"specified": 0.90, "narrowed_implicit": 0.70, "narrowed_inferential": 0.60,
        "weak_signal": 0.40, "abstain": 0.10}


def user_ref(pid: str) -> str:
    return "u_" + hashlib.sha256(pid.encode()).hexdigest()[:8]


def is_trap(clue: dict) -> bool:
    """§3-1 — subject:self 여도 note 에 「통로=」가 있으면 현 거주지가 아니다 (출신지·과거거주·방문지·이사·과거근무지)."""
    return "통로=" in str(clue.get("note", ""))


def build_input(pid: str, clue_plan: list[dict]) -> tuple[dict, dict[str, dict]]:
    """Stage2Input 모양의 입력과, span_id → 원 단서 매핑을 돌려준다."""
    profile_spans: list[dict] = []
    posts: dict[str, list[dict]] = {}
    by_span: dict[str, dict] = {}
    counters: dict[str, int] = {}
    for c in clue_plan:
        attr = c.get("attr")
        if attr not in TYPE_OF:
            continue
        tid = c.get("text_id") or "body"
        key = "profile" if tid == "profile_bio" else c.get("post")
        if not key:
            continue
        counters[key] = counters.get(key, 0) + 1
        sid = f"{pid}_{key}_s{counters[key]:02d}"
        span = {"span_id": sid, "text_id": tid, "text": c.get("clue", ""),
                "type": TYPE_OF[attr], "level": c.get("level"), "subject": c.get("subject") or "self"}
        by_span[sid] = {**c, "_post": None if key == "profile" else f"{pid}_{key}", "_sid": sid}
        if key == "profile":
            profile_spans.append(span)
        else:
            posts.setdefault(f"{pid}_{key}", []).append(span)
    inp = {
        "user_ref": user_ref(pid),
        "profile": {"spans": profile_spans} if profile_spans else None,
        "posts": [{"post_id": p, "spans": s} for p, s in sorted(posts.items())],
    }
    return inp, by_span


def findings_for(by_span: dict[str, dict], allowed_posts: set[str] | None = None) -> dict:
    """§3-1 — 속성마다 결정적으로. allowed_posts 가 주어지면 그 글(과 프로필)의 단서만 본다 (§5 증강)."""
    out = {}
    for attr in ATTRS:
        cands = []
        for sid, c in by_span.items():
            if c.get("attr") != attr:
                continue
            if allowed_posts is not None and c["_post"] is not None and c["_post"] not in allowed_posts:
                continue
            if (c.get("subject") or "self") != "self" or is_trap(c):
                continue
            lv = c.get("level")
            if lv not in LEVELS:
                continue
            if c.get("ambiguous"):
                lv = LEVEL_DOWN[lv]
            cands.append((lv, c))
        evidence = [{"post_id": c["_post"], "span_id": c["_sid"]} for _, c in cands]
        posts_seen = {c["_post"] for _, c in cands if c["_post"]}
        levels = [lv for lv, _ in cands]
        if not cands:
            verdict, conf = "abstain", CONF["abstain"]
        elif "explicit" in levels:
            verdict, conf = "specified", CONF["specified"]
        elif "implicit" in levels:
            verdict, conf = "narrowed", CONF["narrowed_implicit"]
        elif len({c["_post"] for lv, c in cands if lv == "inferential"}) >= 2:
            verdict, conf = "narrowed", CONF["narrowed_inferential"]
        else:
            verdict, conf = "weak_signal", CONF["weak_signal"]
        out[attr] = {"verdict": verdict, "confidence": conf,
                     "cross_post": len(posts_seen) >= 2, "evidence": evidence}
    return out


def build(persona: dict) -> dict:
    pid = persona["id"]
    inp, by_span = build_input(pid, persona.get("clue_plan", []))
    return {
        "persona_id": pid,
        "label_version": "v0",
        "derived_from": "clue_plan",
        "input": inp,
        "target": {"findings": findings_for(by_span), "rewrites": []},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", nargs="*", default=[])
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(PERSONAS.glob("[A-E]*.json"))
    if a.persona:
        files = [f for f in files if f.stem in set(a.persona)]
    n = 0
    verdicts: dict[str, int] = {}
    for f in files:
        p = json.loads(f.read_text(encoding="utf-8-sig"))
        rec = build(p)
        (out / f"{p['id']}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        n += 1
        for attr, fd in rec["target"]["findings"].items():
            verdicts[fd["verdict"]] = verdicts.get(fd["verdict"], 0) + 1
    print(f"인물 {n}명 → {out}")
    print("verdict 분포 (7속성 × 인물):", dict(sorted(verdicts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
