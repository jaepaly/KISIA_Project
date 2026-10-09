"""2단 실행 경로 검증 — 가짜 모델로 돌린다 (GPU·어댑터 없이).

실행:
    python -m pytest src/kopl/c4_stage2/test_infer.py -v
"""

import json
from pathlib import Path

import pytest

from kopl.c4_stage2.infer import (MODEL_MAX_SPANS, MODEL_MAX_SPANS_PER_TYPE, MODEL_VERSION, RULES_VERSION, analyze,
                                  build_user_prompt, output_budget, select_for_model, validate_findings)
from kopl.c4_stage2.rules import ATTRS, findings_from_spans

USER = "u_0123abcd"
BODY = "마흔여덟 살 간호사예요. 남편이랑 둘이 살아요."


def _posts():
    age, job = BODY.index("마흔여덟"), BODY.index("간호사")
    return [
        {"post_id": "p1", "texts": {"body": BODY}, "geo_tag": None, "spans": [
            {"span_id": "p1_s01", "text_id": "body", "start": age, "end": age + 4, "text": "마흔여덟",
             "type": "AGE", "level": "explicit", "subject": "self"},
            {"span_id": "p1_s02", "text_id": "body", "start": job, "end": job + 3, "text": "간호사",
             "type": "JOB", "level": "explicit", "subject": "self"},
        ]},
        {"post_id": "p2", "texts": {"body": "오늘은 쉬는 날"}, "geo_tag": None, "spans": []},
    ]


class FakeModel:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def generate(self, user_prompt: str) -> str:
        self.prompts.append(user_prompt)
        return self.text


def _abstain():
    return {"verdict": "abstain", "confidence": 0.1, "cross_post": False, "evidence": []}


def _validator():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((Path(__file__).resolve().parents[3] / "docs/contracts/stage2-io.schema.json")
                        .read_text(encoding="utf-8"))
    return lambda out: jsonschema.validate(out, {"$defs": schema["$defs"], "$ref": "#/$defs/Stage2Output"})


def test_prompt_has_no_original_text() -> None:
    prompt, entries = build_user_prompt(USER, _posts())
    assert "마흔여덟" not in prompt and "간호사" not in prompt and BODY not in prompt
    assert {s["span_id"] for e in entries for s in e["spans"]} == {"p1_s01", "p1_s02"}


def test_offset_mismatch_span_is_dropped() -> None:
    posts = _posts()
    posts[0]["spans"][0]["start"] += 1
    _, entries = build_user_prompt(USER, posts)
    assert [s["span_id"] for s in entries[0]["spans"]] == ["p1_s02"]


def test_rules_mode_matches_contract() -> None:
    out = analyze(USER, _posts(), mode="rules", target_risk=0.0)
    _validator()(out)
    assert out["provenance"]["model_version"] == RULES_VERSION
    assert out["findings"]["age"]["verdict"] == "specified"
    assert out["findings"]["sex"]["verdict"] == "abstain"


def test_model_output_is_used_and_hallucinated_evidence_removed() -> None:
    findings = {a: _abstain() for a in ATTRS}
    findings["age"] = {"verdict": "specified", "confidence": 0.9, "cross_post": True,
                       "evidence": [{"post_id": "p1", "span_id": "p1_s01"}, {"post_id": "p9", "span_id": "x"}]}
    findings["income"] = {"verdict": "narrowed", "confidence": 0.7, "cross_post": False,
                          "evidence": [{"post_id": "p1", "span_id": "made_up"}]}
    model = FakeModel("생각 없이 " + json.dumps({"findings": findings, "rewrites": []}, ensure_ascii=False))
    out = analyze(USER, _posts(), model=model, mode="model")
    _validator()(out)
    assert out["provenance"]["model_version"] == MODEL_VERSION
    assert out["findings"]["age"]["evidence"] == [{"post_id": "p1", "span_id": "p1_s01"}]
    assert out["findings"]["age"]["cross_post"] is False  # 남은 근거가 글 1편
    assert out["findings"]["income"]["verdict"] == "abstain"  # 근거가 전부 지어낸 것
    assert out["findings"]["income"]["confidence"] <= 0.25
    assert "마흔여덟" not in model.prompts[0]


def test_unparsable_output_falls_back_to_rules() -> None:
    out = analyze(USER, _posts(), model=FakeModel("모르겠어요"), mode="auto")
    assert out["provenance"]["model_version"].startswith(RULES_VERSION + " (fallback")
    assert out["findings"]["occupation"]["verdict"] == "specified"
    with pytest.raises(RuntimeError):
        analyze(USER, _posts(), model=FakeModel("모르겠어요"), mode="model")


def test_validate_rejects_missing_attr() -> None:
    raw = {a: _abstain() for a in ATTRS if a != "income"}
    assert validate_findings(raw, []) is None


