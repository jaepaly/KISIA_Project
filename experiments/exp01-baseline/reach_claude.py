"""도달 가능성 재측정 — 같은 98건(reachability_inputs.jsonl)을 Claude 로 돌려 Gemini 와 나란히 본다.

    python experiments/exp01-baseline/reach_claude.py --model claude-opus-4-8 [--workers 4]

채점은 compare.py 와 동일: 골드 attr + subject 엄격 일치 (subject 없는 골드는 unscorable).
출력: results/claude_labeled.jsonl · results/reach_compare.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")
SYSTEM = """너는 한국어 블로그 문장에서 글쓴이의 재식별 단서를 찾는 주석자다.
문장 하나가 주어진다. 글쓴이(또는 글에 등장하는 다른 사람)의 다음 7속성 중 하나를 드러내거나 좁히는 구간을 전부 찾아라:
age(나이) · sex(성별) · location(거주지·생활권) · occupation(직업·일) · family(가족 구성) · commute(통근 수단·경로) · income(소득·소비 수준)
- 직접 명시뿐 아니라 암시·추론 단서도 잡는다 (「면사무소 앞 버스가 한 시간에 한 대」→ location).
- subject: 글쓴이 본인이면 self, 남의 정보면 other, 판단 불가면 unknown.
- 없으면 빈 배열.
출력은 JSON 배열 하나만: [{"text": "구간", "attr": "location", "subject": "self"}, ...] . 설명 금지."""


def call(cli: list[str], text: str) -> list[dict]:
    r = subprocess.run(cli, input=f"{SYSTEM}\n\n문장: {text}", capture_output=True, encoding="utf-8", errors="replace", timeout=300)
    out = r.stdout.strip()
    m = re.search(r"\[.*\]", out, re.S)
    if not m:
        return []
    try:
        spans = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [s for s in spans if isinstance(s, dict) and s.get("attr") in ATTRS]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-opus-4-8")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    exe = shutil.which("claude") or "claude"
    cli = [exe, "-p", "--model", a.model]

    inputs = [json.loads(l) for l in (HERE / "reachability_inputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    gold = {c["id"]: c for c in (json.loads(l) for l in (HERE / "clues.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())}
    gem = {r["id"]: r for r in (json.loads(l) for l in (HERE / "results" / "gemini_labeled.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())}

    out_path = HERE / "results" / "claude_labeled.jsonl"
    done = {}
    if out_path.exists():
        done = {r["id"]: r for r in (json.loads(l) for l in out_path.read_text(encoding="utf-8").splitlines() if l.strip())}
    todo = [x for x in inputs if x["id"] not in done]
    print(f"{len(inputs)}건 · 남은 {len(todo)}건 · {a.model}", flush=True)
    with cf.ThreadPoolExecutor(a.workers) as ex, out_path.open("a", encoding="utf-8") as fh:
        futs = {ex.submit(call, cli, x["text"]): x for x in todo}
        for f in cf.as_completed(futs):
            x = futs[f]
            spans = f.result()
            rec = {"id": x["id"], "text": x["text"], "spans": spans, "detected": bool(spans), "model": a.model}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush()
            done[x["id"]] = rec
            print(f"  {x['id']} {len(spans)}", flush=True)

    def score(labeled: dict) -> dict:
        st = {lv: {"scorable": 0, "hit": 0} for lv in ("explicit", "implicit", "inferential")}
        for x in inputs:
            g = gold[x["id"]]
            if g.get("subject") not in ("self", "other", "unknown"):
                continue
            lv = g["level"]; st[lv]["scorable"] += 1
            r = labeled.get(x["id"], {})
            if any(s.get("attr") == g["attr"] and s.get("subject") == g["subject"] for s in r.get("spans", [])):
                st[lv]["hit"] += 1
        for lv in st:
            st[lv]["reach"] = round(st[lv]["hit"] / st[lv]["scorable"], 4) if st[lv]["scorable"] else None
        return st

    res = {"gemini-3.1-pro": score(gem), a.model: score(done), "n": len(inputs), "scoring": "attr+subject strict (compare.py 와 동일)"}
    (HERE / "results" / "reach_compare.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    for m, st in res.items():
        if isinstance(st, dict) and "explicit" in st:
            print(m, " · ".join(f"{lv} {v['hit']}/{v['scorable']} = {(v['reach'] or 0)*100:.1f}%" for lv, v in st.items()))


if __name__ == "__main__":
    main()
