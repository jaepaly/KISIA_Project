"""estimate_k — 여러 글의 조건을 엮은 k (#302).

실행:
    python -m pytest src/kopl/c2_specificity/test_k_engine.py -v
"""

import json
from pathlib import Path

import pytest

from kopl.c2_specificity.engine import specificity_l1
from kopl.c2_specificity.k_engine import (
    age_bands,
    conditions_from_posts,
    estimate_k,
    sex_of,
    specificity_document,
)

ROOT = Path(__file__).resolve().parents[3]


def S(text, typ, level="explicit", subject="self"):
    return {"span_id": f"s_{typ}_{text}", "text_id": "body", "start": 0, "end": len(text), "text": text,
            "type": typ, "level": level, "subject": subject}


def k_of(*posts):
    return estimate_k(conditions_from_posts(
        [{"post_id": f"p{i}", "spans": spans} for i, spans in enumerate(posts)]))


@pytest.mark.parametrize("loc,age,sex,word", [
    ("역삼동", 47, "F", "여자"),   # 법정동 → 행정동 둘 (legal_expansion)
    ("신갈동", 42, "M", "남자"),
    ("강남구", 33, "F", "여자"),   # 시군구 → 하위 동 합산
    ("효자동", 17, "F", "여자"),
])
def test_matches_specificity_l1_on_l1_inputs(loc, age, sex, word):
    """지역·나이·성별만 있으면 기존 L1 과 같은 k — 기존 수치와 어긋나지 않는다."""
    out = k_of([S(loc, "LOC_ADMIN"), S(f"{age}세", "AGE"), S(word, "SEX")])
    assert out["k"] == specificity_l1(loc, age, sex)["k"]


def test_k_decreases_as_posts_accumulate():
    """데모 피드백 — 글이 쌓이면 k 가 내려가야 한다."""
    posts = [[S("강남구", "LOC_ADMIN")], [S("선릉역", "LOC_FACILITY")],
             [S("마흔여덟", "AGE"), S("남편", "SEX")], [S("간호사", "JOB")]]
    ks = [k_of(*posts[: i + 1])["k"] for i in range(len(posts))]
    assert all(a > b for a, b in zip(ks, ks[1:])), ks


def test_locations_from_different_posts_intersect():
    """「서울」(글 1) 과 「중구」(글 2) — 둘 다 단독으로는 넓거나 동명이지만, 겹치면 서울 중구."""
    both = k_of([S("서울", "LOC_ADMIN")], [S("중구", "LOC_ADMIN")])
    seoul = k_of([S("서울", "LOC_ADMIN")])
    junggu = k_of([S("중구", "LOC_ADMIN")])
    assert both["k"] < seoul["k"] and both["k"] < junggu["k"]
    assert any("동명 지명" in a for a in both["assumptions"])


def test_conflicting_location_is_skipped_not_zero():
    """서로 겹치지 않는 위치(이사·방문)는 k 를 0 으로 만들지 않고 건너뛰며 기록한다."""
    out = k_of([S("신갈동", "LOC_ADMIN")], [S("효자동", "LOC_ADMIN")])
    assert out["k"] is not None and out["k"] >= 1
    assert any("겹치지 않는 위치 단서" in a for a in out["assumptions"])


def test_weak_clue_narrows_less_than_strong():
    strong = k_of([S("강남구", "LOC_ADMIN")], [S("간호사", "JOB", "explicit")])
    weak = k_of([S("강남구", "LOC_ADMIN")], [S("간호사", "JOB", "inferential")])
    base = k_of([S("강남구", "LOC_ADMIN")])
    assert strong["k"] < weak["k"] < base["k"]


def test_other_subject_does_not_count():
    base = k_of([S("강남구", "LOC_ADMIN")])
    other = k_of([S("강남구", "LOC_ADMIN")], [S("간호사", "JOB", "explicit", "other")])
    assert other["k"] == base["k"]


