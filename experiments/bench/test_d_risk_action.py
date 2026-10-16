"""d_risk_action 테스트 — 가짜 3명 · 손으로 계산되는 장난감 엔진으로 숫자를 검증한다.

장난감 엔진: 스팬 하나 → 조건 하나 (축 = type · 해상도 explicit 2 / 그 외 1) · 위치태그 → LOC 해상도 3.
위험도 = 축별 최고 해상도 × 10 의 합. 추천(recommend) · LOO 는 실제 코드를 그대로 탄다.

    U1: U1_a AGE explicit · U1_b JOB implicit → 20 + 10 = 30 (글 하나씩: 20 · 10)
    U2: U2_a LOC_ADMIN explicit + 위치태그 → LOC max(2, 3) = 30 (스팬만 20)
    U3: 스팬 없음 → 0 (조치·ablation 에서 제외) · 골드 파일 없음
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import d_risk_action as d  # noqa: E402


def _cond(spans, pid):
    return [{"axis": s["type"], "resolution": 2 if s.get("level") == "explicit" else 1, "source_post_ids": [pid]}
            for s in spans]


def _geo(tag, pid):
    return {"axis": "LOC_ADMIN", "resolution": 3, "source_post_ids": [pid]}


def _risk(conds):
    best: dict[str, int] = {}
    for c in conds:
        best[c["axis"]] = max(best.get(c["axis"], 0), c["resolution"])
    return 10.0 * sum(best.values())


TOY = (_cond, _geo, _risk)
GEO = {"U2_a": "어딘가구"}
TEST_IDS = frozenset({"U9_x"})


def _span(t, level, text="x"):
    return {"text_id": "body", "start": 0, "end": len(text), "type": t, "text": text, "level": level, "subject": "self"}


PRED = {
    "U1_a": [_span("AGE", "explicit")],
    "U1_b": [_span("JOB", "implicit")],
    "U2_a": [_span("LOC_ADMIN", "explicit")],
    "U3_a": [],
}
GOLD = {
    "U1": {"U1_a": [_span("AGE", "explicit")], "U1_b": []},
    "U2": {"U2_a": [_span("LOC_ADMIN", "explicit")]},
}


@pytest.fixture()
def files(tmp_path):
    preds = tmp_path / "preds.jsonl"
    preds.write_text("".join(json.dumps({"post_id": k, "spans": v}, ensure_ascii=False) + "\n"
                             for k, v in PRED.items()), encoding="utf-8")
    gold = tmp_path / "gold"
    gold.mkdir()
    for persona, rows in GOLD.items():
        lines = [json.dumps({"schema_version": "1.0"})]
        lines += [json.dumps({"post_id": pid, "persona_id": persona, "spans": s}, ensure_ascii=False)
                  for pid, s in rows.items()]
        (gold / f"{persona}_spans.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # blind 는 읽지 않는다 — 다른 값을 넣어 두고 결과에 안 섞이는지 본다
    (gold / "blind").mkdir()
    (gold / "blind" / "U1_spans.jsonl").write_text(
        json.dumps({"post_id": "U1_b", "spans": [_span("FAM", "explicit")]}) + "\n", encoding="utf-8")
    return preds, gold, tmp_path / "out"


def _run(files, **kw):
    preds, gold, out = files
    return d.run_risk_action(preds, out, gold_dir=gold, geo_tags=GEO, engine=TOY, test_ids=TEST_IDS, **kw)


def test_risk_per_user(files):
    r = _run(files)
    by = {u["user"]: u for u in r["per_user"]}
    assert (by["U1"]["pred_risk"], by["U1"]["gold_risk"]) == (30.0, 20.0)
    assert (by["U2"]["pred_risk"], by["U2"]["gold_risk"]) == (30.0, 30.0)
    assert (by["U2"]["pred_risk_spans_only"], by["U2"]["n_tagged"]) == (20.0, 1)
    assert by["U3"]["pred_risk"] == 0.0 and "gold_risk" not in by["U3"]


def test_risk_vs_gold(files):
    r = _run(files)["risk"]
    v = r["vs_gold"]
    assert v["n_users"] == 2
    assert v["mae"] == 5.0                      # |30-20| · |30-30|
    assert (v["pred_gt_gold"], v["pred_lt_gold"]) == (0.5, 0.0)
    assert v["pred_vs_gold_risk_spearman"] is None            # 예측 쪽이 30 · 30 동률 — 순위가 없다
    assert r["skipped_users"]["no_gold_file"] == 1  # U3


def test_action_reduction(files):
    a = _run(files)["action"]
    # U1: 2편 → 비공개 1편(LOO greedy 가 U1_a 를 고른다) → 10 · 감소 66.67%
    # U2: 1편이라 비공개 없음 → 위치태그 떼기 20 → 리라이트(명시 지움) 0 · 감소 100%
    assert a["n_users"] == 2 and a["n_zero_baseline_excluded"] == 1
    assert a["full_reduction_pct"] == {"n": 2, "mean": 83.34, "median": 83.34}
    assert a["full_step_users"] == {"unpublish": 1, "activity_meta": 1, "rewrite": 1}
    # 앱 기본 목표 40 — 둘 다 이미 30 이라 조치가 없다
    assert a["app_target_reduction_pct"]["mean"] == 0.0 and a["app_target_met_ratio"] == 1.0


def test_ablation_single_vs_account(files):
    preds, _, out = files
    r = d.run_ablation("single_vs_account", preds, out, geo_tags=GEO, engine=TOY, test_ids=TEST_IDS)
    s = r["summary"]["with_geo"]
    # U1: 글 하나씩 20 · 10 → 최댓값 20, 계정 30 → +10 · U2: 1편이라 같다 · U3 제외
    assert (s["n_users"], s["n_zero_excluded"]) == (2, 1)
    assert s["raised_ratio"] == 0.5
    assert s["raise_among_raised"] == {"n": 1, "mean": 10.0, "median": 10.0}
    assert (out / "ablation_single_vs_account.json").exists()


def test_ablation_explicit_removed(files):
    preds, _, out = files
    r = d.run_ablation("explicit_removed", preds, out, geo_tags=GEO, engine=TOY, test_ids=TEST_IDS)
    g, s = r["summary"]["with_geo"], r["summary"]["spans_only"]
    # 위치태그 포함: U1 30 → 10 (66.67%) · U2 30 → 30 (태그가 남는다 · 0%)
    assert g["reduction_pct"]["median"] == 33.33 and g["pooled_reduction_pct"] == 33.33
    # 스팬만: U1 30 → 10 · U2 20 → 0
    assert s["after_mean"] == 5.0 and s["reduction_pct"]["mean"] == 83.33


def test_unknown_ablation(files):
    preds, _, out = files
    with pytest.raises(ValueError):
        d.run_ablation("nope", preds, out, geo_tags=GEO, engine=TOY, test_ids=TEST_IDS)


def test_test_posts_stop(files, tmp_path):
    preds, gold, out = files
    with preds.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"post_id": "U9_x", "spans": []}) + "\n")
    with pytest.raises(ValueError, match="test"):
        _run(files)
    with pytest.raises(ValueError, match="test"):
        d.run_ablation("explicit_removed", preds, out, geo_tags=GEO, engine=TOY, test_ids=TEST_IDS)
    r = _run(files, allow_test=True)  # 명시 플래그가 있을 때만 통과
    assert r["meta"]["n_users"] == 4


def test_meta_and_filters(files):
    r = _run(files, post_ids=["U1_a", "U1_b"])
    m = r["meta"]
    assert (m["n_users"], m["n_posts"]) == (1, 2)
    assert len(m["preds_sha256"]) == 64 and m["measured_at"] and m["git_commit"]
    json.dumps(r)  # 직렬화 가능
    assert _run(files, limit_users=2)["meta"]["n_users"] == 2


def test_real_test_ids_file():
    # 실제 파일은 dict — 목록은 post_ids 이고 255 편
    ids = d.load_test_ids()
    assert len(ids) == 255 and all("_" in i for i in ids)


def test_spearman():
    assert d.spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)
    assert d.spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert d.spearman([1, 2, 2], [1, 2, 3]) == pytest.approx(0.8660254)


def test_app_engine_smoke():
    # 실제 앱 경로 — 명시 나이 단서 하나면 위험도가 0 보다 크다
    post = {"post_id": "A01_zz", "spans": [_span("AGE", "explicit", "마흔여덟")], "geo_tag": None}
    assert d.user_risk([post], d.app_engine()) > 0