def test_rules_verdict_boundaries() -> None:
    """#279 판정 기준 — 학습 타깃과 같은 규칙."""
    def span(sid, typ, level, subject="self"):
        return {"span_id": sid, "type": typ, "level": level, "subject": subject}

    f = findings_from_spans([
        {"post_id": "a", "spans": [span("a1", "JOB", "inferential"), span("a2", "FAM", "inferential"),
                                   span("a3", "INCOME", "implicit"), span("a4", "AGE", "explicit", "other"),
                                   span("a5", "REL_HOME", "inferential")]},
        {"post_id": "b", "spans": [span("b1", "JOB", "inferential")]},
    ])
    assert f["occupation"]["verdict"] == "narrowed" and f["occupation"]["cross_post"] is True  # 추론 2편
    assert f["income"]["verdict"] == "narrowed"  # 암묵 하나로도
    assert f["age"]["verdict"] == "abstain"  # 남의 나이
    assert f["family"]["verdict"] == "weak_signal"  # FAM·REL_HOME 추론 2개여도 같은 글 1편 → 약한 신호
    assert f["family"]["cross_post"] is False


def test_wrong_attribute_or_other_subject_evidence_is_removed() -> None:
    """있는 span_id 라도 속성이 다르거나 남의 것이면 근거가 아니다 (Codex 반례)."""
    posts = _posts()
    posts[0]["spans"][1]["subject"] = "other"  # 간호사 = 남의 직업
    findings = {a: _abstain() for a in ATTRS}
    findings["income"] = {"verdict": "specified", "confidence": 0.9, "cross_post": False,
                          "evidence": [{"post_id": "p1", "span_id": "p1_s01"}]}  # 나이 스팬을 소득 근거로
    findings["occupation"] = {"verdict": "specified", "confidence": 0.9, "cross_post": False,
                              "evidence": [{"post_id": "p1", "span_id": "p1_s02"}]}
    out = analyze(USER, posts, model=FakeModel(json.dumps({"findings": findings})), mode="model")
    assert out["findings"]["income"]["verdict"] == "abstain"
    assert out["findings"]["occupation"]["verdict"] == "abstain"


@pytest.mark.parametrize("bad", [
    {"verdict": "specified", "confidence": float("nan"), "cross_post": False, "evidence": []},
    {"verdict": [], "confidence": 0.9, "cross_post": False, "evidence": []},
    {"verdict": "specified", "confidence": 0.9, "cross_post": False, "evidence": 1},
    {"verdict": "specified", "confidence": 0.9, "cross_post": False,
     "evidence": [{"post_id": ["p1"], "span_id": "p1_s01"}]},
])
def test_malformed_model_output_falls_back_in_auto(bad) -> None:
    findings = {a: _abstain() for a in ATTRS}
    findings["age"] = bad
    text = json.dumps({"findings": findings}, allow_nan=True)
    out = analyze(USER, _posts(), model=FakeModel(text), mode="auto")
    json.dumps(out, allow_nan=False)  # 응답으로 직렬화 가능해야 한다
    assert out["findings"]["age"]["verdict"] in {"specified", "abstain"}


def test_generation_error_falls_back_in_auto() -> None:
    class Boom:
        def generate(self, _):
            raise RuntimeError("CUDA out of memory")

    out = analyze(USER, _posts(), model=Boom(), mode="auto")
    assert "CUDA out of memory" in out["provenance"]["model_version"]
    with pytest.raises(RuntimeError):
        analyze(USER, _posts(), model=Boom(), mode="model")


def test_no_posts_gives_empty_result() -> None:
    out = analyze(USER, [], mode="rules")
    _validator()(out)
    assert out["recommendation"]["actions"] == []
    assert all(f["verdict"] == "abstain" for f in out["findings"].values())


def test_recommendation_risk_matches_app_conditions() -> None:
    """추천 엔진의 「현재 위험」이 분석 앱(c23 · conditions_from_posts)의 위험도와 같다 (#299 후속).

    「동탄」 「일산」 「수원 영통구」처럼 사전 정식 이름이 아닌 지명은 build_conditions 가 조건을 못 만들어 위험 0 으로 셌다 —
    화면은 7.86 인데 추천 엔진은 0 을 보고 조치를 안 냈다.
    """
    from kopl.c2_specificity.engine import risk_total
    from kopl.c2_specificity.k_engine import conditions_from_posts

    body = "동탄에서 마흔여덟 생일을 보냈다"
    st, ag = body.index("동탄에서"), body.index("마흔여덟")
    posts = [{"post_id": "p1", "texts": {"body": body}, "geo_tag": None, "spans": [
        {"span_id": "p1_s01", "text_id": "body", "start": st, "end": st + 4, "text": "동탄에서",
         "type": "LOC_ADMIN", "level": "explicit", "subject": "self"},
        {"span_id": "p1_s02", "text_id": "body", "start": ag, "end": ag + 4, "text": "마흔여덟",
         "type": "AGE", "level": "explicit", "subject": "self"},
    ]}, {"post_id": "p2", "texts": {"body": "오늘은 쉬는 날"}, "geo_tag": None, "spans": []}]
    app = round(float(risk_total(conditions_from_posts(posts))), 2)
    out = analyze(USER, posts, mode="rules", target_risk=100.0)
    assert out["recommendation"]["projected"]["current_risk"] == app


