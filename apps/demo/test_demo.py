"""파도풀 데모 테스트 — 엔진 숫자 · 계약 대조 · 계층 경계.

    python -m pytest apps/demo/test_demo.py -v

SNS 를 띄우지 않는다. export JSON 을 코퍼스 D05 에서 직접 만든다 (apps/sns/test_export.py 와 같은 형식).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from engine.detect import detect_post, detect_profile  # noqa: E402
from engine.pipeline import analyze, compute  # noqa: E402
from engine.recommend import recommend, stage2_output  # noqa: E402

USER_REF = "u_d05a11c2"


def d05_export(geo_tag: str | None = "담양군 창평면") -> dict:
    posts = [json.loads(l) for l in (ROOT / "data/corpus/v0/posts/D05.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    posts.sort(key=lambda p: p["post_id"])
    out, tagged = [], False
    for p in posts:
        t, geo = p["texts"], None
        if geo_tag and not tagged and p["kind"] == "ambient":
            geo, tagged = geo_tag, True
        caps = [{"caption": t[k]} for k in sorted(k for k in t if k.startswith("photo_caption"))]
        out.append({"post_id": p["post_id"], "user_ref": USER_REF, "title": t.get("title"), "body": t["body"],
                    "photos": caps, "activity_meta": {"nickname": "마당일기", "geo_tag": geo, "post_time": p["created_at"][11:16]}})
    return {"schema_version": "1.0", "user_ref": USER_REF, "nickname": "마당일기",
            "profile_bio": "손녀가 맹글어 줬다. 시골서 그냥 소일한다", "posts": out}


@pytest.fixture(scope="module")
def scan():
    view = analyze(d05_export())
    base = compute(view)
    rec = recommend(view, base)
    return view, base, rec, stage2_output(view, base, rec)


# ── 숫자 — 실제 인구표 (행안부 주민등록 2026-07) ─────────────────────────
def test_k_with_geo_tag_is_changpyeong_65_69(scan):
    _, base, _, _ = scan
    assert base["k"] == 421                      # 창평면 · 65~69세 · 남녀 합산 (성별 기권)
    assert base["k_level"] == "ACCEPTABLE"       # C 계약 경계 k>=5
    axes = [s["axis"] for s in base["steps"]]
    assert axes == ["nation", "location", "location", "location", "age", "sex"]
    assert base["steps"][-1]["method"] == "abstain"


def test_geo_tag_off_widens_to_honam_myeon():
    base = compute(analyze(d05_export(geo_tag=None)))
    assert base["k"] == 111_069                  # 호남 면 지역 · 65~69세
    kinds = [s.get("kind") for s in base["steps"] if s["axis"] == "location"]
    assert kinds == ["dialect_region", "admin_unit"]


def test_hiding_explicit_age_falls_back_to_senior_center():
    """암묵-only ablation (D05 설계 의도): b14 「예순여덟」 을 빼면 b08 「경로당」 이 65세 이상을 준다."""
    view = analyze(d05_export())
    base = compute(view, exclude_posts=frozenset({"D05_b14"}))
    age = [s for s in base["steps"] if s["axis"] == "age"][0]
    assert "65세 이상" in age["condition"] and age["src"]["post_id"] == "D05_b08"
    assert base["k"] == 1473


# ── 함정 — 지명이 나와도 현 거주지가 아니다 ──────────────────────────────
def test_traps_are_excluded_from_k(scan):
    view, base, _, _ = scan
    notes = {sid: n for p in view["posts"] for sid, n in p["notes"].items()}
    spans = {sp["span_id"]: sp for p in view["posts"] for sp in p["spans"]}
    past = [sid for sid, n in notes.items() if n.get("exclude") == "past_residence"]
    assert past and spans[past[0]]["text"] == "광주" and past[0].startswith("D05_b17")      # 시제로만 걸러진다
    other = [sid for sid, sp in spans.items() if sp["type"] == "LOC_ADMIN" and sp["subject"] == "other"]
    assert {spans[s]["text"] for s in other} == {"여수", "해남"}                           # §4-2 귀속
    used = {s["src"]["span_id"] for s in base["steps"] if s.get("src") and s["src"].get("span_id")}
    assert not (used & set(past)) and not (used & set(other))


# ── 조치 — 예상값은 계산값이다 ───────────────────────────────────────────
def test_actions_sorted_by_burden_and_meta_first(scan):
    _, base, rec, _ = scan
    kinds = [a["action_type"] for a in rec["actions"]]
    assert kinds[0] == "activity_meta" and kinds.count("rewrite") >= 1
    burdens = [a["burden"] for a in rec["actions"]]
    order = {"low": 0, "medium": 1, "high": 2}
    assert burdens == sorted(burdens, key=order.__getitem__)
    meta = rec["actions"][0]
    assert meta["_k"] == 111_069 and meta["projected_delta"] < 0
    assert rec["exceptional"] == []                                   # 삭제 권고는 기본 추천에 없다
    assert rec["projected_k"] > base["k"]


def test_rewrite_has_three_candidates_per_span(scan):
    _, _, rec, _ = scan
    by_span: dict[str, list] = {}
    for r in rec["rewrites"]:
        by_span.setdefault(r["span_id"], []).append(r)
    assert by_span and all(len(v) == 3 for v in by_span.values())
    b03 = by_span.get("D05_b03_s01")
    assert b03 and b03[0]["suggestion"] == "버스가 하도 안 와서"
    assert "면사무소" not in b03[0]["_new_sentence"]


# ── 계약 대조 ───────────────────────────────────────────────────────────
def _validator(schema):
    import jsonschema
    return jsonschema.Draft202012Validator(schema)


def test_stage2_output_matches_contract(scan):
    _, _, _, out = scan
    schema = json.loads((ROOT / "docs/contracts/stage2-io.schema.json").read_text(encoding="utf-8"))
    _validator({"$defs": schema["$defs"], "$ref": "#/$defs/Stage2Output"}).validate(out)
    assert out["findings"]["sex"]["verdict"] == "abstain"
    assert out["findings"]["location"]["granularity"] == "eupmyeondong"
    assert out["provenance"]["external_llm_used"] is False


def test_span_records_match_contract():
    schema = json.loads((ROOT / "docs/contracts/span.schema.json").read_text(encoding="utf-8"))
    v = _validator(schema)
    ex = d05_export()
    for p in ex["posts"]:
        rec = detect_post(p)
        v.validate(rec["record"])
        for sp in rec["record"]["spans"]:                              # text == texts[text_id][start:end]
            assert rec["texts"][sp["text_id"]][sp["start"]:sp["end"]] == sp["text"]
    v.validate(detect_profile(USER_REF, ex["profile_bio"])["record"])


# ── 계층 경계 — 분석기는 DB·파일을 안 만지고 SNS 를 직접 바꾸지 않는다 ────
def _code_only(text: str) -> str:
    """주석·독스트링을 뺀 코드만 — 설명 문장 속 단어에 걸리지 않게."""
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))


def test_analyzer_never_touches_sns_db_or_writes_platform():
    files = [HERE / "app.py", *sorted((HERE / "engine").glob("*.py"))]
    src = "".join(_code_only(f.read_text(encoding="utf-8")) for f in files)
    assert "sqlite3" not in src and "sns.db" not in src and "apps/sns" not in src and "/sns" not in src
    assert not re.search(r"requests\.(post|put|patch|delete)\([^)]*SNS_URL", src)   # SNS 에 쓰는 호출이 없다
    assert re.search(r"requests\.get\(f\"\{SNS_URL\}/api/export/", src)              # 읽는 창구는 export 하나
    # 외부 호출은 external.py 한 파일에서만 (E-system.md §2)
    for f in files:
        if f.name != "external.py":
            assert "api.openai.com" not in f.read_text(encoding="utf-8") and "requests.post(" not in _code_only(f.read_text(encoding="utf-8"))


def test_external_llm_is_off_by_default(monkeypatch):
    from engine import external
    monkeypatch.delenv("DEMO_EXTERNAL_REWRITE", raising=False)
    assert external.enabled() is False
    assert external.rewrite_candidates("x", "x", "x") is None
