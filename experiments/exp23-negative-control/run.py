"""exp23 — 네거티브 컨트롤: 단서 없는 잡담만 쓴 계정의 위험도가 낮은가 (C 성공 기준 「N1 에서 risk < 15」).

N1 은 선행 PoC 인물이라 저장소에 없다. 대신 코퍼스의 **잡담 글**(`negative_control: true` · 생성 계약상 단서 0 ·
시딩 때 위치태그도 붙지 않는다)만 모아 인물마다 「잡담만 쓰는 계정」을 만든다 (115명 · 계정당 5~22편).

위험도는 분석 앱과 같은 길로 잰다 — 스팬 → `conditions_from_posts`(본인 단서 · 여러 글 교집합) → `risk_total`.
스팬은 두 가지:
  --source gold   교사 라벨 + 사람 검수 골드(`data/corpus/v0/gold/*_spans.jsonl`). 모델 없이 재현된다
  --source model  앱의 1단(기준선 v2 + 명시 규칙). 체크포인트가 필요하다 — C1_CHECKPOINT_DIR

실행:
  PYTHONIOENCODING=utf-8 PYTHONPATH="src;." python experiments/exp23-negative-control/run.py --source gold
  ENGINE_MODE=real C1_CHECKPOINT_DIR=<v2 폴더> ... run.py --source model
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from kopl.c2_specificity import risk_by_axis, risk_total  # noqa: E402
from kopl.c2_specificity.k_engine import conditions_from_posts  # noqa: E402

CORPUS = ROOT / "data/corpus/v0"
THRESHOLD = 15.0


def negative_posts() -> dict[str, list[dict]]:
    by_persona: dict[str, list[dict]] = defaultdict(list)
    for f in sorted((CORPUS / "posts").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("negative_control") and "post_id" in r:
                by_persona[r["persona_id"]].append(r)
    return dict(by_persona)


def gold_spans() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for f in sorted((CORPUS / "gold").glob("*_spans.jsonl")):
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            r = json.loads(line) if line.strip() else {}
            if "post_id" in r:
                out[r["post_id"]] = list(r.get("spans") or [])
    return out


def model_spans(posts: list[dict]) -> dict[str, list[dict]]:
    from apps.analyzer.engines import real  # 체크포인트를 여기서 올린다
    out = {}
    for p in posts:
        t = p.get("texts") or {}
        rec = {"post_id": p["post_id"], "title": t.get("title"), "body": t.get("body") or "",
               "photo_captions": [t[k] for k in sorted(t) if k.startswith("photo_caption:")]}
        out[p["post_id"]] = list(real.detect_spans(rec).get("spans") or [])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("gold", "model"), required=True)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "results")
    a = ap.parse_args()

    by_persona = negative_posts()
    t0 = time.perf_counter()
    if a.source == "gold":
        spans = gold_spans()
        covered = sum(1 for ps in by_persona.values() for p in ps if p["post_id"] in spans)
    else:
        spans = model_spans([p for ps in by_persona.values() for p in ps])
        covered = len(spans)

    rows = []
    for pid, posts in sorted(by_persona.items()):
        kposts = [{"post_id": p["post_id"], "spans": spans.get(p["post_id"], []), "geo_tag": None} for p in posts]
        conds = conditions_from_posts(kposts)
        mine = [s for k in kposts for s in k["spans"] if s.get("subject") != "other"]
        axes = {k: v for k, v in risk_by_axis(conds).items() if v}
        rows.append({"persona_id": pid, "n_posts": len(posts), "n_spans_self": len(mine),
                     "types": dict(Counter(s.get("type") for s in mine)),
                     "risk": round(float(risk_total(conds)), 2), "risk_by_axis": axes})

    risks = [r["risk"] for r in rows]
    summary = {
        "source": a.source, "measured": time.strftime("%Y-%m-%d"),
        "accounts": len(rows), "posts": sum(r["n_posts"] for r in rows), "posts_with_labels": covered,
        "risk_median": round(statistics.median(risks), 2), "risk_mean": round(statistics.mean(risks), 2),
        "risk_p90": round(sorted(risks)[int(0.9 * (len(risks) - 1))], 2), "risk_max": max(risks),
        f"below_{int(THRESHOLD)}": sum(r < THRESHOLD for r in risks),
        "zero": sum(r == 0 for r in risks),
        "seconds": round(time.perf_counter() - t0, 1),
    }
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"metrics_{a.source}.json").write_text(
        json.dumps({"summary": summary, "accounts": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    worst = sorted(rows, key=lambda r: -r["risk"])[:5]
    for r in worst:
        print(r["persona_id"], r["risk"], r["n_spans_self"], r["types"], r["risk_by_axis"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