def test_unknown_subject_does_not_count():
    """관계 불명(unknown) 스팬은 k 에 들어가지 않는다 — 사전 밖 지명 해석기(약칭 · 어간) 경로도 같다 (exp43)."""
    base = k_of([S("강남구", "LOC_ADMIN")])
    for extra in ([S("세 살", "AGE", "explicit", "unknown")], [S("남자", "SEX", "explicit", "unknown")],
                  [S("해운대에서", "LOC_ADMIN", "explicit", "unknown")], [S("REL", "REL_WORK", "implicit", "unknown")]):
        assert k_of([S("강남구", "LOC_ADMIN")], extra)["k"] == base["k"], extra
    assert conditions_from_posts([{"post_id": "p", "spans": [S("해운대에서", "LOC_ADMIN", "explicit", "unknown")]}]) == []
    assert conditions_from_posts([{"post_id": "p", "spans": [S("해운대에서", "LOC_ADMIN", "explicit", "self")]}])


def test_ratio_axes_use_one_clue_per_axis():
    """같은 축 단서가 여러 개여도 한 번만 곱한다 (규칙 1) — 같은 직업을 열 번 써도 열 번 깎이지 않는다."""
    once = k_of([S("강남구", "LOC_ADMIN")], [S("간호사", "JOB")])
    many = k_of([S("강남구", "LOC_ADMIN")], *[[S("간호사", "JOB")] for _ in range(10)])
    assert once["k"] == many["k"]


def test_floor_and_contract_shape():
    schema = json.loads((ROOT / "docs/contracts/specificity.schema.json").read_text(encoding="utf-8"))
    jsonschema = pytest.importorskip("jsonschema")
    posts = [[S("역삼동", "LOC_ADMIN")], [S("마흔여덟", "AGE"), S("남편", "SEX")], [S("간호사", "JOB")],
             [S("쌍둥이 둘 다 초3", "FAM")], [S("2호선 출근", "COMMUTE")], [S("연봉 1억", "INCOME")]]
    conds = conditions_from_posts([{"post_id": f"p{i}", "spans": s} for i, s in enumerate(posts)])
    doc = specificity_document("u_0123abcd", conds)
    jsonschema.validate(doc, schema)
    out = doc["output"]
    assert out["k"] >= 1
    assert out["floor_applied"] == (min(s["n_after"] for s in out["steps"]) < 1)


def test_no_conditions_is_unknown():
    out = estimate_k([])
    assert out["k"] is None and out["k_level"] == "UNKNOWN"


def test_unresolvable_location_does_not_narrow():
    out = k_of([S("상하이", "LOC_ADMIN")])
    assert out["k"] == k_of([])["k"] or out["k"] > 50_000_000


def test_geo_tag_is_a_location_clue():
    plain = estimate_k(conditions_from_posts([{"post_id": "p", "spans": []}]))
    tagged = estimate_k(conditions_from_posts([{"post_id": "p", "spans": [], "geo_tag": "강남구"}]))
    assert plain["k"] is None and tagged["k"] < 1_000_000


@pytest.mark.parametrize("text,kind,expected", [
    ("마흔여덟", "age_exact", ["45-49"]),
    ("38세", "age_exact", ["35-39"]),
    ("88년생", "age_exact", ["35-39"]),
    ("삼십팔 세", "age_exact", ["35-39"]),
    ("서른 살", "age_exact", ["25-29", "30-34"]),   # 만 나이·세는 나이가 섞여 경계에서 두 구간
    ("40대", "age_hint", ["40-44", "45-49"]),
    ("20~29세", "age_hint", ["20-24", "25-29"]),
    ("45-49", "age_band", ["45-49"]),
    ("나이 들어서", "age_hint", None),
])
def test_age_bands(text, kind, expected):
    assert age_bands({"kind": kind, "value": text}) == expected


