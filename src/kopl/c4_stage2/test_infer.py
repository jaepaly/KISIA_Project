"""2단 실행 경로 검증 — 가짜 모델로 돌린다 (GPU·어댑터 없이).

실행:
    python -m pytest src/kopl/c4_stage2/test_infer.py -v
"""

import json
from pathlib import Path

import pytest

from kopl.c4_stage2.infer import MODEL_VERSION, RULES_VERSION, analyze, build_user_prompt, validate_findings
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
