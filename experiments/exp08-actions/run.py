"""exp8 축약판 — 페르소나 1명(D12)의 조치 곡선.

    export PYTHONIOENCODING=utf-8 PYTHONPATH=src
    python scripts/split_train_test.py                       # test 목록 (지문 9662a167)
    python experiments/exp10-action-repro/build_inputs.py    # data/inputs_full.jsonl 생성
    python experiments/exp08-actions/run.py

위험도 계산은 하지 않는다. exp10(#281)이 합의된 정의(비공개 = LOO 탐욕 경로 ·
활동 메타 = 실제 geo_tag · 리라이트 = 명시 단서 교체)로 낸 D12 결과를 읽어
부담 등급(plan.md §2)과 함께 그래프 1장 + metrics.json 으로 낸다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from kopl.c2_specificity import risk_total  # noqa: E402

PERSONA = "D12"
EXP10_INPUTS = ROOT / "experiments" / "exp10-action-repro" / "data" / "inputs_full.jsonl"
RESULTS = Path(__file__).resolve().parent / "results"
# 대조 사례 — exp8 초판이 손으로 고른 비공개 대상. 단서가 몰려 있지만 전부 다른 글에도 있다
HAND_PICKED_POST = "D12_b06"

# 부담은 plan.md §2 조치 메뉴표의 등급을 그대로 쓴다 (1=낮음 · 2=중간 · 3=높음)
ACTIONS = [
    {"key": "unpublish", "label": "비공개", "burden": 1},
    {"key": "activity_meta", "label": "위치태그 제거", "burden": 2},
    {"key": "rewrite", "label": "리라이트(명시)", "burden": 3},
]
BURDEN_LABEL = {1: "낮음", 2: "중간", 3: "높음"}


def load_row() -> dict:
    if not EXP10_INPUTS.exists():
        sys.exit(f"{EXP10_INPUTS} 가 없다 — 위 docstring 의 build_inputs.py 를 먼저 실행한다")
    with EXP10_INPUTS.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["persona_id"] == PERSONA:
                return row
    sys.exit(f"{EXP10_INPUTS} 에 {PERSONA} 가 없다")


def hand_picked_risk(row: dict) -> float:
    """exp10 과 같은 condition 집합에서 HAND_PICKED_POST 한 편만 숨겼을 때의 위험도."""
    kept = [c for c in row["baseline"]["conditions"]
            if c["source_post_ids"] != [HAND_PICKED_POST]]
    return round(risk_total(kept), 2)


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build_svg(curve: list[dict], per_action: list[dict], contrast: dict) -> str:
    w, h = 900, 380
    pad_l, pad_t, plot_w, plot_h = 60, 50, 330, 250

    def y_risk(risk: float) -> float:
        return pad_t + plot_h * (1 - risk / 100)

    def y_effect(effect: float) -> float:
        return pad_t + plot_h * (1 - effect / 50)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="Pretendard, Malgun Gothic, sans-serif" font-size="12">',
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        f'<text x="{w / 2}" y="24" text-anchor="middle" font-size="15" font-weight="700">'
        f'exp8 축약판 — {PERSONA} 조치 곡선 (위험도 0~100 · exp10 정의)</text>',
    ]

    # 왼쪽: 누적 적용 곡선
    x0 = pad_l
    parts.append(f'<text x="{x0 + plot_w / 2}" y="{pad_t - 10}" text-anchor="middle" '
                 f'font-weight="600">① 조치를 차례로 누적 적용</text>')
    for tick in (0, 25, 50, 75, 100):
        y = y_risk(tick)
        parts.append(f'<line x1="{x0}" y1="{y}" x2="{x0 + plot_w}" y2="{y}" stroke="#eee"/>')
        parts.append(f'<text x="{x0 - 8}" y="{y + 4}" text-anchor="end" fill="#777">{tick}</text>')
    step_w = plot_w / (len(curve) - 1)
    points = [(x0 + i * step_w, y_risk(c["risk"])) for i, c in enumerate(curve)]
    parts.append('<polyline fill="none" stroke="#D8896F" stroke-width="2.5" points="'
                 + " ".join(f"{x:.1f},{y:.1f}" for x, y in points) + '"/>')
    for (x, y), c in zip(points, curve):
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#D8896F"/>')
        parts.append(f'<text x="{x:.1f}" y="{y - 10:.1f}" text-anchor="middle" '
                     f'font-weight="700">{c["risk"]}</text>')
        parts.append(f'<text x="{x:.1f}" y="{pad_t + plot_h + 18}" text-anchor="middle" '
                     f'fill="#555">{c["short"]}</text>')

    # 오른쪽: 조치 유형별 (부담, 단독 효과) + 대조 사례
    x1 = pad_l + plot_w + 120
    parts.append(f'<text x="{x1 + plot_w / 2}" y="{pad_t - 10}" text-anchor="middle" '
                 f'font-weight="600">② 조치 유형별 (부담, 단독 효과)</text>')
    for tick in (0, 25, 50):
        y = y_effect(tick)
        parts.append(f'<line x1="{x1}" y1="{y}" x2="{x1 + plot_w}" y2="{y}" stroke="#eee"/>')
        parts.append(f'<text x="{x1 - 8}" y="{y + 4}" text-anchor="end" fill="#777">−{tick}</text>')
    for burden, label in BURDEN_LABEL.items():
        x = x1 + plot_w * (burden - 0.5) / 3
        parts.append(f'<text x="{x:.1f}" y="{pad_t + plot_h + 18}" text-anchor="middle" '
                     f'fill="#555">부담 {label}</text>')
    for a in per_action:
        x = x1 + plot_w * (a["burden"] - 0.5) / 3
        y = y_effect(a["effect_solo"])
        effect = f"−{a['effect_solo']}" if a["effect_solo"] else "0"
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#3E3A36"/>')
        parts.append(f'<text x="{x:.1f}" y="{y - 12:.1f}" text-anchor="middle" '
                     f'font-weight="700">{a["label"]} {effect}</text>')
    # 대조: 손으로 고른 한 편 — 같은 부담(비공개)인데 효과는 0
    x = x1 + plot_w * 0.5 / 3
    y = y_effect(contrast["effect"])
    parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#fff" stroke="#A89B91" stroke-width="2"/>')
    parts.append(f'<text x="{x - 40:.1f}" y="{y - 30:.1f}" fill="#8a7f76">'
                 f'대조: {contrast["post_id"]} 1편만 숨김 {contrast["effect"] or 0}</text>')

    parts.append(f'<text x="{w / 2}" y="{h - 10}" text-anchor="middle" fill="#888" font-size="11">'
                 f'수치 출처: exp10 inputs_full D12 행 (비공개 = LOO 탐욕 경로 · 위치태그 = seed_sns geo_tag · '
                 f'리라이트 = 명시 단서 교체) · 부담 = plan.md §2</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    row = load_row()
    preview = row["preview"]
    cum, solo = preview["cumulative"], preview["solo"]
    baseline = cum["baseline"]
    hidden = row["actions"][0]["post_ids"]

    curve = [
        {"step": 0, "applied": [], "short": "조치 없음", "risk": baseline},
        {"step": 1, "applied": ["unpublish"], "short": f"+비공개 {len(hidden)}편",
         "risk": cum["after_unpublish"]},
        {"step": 2, "applied": ["unpublish", "activity_meta"], "short": "+위치태그 제거",
         "risk": cum["after_meta"]},
        {"step": 3, "applied": ["unpublish", "activity_meta", "rewrite"], "short": "+리라이트(명시)",
         "risk": cum["after_rewrite"]["explicit"]},
    ]
    solo_risk = {
        "unpublish": solo["unpublish"],
        "activity_meta": solo["activity_meta"],
        "rewrite": solo["rewrite"]["explicit"],
    }
    per_action = []
    for i, a in enumerate(ACTIONS):
        per_action.append({
            "action": a["key"],
            "label": a["label"],
            "burden": a["burden"],
            "burden_label": BURDEN_LABEL[a["burden"]],
            "risk_solo": solo_risk[a["key"]],
            "effect_solo": round(baseline - solo_risk[a["key"]], 2),
            "effect_in_sequence": round(curve[i]["risk"] - curve[i + 1]["risk"], 2),
        })

    contrast_risk = hand_picked_risk(row)
    contrast = {
        "post_id": HAND_PICKED_POST,
        "risk_after_hiding_only_this": contrast_risk,
        "effect": round(baseline - contrast_risk, 2),
        "note": "exp8 초판이 손으로 고른 비공개 대상. 단서(야간·울주·공단 정문·차로)가 전부 다른 글에도 있어 한 편만 숨기면 효과가 없다",
    }

    label_source: dict[str, int] = {}
    for p in row["posts"]:
        label_source[p["label_source"]] = label_source.get(p["label_source"], 0) + 1

    metrics = {
        "experiment": "exp08-actions (축약판)",
        "measured_at": date.today().isoformat(),
        "persona": PERSONA,
        "source": "experiments/exp10-action-repro/data/inputs_full.jsonl 의 D12 행 (build_inputs.py 로 재생성)",
        "definitions": {
            "order": "비공개 → 위치태그 제거 → 리라이트 (exp10 과 같음)",
            "unpublish": "C3 leave_one_out 탐욕 경로 앞 k편 · k_max = round(n×3/19)",
            "activity_meta": "scripts/seed_sns.py 가 붙인 실제 geo_tag condition 제거",
            "rewrite": "명시(explicit) 단서 스팬만 교체 — 본 지표 (weaken·remove 는 참고)",
        },
        "data": {
            "corpus": "v0 · 전체 이력",
            "n_posts": len(row["post_ids"]),
            "label_source": label_source,
            "test_split_sha256_prefix": "9662a167",
        },
        "git_commit": git_commit(),
        "burden_source": "docs/plan.md §2 조치 메뉴 (1=낮음 · 2=중간 · 3=높음)",
        "unpublish": {
            "post_ids": hidden,
            "k_max": row["actions"][0]["k_max"],
            "stalled": row["actions"][0]["stalled"],
        },
        "geo_tags": {p["post_id"]: p["geo_tag"] for p in row["posts"] if p.get("geo_tag")},
        "curve": [{k: v for k, v in c.items() if k != "short"} for c in curve],
        "per_action": per_action,
        "rewrite_modes_reference": {
            "cumulative_after_rewrite": cum["after_rewrite"],
            "solo": solo["rewrite"],
        },
        "contrast_hand_picked": contrast,
    }

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "action_curve.svg").write_text(build_svg(curve, per_action, contrast), encoding="utf-8")

    for c in curve:
        print(f"{c['step']} {c['short']}: {c['risk']}")
    for a in per_action:
        print(f"  {a['label']}: 부담 {a['burden_label']} · 단독 효과 {a['effect_solo']} "
              f"· 순서 안 효과 {a['effect_in_sequence']}")
    print(f"  대조 {HAND_PICKED_POST} 1편만 숨김: {contrast_risk} (효과 {contrast['effect']})")


if __name__ == "__main__":
    main()