@pytest.mark.parametrize("text,expected", [
    ("엄마", "F"), ("남편이랑", "F"), ("아빠", "M"), ("와이프", "M"), ("배우자", None), ("엄마랑 아빠", None),
])
def test_sex_of(text, expected):
    assert sex_of({"value": text}) == expected


# ── Codex 검토 재현 사례 (회귀) ──────────────────────────────────────────

def C(axis, kind, value=None, conf=1.0, res=2, geo=None, post="p"):
    c = {"axis": axis, "kind": kind, "resolution": res, "confidence": conf, "source_post_ids": [post]}
    if geo:
        c["geo_code"] = geo
    else:
        c["value"] = value
    return c


def test_containing_clue_does_not_raise_k():
    """역삼동(법정동 확장)에 그걸 포함하는 강남구를 더해도 k 는 그대로 — 최소값 규칙이 유지된다."""
    alone = k_of([S("역삼동", "LOC_ADMIN")])
    plus = k_of([S("역삼동", "LOC_ADMIN")], [S("강남구", "LOC_ADMIN")])
    assert plus["k"] == alone["k"]


def test_conflicting_stronger_clue_does_not_raise_k():
    base = estimate_k([C("location", "administrative_area", "역삼1동", conf=0.8)])
    more = estimate_k([C("location", "administrative_area", "역삼1동", conf=0.8),
                       C("location", "administrative_area", "부산", conf=1.0, post="q")])
    assert more["k"] <= base["k"]


def test_broader_age_does_not_widen():
    loc = C("location", "administrative_area", "강남구")
    narrow = estimate_k([loc, C("age", "age_band", "45-49", conf=0.8)])
    both = estimate_k([loc, C("age", "age_band", "45-49", conf=0.8), C("age", "age_hint", "40대", conf=1.0)])
    assert both["k"] <= narrow["k"]


def test_floor_recorded_when_candidate_dong_has_zero():
    """후보 동 인구가 0 이면 하한 1 이 걸렸다고 남긴다 (먼저 1 로 막아 기록이 사라지면 안 된다)."""
    out = estimate_k([C("location", "administrative_area", "상계동"), C("age", "age_band", "100+"),
                      C("sex", "sex", "남자")])
    if out.get("k_min") == 1 and min(out["populations"].values()) == 0:
        assert out["floor_applied"] is True
    assert any(s["method"] == "legal_dong_expansion_min" for s in out["steps"]) or "codes" not in out


def test_weak_nested_locations_apply_once():
    out = estimate_k([C("location", "administrative_area", "서울", conf=0.5),
                      C("location", "administrative_area", "강남구", conf=0.5)])
    assert sum(1 for s in out["steps"] if s["axis"] == "location" and s["method"] == "ratio_damped") == 1


def test_facility_resolution_is_stable():
    """장소 스팬 「일산에서」 — 조건을 만들 때와 계산할 때 같은 해석(역 우선)을 쓴다."""
    from kopl.c2_specificity.k_engine import _default_index, _location_set
    conds = conditions_from_posts([{"post_id": "p", "spans": [S("일산에서", "LOC_FACILITY")]}])
    loc = [c for c in conds if c["axis"] == "location"]
    if loc:
        codes, _ = _location_set(loc[0], _default_index())
        direct, _ = _default_index().resolve_text("일산에서", facility=True)
        assert codes == direct


@pytest.mark.parametrize("text,expected", [
    ("여자친구", None), ("남자친구", None), ("엄마가", "F"), ("신부님", None), ("아내와", "M"),
])
def test_sex_whole_span_only(text, expected):
    assert sex_of({"value": text}) == expected


@pytest.mark.parametrize("text,expected", [
    ("세 살", ["0-4"]), ("다섯 살", ["0-4", "5-9"]), ("만 40세", ["40-44"]), ("27년생", None),
])
def test_age_edge_cases(text, expected):
    assert age_bands({"kind": "age_exact", "value": text}) == expected