def _many_posts(n_posts: int = 8):
    """글마다 JOB 5 · FAM 3(같은 「엄마」 되풀이) · COMMUTE 2 — 실제 계정처럼 스팬이 많은 입력"""
    posts = []
    for i in range(n_posts):
        words = [("인턴", "JOB", "inferential"), ("출근", "JOB", "inferential"), ("부장님", "JOB", "inferential"),
                 ("이사님", "JOB", "inferential"), ("간호사", "JOB", "explicit"),
                 ("엄마", "FAM", "inferential"), ("엄마", "FAM", "inferential"), ("엄마", "FAM", "inferential"),
                 ("지하철", "COMMUTE", "inferential"), ("퇴근길", "COMMUTE", "inferential")]
        body, spans = "", []
        for j, (w, t, lv) in enumerate(words):
            start = len(body)
            body += w + " 얘기. "
            spans.append({"span_id": f"q{i}_s{j:02d}", "text_id": "body", "start": start, "end": start + len(w),
                          "text": w, "type": t, "level": lv, "subject": "self"})
        posts.append({"post_id": f"q{i}", "texts": {"body": body}, "geo_tag": None, "spans": spans})
    return posts


def test_model_input_is_capped_to_training_range() -> None:
    _, full = build_user_prompt(USER, _many_posts())
    _, capped = build_user_prompt(USER, _many_posts(), cap=True)
    assert sum(len(e["spans"]) for e in full) == 80
    spans = [s for e in capped for s in e["spans"]]
    assert len(spans) <= MODEL_MAX_SPANS
    by_type = {}
    for s in spans:
        by_type[s["type"]] = by_type.get(s["type"], 0) + 1
    assert max(by_type.values()) <= MODEL_MAX_SPANS_PER_TYPE
    assert set(by_type) == {"JOB", "FAM", "COMMUTE"}  # 한 유형이 자리를 독차지하지 않는다


def test_selection_prefers_explicit_spreads_posts_and_drops_repeats() -> None:
    _, full = build_user_prompt(USER, _many_posts())
    capped = select_for_model(full)
    jobs = [(e["post_id"], s["level"]) for e in capped for s in e["spans"] if s["type"] == "JOB"]
    assert all(level == "explicit" for _, level in jobs)       # 명시 단서(간호사)가 먼저
    assert len({pid for pid, _ in jobs}) == len(jobs)            # 여러 글에 퍼져 cross_post 를 살린다
    for e in capped:                                             # 같은 글의 「엄마」 되풀이는 하나만
        assert sum(1 for s in e["spans"] if s["type"] == "FAM") <= 1


def test_small_input_is_unchanged_by_cap() -> None:
    prompt_full, _ = build_user_prompt(USER, _posts())
    prompt_cap, _ = build_user_prompt(USER, _posts(), cap=True)
    assert prompt_full == prompt_cap


def test_rules_fallback_uses_all_spans_and_budget_grows() -> None:
    out = analyze(USER, _many_posts(), model=FakeModel('{"findings": {"age": '), mode="auto")
    assert out["provenance"]["model_version"] == f"{RULES_VERSION} (fallback: model output truncated)"
    assert out["findings"]["occupation"]["verdict"] != "abstain"
    assert output_budget(2) == 700 and output_budget(24) == 850 and output_budget(500) == 1400


def _entry(post_id, spans):
    return {"post_id": post_id, "spans": [dict(span_id=f"{post_id}_s{i:02d}", text_id=tid, text=tok, type=ty, level=lv,
                                               subject=sub) for i, (tid, tok, ty, lv, sub) in enumerate(spans)]}


def test_repeat_keeps_best_ranked_and_channel_is_part_of_key() -> None:
    # 같은 표현이 타인 → 본인 순으로 나와도 본인이 남는다
    out = select_for_model([_entry("a", [("body", "[직업1]", "JOB", "explicit", "other"),
                                         ("body", "[직업1]", "JOB", "explicit", "self")])])
    assert [s["subject"] for s in out[0]["spans"]] == ["self"]
    # 제목 [직업1] 과 본문 [직업1] 은 다른 표현이다 (채널마다 번호가 새로 붙는다)
    out = select_for_model([_entry("a", [("title", "[직업1]", "JOB", "inferential", "self"),
                                         ("body", "[직업1]", "JOB", "explicit", "self")])])
    assert len(out[0]["spans"]) == 2


def test_spreading_posts_never_beats_self_priority() -> None:
    first = _entry("p0", [("body", f"[직업{i}]", "JOB", "explicit", "self") for i in range(1, 7)])
    others = [_entry(f"p{i}", [("body", "[직업1]", "JOB", "inferential", "other")]) for i in range(1, 6)]
    out = select_for_model([first, *others])
    picked = [s for e in out for s in e["spans"]]
    assert len(picked) == MODEL_MAX_SPANS_PER_TYPE and all(s["subject"] == "self" for s in picked)


def test_selection_is_deterministic() -> None:
    _, full = build_user_prompt(USER, _many_posts())
    assert select_for_model(full) == select_for_model(full)
