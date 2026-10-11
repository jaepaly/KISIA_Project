"""회귀 테스트 ③ 네거티브 — 잡담만 쓴 계정의 위험도가 낮다 (howto/c-engine.md §6 · exp23).

골드 라벨(모델 없이 재현)로 잰다. 기준: 잡담 계정 115개의 위험 중앙값 < 15, 그리고 같은 인물의 계정 전체보다
확실히 낮다 — 엔진이 「아무 글에나 위험하다고 하지 않는다」. PoC 의 N1(인물 1명) 기준을 그대로 대신하지는 않는다 (exp23 README).
"""
import importlib.util
import json
import statistics
from pathlib import Path

from kopl.c2_specificity import risk_total
from kopl.c2_specificity.k_engine import conditions_from_posts

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("exp23_run", ROOT / "experiments/exp23-negative-control/run.py")
exp23 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(exp23)


def _risk(posts, spans):
    return risk_total(conditions_from_posts(
        [{"post_id": p["post_id"], "spans": spans.get(p["post_id"], []), "geo_tag": None} for p in posts]))


def test_negative_control_accounts_have_low_risk():
    spans = exp23.gold_spans()
    negative = exp23.negative_posts()
    assert len(negative) == 115

    neg = [_risk(ps, spans) for ps in negative.values()]
    assert statistics.median(neg) < 15.0          # 측정 10/11: 5.71

    full = []
    for f in sorted((ROOT / "data/corpus/v0/posts").glob("*.jsonl")):
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
        posts = [r for r in rows if "post_id" in r]
        if posts:
            full.append(_risk(posts, spans))
    assert statistics.median(full) >= 3 * statistics.median(neg)   # 측정 10/11: 45.0 vs 5.71