def test_only_unresolvable_conditions_is_unknown():
    out = estimate_k([C("location", "administrative_area", "어딘가모를곳")])
    assert out["k"] is None and out["k_level"] == "UNKNOWN"


def test_monotonic_on_real_windows():
    """실제 인물 글로 — 조건을 하나씩 더할 때 k 가 커지는 순간이 없어야 한다 (방어적 최소)."""
    gold = ROOT / "data/corpus/v0/gold"
    checked = 0
    for path in sorted(gold.glob("[A-E]*_spans.jsonl"))[:12]:
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
        posts = [{"post_id": r["post_id"], "spans": r.get("spans") or []} for r in rows if r.get("post_id")][:15]
        conds = conditions_from_posts(posts)
        prev = None
        for i in range(1, len(conds) + 1):
            k = estimate_k(conds[:i])["k"]
            if prev is not None and k is not None:
                assert k <= prev + 1e-6, (path.name, i, prev, k)
            prev = k if k is not None else prev
            checked += 1
    assert checked > 50


# ── 2차 검토 재현 사례 (회귀) ──────────────────────────────────────────

def test_same_place_with_josa_keeps_legal_min():
    alone = estimate_k([C("location", "administrative_area", "역삼동", conf=0.8)])
    both = estimate_k([C("location", "administrative_area", "역삼동", conf=0.8),
                       C("location", "administrative_area", "역삼동에서", conf=1.0, post="q")])
    assert both["k"] <= alone["k"]


@pytest.mark.parametrize("first,second", [
    (C("location", "administrative_area", "강남구", conf=0.5), C("location", "facility", "선릉역", conf=0.4, post="q")),
    (C("occupation", "job_group", "간호사", conf=1.0, res=2), C("occupation", "job_group", "OO병원", conf=0.5, res=3, post="q")),
])
def test_adding_any_clue_never_raises_k(first, second):
    a = estimate_k([C("location", "administrative_area", "서울"), first])
    b = estimate_k([C("location", "administrative_area", "서울"), first, second])
    assert b["k"] <= a["k"]


def test_promotion_by_corroboration_never_raises_k():
    base = [C("location", "administrative_area", "역삼동", post="a"),
            C("location", "administrative_area", "역삼1동", conf=0.5, post="b")]
    more = base + [C("location", "administrative_area", "역삼1동", conf=0.5, post="c")]
    assert estimate_k(more)["k"] <= estimate_k(base)["k"]


def test_many_disjoint_places_keep_smallest():
    """서로 떨어진 동 15곳 — 상한으로 작은 해석을 버리지 않는다."""
    names = ["신갈동", "효자동", "역삼1동", "상계1동", "송도1동", "첨단1동", "덕진동", "화정1동",
             "일산1동", "구월1동", "부평1동", "연산1동", "범어1동", "둔산1동", "봉명동"]
    conds = [C("location", "administrative_area", n, post=f"p{i}") for i, n in enumerate(names)]
    smallest = min(estimate_k([c])["k"] for c in conds)
    assert estimate_k(conds)["k"] <= smallest


def test_many_repeated_clues_are_fast():
    import time
    posts = [[S("만 40세", "AGE"), S("강남구", "LOC_ADMIN")] for _ in range(40)]
    t0 = time.time()
    k_of(*posts)
    assert time.time() - t0 < 2.0


def test_facility_without_home_marker_is_weak():
    """「선릉역」만 한 번 — 사는 곳 단서로 직접 좁히지 않는다 (관계 불명). 「집 근처」가 같은 글에 있으면 직접 좁힌다."""
    visit = k_of([S("서울", "LOC_ADMIN")], [S("선릉역", "LOC_FACILITY")])
    home = k_of([S("서울", "LOC_ADMIN")], [S("선릉역", "LOC_FACILITY"), S("집 근처", "REL_HOME", "inferential")])
    assert home["k"] < visit["k"]


