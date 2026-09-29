"""exp8 축약판 — 페르소나 1명(D12)의 조치 곡선.

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp08-actions/run.py

골드 스팬 → build_conditions() → risk_total() 로 위험도를 재고, 조치별로 해당
스팬을 "완전히 제거된다"고 가정해 다시 잰다. 산출은 results/metrics.json 과
results/action_curve.svg 두 개다. 그래프는 외부 라이브러리 없이 SVG를 직접 쓴다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from kopl.c2_specificity import risk_by_axis, risk_total  # noqa: E402
from kopl.c2_specificity.clues import build_conditions  # noqa: E402

PERSONA = "D12"
GOLD = ROOT / "data" / "corpus" / "v0" / "gold" / f"{PERSONA}_spans.jsonl"
RESULTS = Path(__file__).resolve().parent / "results"

# 부담은 plan.md §2 조치 메뉴표의 등급을 그대로 쓴다 (1=낮음 · 2=중간 · 3=높음)
ACTIONS = [
    {"key": "rewrite", "label": "리라이트", "burden": 3,
     "types": {"AGE", "JOB", "FAM", "SEX", "INCOME"}},
    {"key": "activity_meta", "label": "활동 메타 관리", "burden": 2,
     "types": {"LOC_ADMIN", "LOC_FACILITY", "COMMUTE", "REL_HOME", "REL_WORK"}},
    {"key": "unpublish", "label": "비공개", "burden": 1, "posts": {"D12_b06"}},
]
BURDEN_LABEL = {1: "낮음", 2: "중간", 3: "높음"}
# 비공개 대상 글은 단서가 한 글에 몰려 있어(JOB·LOC_ADMIN·COMMUTE) 표현 단위로
# 고치기보다 통째로 숨기는 쪽을 권고한다 — 그래서 리라이트·메타 관리가 건드리지 않는다
PRIVATE_POSTS = set().union(*(a.get("posts", set()) for a in ACTIONS))


def load_posts() -> list[dict]:
    posts = []
    with GOLD.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                record = json.loads(line)
                if "post_id" in record:
                    posts.append(record)
    return posts


def measure(posts: list[dict], applied: list[dict]) -> dict:
    removed_types = set().union(*(a.get("types", set()) for a in applied))
    hidden = set().union(*(a.get("posts", set()) for a in applied))
    conditions = []
    for post in posts:
        pid = post["post_id"]
        if pid in hidden:
            continue
        spans = post.get("spans", [])
        if pid not in PRIVATE_POSTS:
            spans = [s for s in spans if s["type"] not in removed_types]
        conditions.extend(build_conditions(spans, pid))
    by_axis = risk_by_axis(conditions)
    return {
        "risk": round(risk_total(conditions), 1),
        "n_conditions": len(conditions),
        "risk_by_axis": {k: round(v, 1) for k, v in by_axis.items()},
    }


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build_svg(curve: list[dict], per_action: list[dict]) -> str:
    w, h = 900, 380
    pad_l, pad_t, plot_w, plot_h = 60, 50, 330, 250

    def y_of(risk: float) -> float:
        return pad_t + plot_h * (1 - risk / 100)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="Pretendard, Malgun Gothic, sans-serif" font-size="12">',
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        f'<text x="{w / 2}" y="24" text-anchor="middle" font-size="15" font-weight="700">'
        f'exp8 축약판 — {PERSONA} 조치 곡선 (위험도 0~100)</text>',
    ]

    # 왼쪽: 누적 적용 곡선
    x0 = pad_l
    parts.append(f'<text x="{x0 + plot_w / 2}" y="{pad_t - 10}" text-anchor="middle" '
                 f'font-weight="600">① 조치를 차례로 누적 적용</text>')
    for tick in (0, 25, 50, 75, 100):
        y = y_of(tick)
        parts.append(f'<line x1="{x0}" y1="{y}" x2="{x0 + plot_w}" y2="{y}" stroke="#eee"/>')
        parts.append(f'<text x="{x0 - 8}" y="{y + 4}" text-anchor="end" fill="#777">{tick}</text>')
    step_w = plot_w / (len(curve) - 1)
    points = [(x0 + i * step_w, y_of(c["risk"])) for i, c in enumerate(curve)]
    parts.append('<polyline fill="none" stroke="#D8896F" stroke-width="2.5" points="'
                 + " ".join(f"{x:.1f},{y:.1f}" for x, y in points) + '"/>')
    for (x, y), c in zip(points, curve):
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#D8896F"/>')
        parts.append(f'<text x="{x:.1f}" y="{y - 10:.1f}" text-anchor="middle" '
                     f'font-weight="700">{c["risk"]}</text>')
        parts.append(f'<text x="{x:.1f}" y="{pad_t + plot_h + 18}" text-anchor="middle" '
                     f'fill="#555">{c["short"]}</text>')

    # 오른쪽: 조치 유형별 (부담, 단독 효과)
    x1 = pad_l + plot_w + 120
    parts.append(f'<text x="{x1 + plot_w / 2}" y="{pad_t - 10}" text-anchor="middle" '
                 f'font-weight="600">② 조치 유형별 (부담, 단독 효과)</text>')
    for tick in (0, 25, 50):
        y = pad_t + plot_h * (1 - tick / 50)
        parts.append(f'<line x1="{x1}" y1="{y}" x2="{x1 + plot_w}" y2="{y}" stroke="#eee"/>')
        parts.append(f'<text x="{x1 - 8}" y="{y + 4}" text-anchor="end" fill="#777">−{tick}</text>')
    for burden, label in BURDEN_LABEL.items():
        x = x1 + plot_w * (burden - 0.5) / 3
        parts.append(f'<text x="{x:.1f}" y="{pad_t + plot_h + 18}" text-anchor="middle" '
                     f'fill="#555">부담 {label}</text>')
    for a in per_action:
        x = x1 + plot_w * (a["burden"] - 0.5) / 3
        y = pad_t + plot_h * (1 - a["effect_alone"] / 50)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#3E3A36"/>')
        effect = f"−{a['effect_alone']}" if a["effect_alone"] else "0"
        parts.append(f'<text x="{x:.1f}" y="{y - 12:.1f}" text-anchor="middle" '
                     f'font-weight="700">{a["label"]} {effect}</text>')

    parts.append(f'<text x="{w / 2}" y="{h - 10}" text-anchor="middle" fill="#888" font-size="11">'
                 f'가정: 조치 대상 단서는 완전히 제거된다 · 위험도 = C2 risk_total '
                 f'(7축 가중평균) · 부담 = plan.md §2</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    posts = load_posts()
    baseline = measure(posts, [])

    curve = [{"step": 0, "applied": [], "short": "조치 없음", **baseline}]
    for i in range(len(ACTIONS)):
        applied = ACTIONS[: i + 1]
        curve.append({
            "step": i + 1,
            "applied": [a["key"] for a in applied],
            "short": f"+{ACTIONS[i]['label']}",
            **measure(posts, applied),
        })

    per_action = []
    for i, a in enumerate(ACTIONS):
        alone = measure(posts, [a])
        per_action.append({
            "action": a["key"],
            "label": a["label"],
            "burden": a["burden"],
            "burden_label": BURDEN_LABEL[a["burden"]],
            "risk_alone": alone["risk"],
            "effect_alone": round(baseline["risk"] - alone["risk"], 1),
            "effect_in_sequence": round(curve[i]["risk"] - curve[i + 1]["risk"], 1),
        })

    metrics = {
        "experiment": "exp08-actions (축약판)",
        "measured_at": date.today().isoformat(),
        "persona": PERSONA,
        "data_version": "corpus v0 · gold/D12_spans.jsonl",
        "engine": "kopl.c2_specificity — clues.build_conditions + risk_total",
        "git_commit": git_commit(),
        "n_posts": len(posts),
        "assumption": "조치 대상 단서는 완전히 제거된다 (잔존 단서는 W9 전체판에서 다룬다)",
        "burden_source": "docs/plan.md §2 조치 메뉴 (1=낮음 · 2=중간 · 3=높음)",
        "unpublish_target_posts": sorted(PRIVATE_POSTS),
        "curve": [{k: v for k, v in c.items() if k != "short"} for c in curve],
        "per_action": per_action,
    }

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "action_curve.svg").write_text(build_svg(curve, per_action), encoding="utf-8")

    for c in curve:
        print(f"{c['step']} {c['short']}: {c['risk']}")
    for a in per_action:
        print(f"  {a['label']}: 부담 {a['burden_label']} · 단독 효과 −{a['effect_alone']} "
              f"· 순서 안 효과 −{a['effect_in_sequence']}")


if __name__ == "__main__":
    main()
