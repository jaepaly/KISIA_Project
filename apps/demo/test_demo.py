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
from engine.recommend import ladder_candidates, recommend, stage2_output  # noqa: E402

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


# ── 파도풀 API — 우리뜰이 붙여 쓰는 창구 ─────────────────────────────────
@pytest.fixture(scope="module")
def client():
    # `from app import app` 은 apps/sns/test_export.py 가 먼저 등록한 SNS 앱과 이름이 겹친다 — 경로로 직접 읽는다
    import importlib.util
    spec = importlib.util.spec_from_file_location("padopool_app", HERE / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pado = mod.app
    pado.config["TESTING"] = True
    with pado.test_client() as c:
        yield c


def test_api_scan_returns_platform_payload_and_contract(client):
    r = client.post("/api/scan", json=d05_export())
    assert r.status_code == 200
    j = r.get_json()
    assert j["k"] == 421 and j["actions"][0]["action_type"] == "activity_meta"
    assert j["evidence"] and "<mark" in "".join(ch["html"] for c in j["evidence"] for ch in c["channels"])
    assert j["stage2"]["schema_version"] == "0.1.0" and j["rewrites"]
    assert client.post("/api/scan", json={"nope": 1}).status_code == 400


def test_api_check_shows_draft_narrowing(client):
    ex = d05_export(geo_tag=None)                       # 태그 없는 상태: 111,069
    leak = {"title": "구월 사흗날", "body": "오늘도 면사무소 앞에서 기다렸는디 버스가 한 시간에 한 대라 그냥 걸어왔다.\n예순여덟인디 아직 걸을 만 하다.",
            "photos": [], "activity_meta": {"geo_tag": "담양군 창평면"}}
    j = client.post("/api/check", json={"export": ex, "draft": leak}).get_json()
    assert j["before"]["k"] == 111_069 and j["after"]["k"] == 421 and j["narrows"] is True
    assert j["draft"]["n_spans"] >= 2 and any(s["src"]["post_id"] == "draft" for s in j["contributing"])
    noise = {"title": None, "body": "된장국이 짜서 물을 부었다.\n그래도 먹을 만은 했다^^", "photos": [], "activity_meta": {}}
    j = client.post("/api/check", json={"export": ex, "draft": noise}).get_json()
    assert j["after"]["k"] == j["before"]["k"] and j["draft"]["n_spans"] == 0 and j["narrows"] is False


def test_external_llm_is_off_by_default(monkeypatch):
    from engine import external
    monkeypatch.delenv("DEMO_EXTERNAL_REWRITE", raising=False)
    assert external.enabled() is False
    assert external.rewrite_candidates("x", "x", "x") is None


# ── 9/10 피드백 반영분 ────────────────────────────────────────────────────────
def _spans(text: str) -> list[str]:
    r = detect_post({"post_id": "x", "title": None, "body": text, "photos": [], "activity_meta": {}})
    return [s["text"] for s in r["record"]["spans"]]


def test_stoplisted_short_place_counts_only_with_residence_context():
    """「강남에 산다」 는 잡고, 「강남 스타일」「한동안」 은 안 잡는다 — 스톱리스트 약칭은 거주 서술이 붙을 때만."""
    assert _spans("난 강남에 산다") == ["강남"]
    assert _spans("난 경남에 산다") == ["경남"]
    assert _spans("화성에 산 지 오래") == ["화성"]
    assert _spans("강남 스타일이 유행이다") == []
    assert _spans("한동안 강남 갔다") == []


def test_unpublish_action_says_which_clues_vanish(scan):
    _, _, rec, _ = scan
    acts = [a for a in rec["actions"] if a["action_type"] == "unpublish"]
    assert acts and isinstance(acts[0]["_cut"], list)
    rws = rec["rewrites"]
    assert rws and all(r["_span_text"] in r["_sentence"] for r in rws)


def test_api_scan_actions_carry_post_and_cut(client):
    j = client.post("/api/scan", json=d05_export()).get_json()
    for a in j["actions"]:
        assert "post" in a and "cut" in a
        if a["action_type"] in ("unpublish", "activity_meta"):
            assert a["post"].get("title") is not None
    for sid, cands in j["rewrites"].items():
        assert all(c["span_text"] in c["sentence"] for c in cands)


# ── 역 사전 (E 피드백 9/10: 「용마산역」 이 안 잡혔다) ──────────────────────────
def _post(body: str) -> dict:
    return {"post_id": "p1", "title": None, "body": body, "photos": [], "activity_meta": {},
            "created_at": "2026-01-01T00:00:00+09:00", "visibility": "public"}


def _export(body: str) -> dict:
    return {"schema_version": "1.0", "user_ref": "u_t", "nickname": "t", "profile_bio": None, "posts": [_post(body)]}


def test_station_name_resolves_to_dong_and_narrows_k():
    r = detect_post(_post("용마산역 근처에 산다. 태릉입구에서 7호선 타고 출근."))
    got = {s["text"]: (s["type"], r["notes"].get(s["span_id"], {}).get("place")) for s in r["record"]["spans"]}
    assert got["용마산역"] == ("LOC_FACILITY", "서울특별시 중랑구 면목제4동")
    assert got["태릉입구"][0] == "LOC_FACILITY" and got["태릉입구"][1].endswith("공릉1동")
    base = compute(analyze(_export("용마산역 근처에 산다. 서른셋이다.")))
    steps = {s["condition"]: s["n_after"] for s in base["steps"]}
    assert any("용마산역" in c for c in steps) and base["k"] < 5000


def test_station_same_name_in_many_cities_is_not_counted():
    r = detect_post(_post("시청역에서 만나자"))
    n = r["notes"][r["record"]["spans"][0]["span_id"]]
    assert n["exclude"] == "ambiguous" and "역이" in n["why"]
    assert detect_post(_post("울역에 갔다"))["record"]["spans"] == []          # 「서울역」 안쪽 부분 일치 금지


def test_station_ladder_widens_to_gu_then_city():
    view = analyze(_export("용마산역 근처에 산다."))
    p = view["posts"][0]
    sp = p["spans"][0]
    ladder = ladder_candidates(view, "p1", sp, p["notes"][sp["span_id"]])
    assert [l["text"] for l in ladder] == ["중랑구", "서울"]
    assert ladder[0]["k"] < ladder[1]["k"]