def test_monotonic_random_orders_on_real_personas():
    """실제 인물 20명 × 무작위 순서 3개 — 조건을 하나씩 더할 때 k 가 커지는 순간이 없어야 한다."""
    import random
    gold = ROOT / "data/corpus/v0/gold"
    rng = random.Random(20261005)
    for path in sorted(gold.glob("[A-E]*_spans.jsonl"))[:20]:
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
        conds = conditions_from_posts([{"post_id": r["post_id"], "spans": r.get("spans") or []}
                                       for r in rows if r.get("post_id")])
        for _ in range(3):
            order = conds[:]
            rng.shuffle(order)
            prev = None
            for i in range(1, len(order) + 1):
                k = estimate_k(order[:i])["k"]
                if prev is not None and k is not None:
                    assert k <= prev * (1 + 1e-9) + 1e-6, (path.name, i, prev, k)
                if k is not None:
                    prev = k


def test_first_strong_age_keeps_unconstrained_hypothesis():
    """약한 「100+」 뒤에 넓은 강한 나이(0~99세)가 와도 k 가 커지지 않는다 (3차 검토 반례)."""
    a = estimate_k([C("age", "age_band", "100+", conf=0.79)])
    b = estimate_k([C("age", "age_band", "100+", conf=0.79), C("age", "age_hint", "0~99세", conf=1.0, post="q")])
    assert b["k"] <= a["k"]


def test_legal_min_with_weak_age_and_strong_sex_monotone():
    loc = C("location", "administrative_area", "역삼동")
    a = estimate_k([loc, C("age", "age_band", "45-49", conf=0.5)])
    b = estimate_k([loc, C("age", "age_band", "45-49", conf=0.5), C("sex", "sex", "여자", post="q")])
    assert b["k"] <= a["k"]


def test_never_below_direct_crosstab_on_real_table():
    """위치·나이·성별이 모두 강하면 k 는 주민등록 교차표 직접 조회값 이상 (C 규칙 2) — 실제 인구표 무작위 300개.

    합성 인구표(극단적 상관)에서는 「제한 없음」 가설의 주변 비율 곱이 교차표보다 작아질 수 있다 (exp14 README 한계).
    """
    import random
    from kopl.c2_specificity.k_engine import _BANDS, _default_index
    idx = _default_index()
    rng = random.Random(11)
    emds = list(idx.all_emd)
    for _ in range(300):
        e, b, sx = rng.choice(emds), rng.choice(_BANDS), rng.choice(["F", "M"])
        direct = idx.pop([e], sx, [b])
        if direct < 1:
            continue
        k = estimate_k([C("location", "administrative_area", geo=e, res=3), C("age", "age_band", b),
                        C("sex", "sex", "여자" if sx == "F" else "남자", res=1)])["k"]
        assert k >= direct - 1e-6, (e, b, sx, direct, k)


def test_park_is_not_resolved_as_station():
    """「체육공원」은 같은 이름의 역(체육공원역)이 아니다 — 시설 이름만으로 역 동네를 짚지 않는다."""
    from kopl.c2_specificity.k_engine import _default_index
    codes, how = _default_index().resolve_text("체육공원", facility=True)
    assert how != "station"


def test_k_by_post_removal_never_lowers_k_and_ranks_identifying_posts():
    from kopl.c2_specificity.k_engine import k_by_post
    posts = [
        {"post_id": "a", "spans": [S("역삼동", "LOC_ADMIN")]},
        {"post_id": "b", "spans": [S("마흔여덟", "AGE"), S("남편", "SEX")]},
        {"post_id": "c", "spans": []},
        {"post_id": "d", "spans": [S("간호사", "JOB")]},
    ]
    out = k_by_post(posts)
    assert all(r["k_without"] >= out["k"] for r in out["per_post"])
    assert out["per_post"][0]["post_id"] == "a"            # 동네를 짚는 글이 가장 크게 좁힌다
    assert [r for r in out["per_post"] if r["post_id"] == "c"][0]["gain"] == 1.0   # 단서 없는 글은 k 그대로
    ks = [out["k"]] + [g["k_after"] for g in out["greedy"]]
    assert ks == sorted(ks) and len(out["greedy"]) <= 3


