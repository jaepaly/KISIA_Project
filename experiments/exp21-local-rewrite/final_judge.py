"""exp21 최종 판정 — README 「최종 판정」 규칙 그대로. 평가가 끝날 때까지 기다렸다가 이중 채점 · 판정 · 보고서.

    python experiments/exp21-local-rewrite/final_judge.py --wait

- 시험지: results/final_v2c_exp17.jsonl (52편) · results/final_v2c_aug1.jsonl (214편)
- 채점: judge_prompt.txt 로 Codex 를 두 번 따로 → 하나라도 wrong 이면 wrong · 둘 다 good 일 때만 good
- 채택: 합계 good ≥ 70% · wrong ≤ 5% (후보 기준)
- 산출: results/final_judge_{1,2}.txt · results/final_report.json · results/final_report.md
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE / "results"
SOURCES = {"exp17": 52, "aug1": 214}
CHUNK = 60  # 한 번에 채점할 후보 수 — 길면 Codex 출력이 잘린다


def rows_of(src: str) -> list[dict]:
    f = R / f"final_v2c_{src}.jsonl"
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


def wait_done() -> None:
    while True:
        done = {s: len({r["post_id"] for r in rows_of(s)}) for s in SOURCES}
        if all(done[s] >= n for s, n in SOURCES.items()):
            return
        print("대기", done, flush=True)
        time.sleep(60)


def judge_once(items: list[dict]) -> dict[int, dict]:
    prompt_head = (HERE / "judge_prompt.txt").read_text(encoding="utf-8")
    exe = shutil.which("codex.cmd") or shutil.which("codex") or "codex"
    out: dict[int, dict] = {}
    for c0 in range(0, len(items), CHUNK):
        chunk = items[c0:c0 + CHUNK]
        lines = []
        for j, r in enumerate(chunk, 1):
            b = r["context_before"].replace("\n", " ")
            a = r["context_after"].replace("\n", " ")
            lines.append(f"{j}. 유형={r['type']}\n   원문: …{b}【{r['original']}】{a}…\n   수정: …{b}【{r['suggestion']}】{a}…")
        for attempt in range(3):
            res = subprocess.run([exe, "exec", "--sandbox", "read-only", "-m", "gpt-6.1-sol", "-"],
                                 input=prompt_head + "\n".join(lines), capture_output=True, text=True,
                                 encoding="utf-8", timeout=1200)
            got = {}
            for m in re.findall(r'\{"i".*?\}', res.stdout):
                try:
                    o = json.loads(m)
                    got[int(o["i"])] = o
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
            if len(got) >= len(chunk):
                break
        for j in range(1, len(chunk) + 1):
            # 채점 누락은 보수적으로 wrong 처리 (규칙: 의심스러우면 나쁜 쪽)
            out[c0 + j] = got.get(j, {"i": j, "natural": 0, "meaning": 0, "less": 0, "wrong": 1, "why": "채점 누락"})
    return out


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", action="store_true")
    a = ap.parse_args()
    if a.wait:
        wait_done()
    items, src_of = [], []
    n_clues = {}
    for s in SOURCES:
        rows = rows_of(s)
        n_clues[s] = len(rows)
        for r in rows:
            if r["suggestion"]:
                items.append(r)
                src_of.append(s)
    j1 = judge_once(items)
    (R / "final_judge_1.json").write_text(json.dumps(j1, ensure_ascii=False), encoding="utf-8")
    j2 = judge_once(items)
    (R / "final_judge_2.json").write_text(json.dumps(j2, ensure_ascii=False), encoding="utf-8")

    def good(o):
        return bool(o["natural"] and o["meaning"] and o["less"] and not o["wrong"])

    per = []
    for i, r in enumerate(items, 1):
        g = good(j1[i]) and good(j2[i])
        w = bool(j1[i]["wrong"] or j2[i]["wrong"])
        per.append({"source": src_of[i - 1], "type": r["type"], "original": r["original"], "suggestion": r["suggestion"],
                    "good": g, "wrong": w, "agree": good(j1[i]) == good(j2[i]),
                    "why": [j1[i].get("why"), j2[i].get("why")]})
    report = {"rule": "README 최종 판정 — 합계 good ≥ 70% · wrong ≤ 5% (후보 기준) · 이중 채점 보수 병합"}
    for name, sel in (("exp17", "exp17"), ("aug1", "aug1"), ("합계", None)):
        ps = [p for p in per if sel is None or p["source"] == sel]
        n = len(ps)
        k_g, k_w = sum(p["good"] for p in ps), sum(p["wrong"] for p in ps)
        clues = sum(n_clues.values()) if sel is None else n_clues[sel]
        report[name] = {"clues": clues, "candidates": n, "good": k_g, "good_rate": round(k_g / n, 3) if n else None,
                        "good_ci95": wilson(k_g, n), "wrong": k_w, "wrong_rate": round(k_w / n, 3) if n else None,
                        "wrong_ci95": wilson(k_w, n), "good_over_clues": round(k_g / clues, 3) if clues else None,
                        "judge_agreement": round(sum(p["agree"] for p in ps) / n, 3) if n else None}
    t = report["합계"]
    report["adopted"] = bool(t["good_rate"] is not None and t["good_rate"] >= 0.70 and t["wrong_rate"] <= 0.05)
    report["bad_examples"] = [p for p in per if not p["good"]][:60]
    (R / "final_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# exp21 최종 판정 (v2c · exp17 + AUG1)", "", f"**판정: {'채택' if report['adopted'] else '미채택'}** — {report['rule']}", "",
          "| 시험지 | 단서 | 후보 | good | wrong | 단서 대비 good | 채점 일치 |", "|---|---|---|---|---|---|---|"]
    for name in ("exp17", "aug1", "합계"):
        x = report[name]
        md.append(f"| {name} | {x['clues']} | {x['candidates']} | {x['good']} ({x['good_rate']:.0%} · 95% {x['good_ci95'][0]:.0%}~{x['good_ci95'][1]:.0%}) "
                  f"| {x['wrong']} ({x['wrong_rate']:.0%} · 95% {x['wrong_ci95'][0]:.0%}~{x['wrong_ci95'][1]:.0%}) | {x['good_over_clues']:.0%} | {x['judge_agreement']:.0%} |")
    (R / "final_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
