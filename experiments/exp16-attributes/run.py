"""exp16: 스팬 level·subject 규칙 판정(attributes.resolve) 정확도 — 골드 개발셋(튜닝) · blind(손대지 않은 평가).

비교: ① 지금 앱·추론기의 고정값 implicit/self ② 유형별 최빈값(개발셋에서 셈 — 상한 아닌 기준선) ③ 규칙.
reviewed=true 레코드만. 실행: PYTHONPATH=src python experiments/exp16-attributes/run.py
"""
from __future__ import annotations

import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from kopl.c1_span.attributes import resolve

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "results"


def load(pattern: str) -> list[tuple[dict, dict]]:
    rows = []
    for path in sorted(glob.glob(str(ROOT / pattern))):
        for line in open(path, encoding="utf-8-sig"):
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("reviewed") is not True:
                continue
            for s in rec.get("spans") or []:
                if "level" in s and "subject" in s:
                    rows.append((rec["texts"], s))
    return rows


def f1(gold: list[str], pred: list[str], label: str) -> dict:
    tp = sum(g == p == label for g, p in zip(gold, pred))
    fp = sum(p == label != g for g, p in zip(gold, pred))
    fn = sum(g == label != p for g, p in zip(gold, pred))
    pr = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(pr, 3), "recall": round(rc, 3), "f1": round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0,
            "support": tp + fn}


def score(rows, predict) -> dict:
    gl = [s["level"] for _, s in rows]
    gs = [s["subject"] for _, s in rows]
    preds = [predict(t, s) for t, s in rows]
    pl = [p["level"] for p in preds]
    ps = [p["subject"] for p in preds]
    n = len(rows)
    levels = ("explicit", "implicit", "inferential")
    return {
        "n": n,
        "level_acc": round(sum(a == b for a, b in zip(gl, pl)) / n, 3),
        "level_macro_f1": round(sum(f1(gl, pl, x)["f1"] for x in levels) / 3, 3),
        "level_by_label": {x: f1(gl, pl, x) for x in levels},
        "subject_acc": round(sum(a == b for a, b in zip(gs, ps)) / n, 3),
        "subject_other": f1(gs, ps, "other"),
        # 본인 명시 단서 — 추천·바꿔 쓰기 대상
        "self_explicit": f1(["se" if (a, b) == ("self", "explicit") else "x" for a, b in zip(gs, gl)],
                            ["se" if (a, b) == ("self", "explicit") else "x" for a, b in zip(ps, pl)], "se"),
    }


def main() -> int:
    dev = load("data/corpus/v0/gold/[A-E]*_spans.jsonl")
    blind = load("data/corpus/v0/gold/blind/*_spans.jsonl")
    by_type = defaultdict(Counter)
    for _, s in dev:
        by_type[s["type"]][s["level"]] += 1
    majority = {t: c.most_common(1)[0][0] for t, c in by_type.items()}

    systems = {
        "fixed_implicit_self": lambda t, s: {"level": "implicit", "subject": "self"},
        "type_majority_self": lambda t, s: {"level": majority.get(s["type"], "implicit"), "subject": "self"},
        "rules": lambda t, s: resolve(t, s),
    }
    result = {name: {"dev": score(dev, fn), "blind": score(blind, fn)} for name, fn in systems.items()}
    OUT.mkdir(exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    errs = []
    for split, rows in (("dev", dev), ("blind", blind)):
        for texts, s in rows:
            p = resolve(texts, s)
            if p["subject"] != s["subject"]:
                t = texts.get(s["text_id"], "")
                errs.append(f"- [{split}] subject 정답 {s['subject']} · 예측 {p['subject']} · {s['type']} · "
                            f"…{t[max(0, s['start'] - 30):s['start']]}[{s['text']}]{t[s['end']:s['end'] + 15]}…".replace("\n", " "))
    (OUT / "subject_errors.md").write_text("# subject 오답\n\n" + "\n".join(errs) + "\n", encoding="utf-8")

    for name, r in result.items():
        for split in ("dev", "blind"):
            m = r[split]
            print(f"{name:22s} {split:5s} n={m['n']:3d} level acc {m['level_acc']:.3f} macroF1 {m['level_macro_f1']:.3f} · "
                  f"subject acc {m['subject_acc']:.3f} other P/R {m['subject_other']['precision']:.2f}/{m['subject_other']['recall']:.2f} · "
                  f"self-explicit P/R {m['self_explicit']['precision']:.2f}/{m['self_explicit']['recall']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