@pytest.mark.parametrize("word,sigungu", [("안동", "안동시"), ("하동", "하동군"), ("강동", "강동구"), ("영동", "영동군")])
def test_sigungu_short_wins_over_same_named_dong(word, sigungu):
    """「안동」은 안동시 — 같은 이름의 동(김해시 안동)으로 좁히지 않는다 (인스턴스 테스트 B18_b10)."""
    from kopl.c2_specificity.k_engine import _default_index
    idx = _default_index()
    got, how = idx.resolve_text(word)
    want, _ = idx.resolve_text(sigungu)
    assert how == "short_alias_homonym" and want <= got and len(got) > len(want)   # 같은 이름의 동도 후보로 남는다


@pytest.mark.parametrize("multi,narrow", [("수원 영통구에", "영통구"), ("경기 수원 영통구", "영통구"), ("용인 기흥구", "기흥구"),
                                          ("대전 유성구 전민동", "전민동")])
def test_multi_token_place_uses_narrowest_word(multi, narrow):
    """여러 단어 지명은 단어마다 해석해 교집합 — 첫 단어(수원 전체)로 넓히지 않는다 (인스턴스 테스트 10/5)."""
    from kopl.c2_specificity.k_engine import _default_index
    idx = _default_index()
    got, _ = idx.resolve_text(multi)
    want, _ = idx.resolve_text(narrow)
    assert got and got == want


def test_bare_number_age_span_narrows():
    """「나이 48에」 — 1단 규칙이 「48에」만 AGE 로 잡는다. 살·세가 없어도 나이로 좁힌다 (인스턴스 비교 측정 10/5)."""
    from kopl.c2_specificity.k_engine import age_bands
    assert age_bands({"axis": "age", "kind": "age_mention", "value": "48에"}) == age_bands({"axis": "age", "kind": "age_exact", "value": "48살"})
    assert age_bands({"axis": "age", "kind": "age_mention", "value": "2024년"}) is None


@pytest.mark.parametrize("multi,narrow", [("울산 일산동에서", "울산 동구 일산동"), ("서울 중앙 쪽에", "서울")])
def test_multi_token_codex_regressions(multi, narrow):
    """Codex 검토(10/5): 「울산 일산동」은 울산의 일산동(고양 아님) · 「서울 중앙」은 중앙동 하나로 좁히지 않는다."""
    from kopl.c2_specificity.k_engine import _default_index
    idx = _default_index()
    got, _ = idx.resolve_text(multi)
    want, _ = idx.resolve_text(narrow)
    assert got == want


def test_collision_name_real_path_keeps_both_readings():
    """Codex 검토(10/5) — 실제 조건 경로에서도 「안동」 단독 스팬이 김해시 안동 하나로 고정되지 않는다 (조사 유무와 같은 결과)."""
    from kopl.c2_specificity.k_engine import conditions_from_posts, estimate_k
    ks = []
    for text in ("안동", "안동에서"):
        c = conditions_from_posts([{"post_id": "p", "spans": [S(text, "LOC_ADMIN")]}])
        ks.append(estimate_k(c)["k"])
    assert ks[0] == ks[1]


def test_collision_name_keeps_risk_resolution():
    """Codex 3차 — 겹치는 지명도 위험도(해상도)는 build_conditions 와 같다 (추천 엔진·exp10 과 일치)."""
    from kopl.c2_specificity.clues import build_conditions
    from kopl.c2_specificity.engine import risk_total
    from kopl.c2_specificity.k_engine import _default_index, conditions_from_posts
    span = S("안동", "LOC_ADMIN")
    assert risk_total(conditions_from_posts([{"post_id": "p", "spans": [span]}])) ==         risk_total(build_conditions([span], "p", dictionary=_default_index().d))
