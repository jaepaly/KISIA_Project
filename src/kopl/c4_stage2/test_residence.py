"""해외 거주 판별 — 합성 문장만.

실행:
    python -m pytest src/kopl/c4_stage2/test_residence.py -v
"""

import pytest

from kopl.c4_stage2.residence import find_residence


def _run(bodies, spans=None):
    return find_residence({f"p{i}": {"body": b} for i, b in enumerate(bodies)}, spans)


def test_us_residence_across_posts_is_overseas():
    out = _run([
        "미국에서 지내다 보니 아이가 영어를 먼저 배운다.",
        "오늘은 마트 장보기. 미국생활 3년 차인데 아직도 단위가 헷갈린다.",
        "주말에는 공원에 갔다. 날씨가 좋았다.",
    ])
    assert out["overseas"] and out["country"] == "미국"
    assert out["posts"]["residence"] == ["p0", "p1"]
    assert [e["value"] for e in out["evidence"]] == ["미국에서 지내다 보", "미국생활"]


def test_one_residence_post_plus_repeated_country_is_overseas():
    out = _run([
        "시애틀에 살고 있는 평범한 직장인의 기록.",
        "시애틀 겨울은 비가 잦다.",
        "시애틀 해안가 산책로를 걸었다.",
    ])
    assert out["overseas"] and out["country"] == "미국"
    assert out["rule"] == "거주 표현 1편 + 같은 나라 반복"


@pytest.mark.parametrize("bodies", [
    ["뉴욕 여행 다녀왔다. 타임스스퀘어가 생각보다 작았다.", "뉴욕에서 지내는 사흘 동안 비가 왔다. 여행은 역시 날씨다.",
     "망원동에 산 지 5년째다."],
    ["미국 주식이 또 떨어졌다.", "미국 대선 뉴스를 봤다.", "일본 드라마를 정주행했다.", "미국 금리 얘기뿐이다."],
    ["동생이 캐나다에 살고 있어서 영상통화를 했다.", "친구는 호주에서 지내고 있다고 한다."],
    ["언젠가 캐나다에 살아 보고 싶다.", "이민 가고 싶다는 생각을 자주 한다."],
    ["대학 때 일본에서 살았던 기억이 난다.", "도쿄 생활했을 때 자주 가던 가게가 있다."],
    ["미국에서 지내다 보니 영어가 늘었다."],   # 글 한 편으로는 판단하지 않는다
], ids=["travel", "news", "others", "wish", "past", "single_post"])
def test_korean_residents_are_not_overseas(bodies):
    out = _run(bodies)
    assert not out["overseas"], out
    assert out["country"] is None


def test_travel_post_blocks_arrival_but_not_living():
    # 여행 글의 「일본 와서」는 세지 않는다 — 여행 첫날에도 쓰는 말
    out = _run(["2박 3일 오사카 여행. 일본 와서 첫 끼는 라멘.", "오사카 여행 둘째 날. 일본 와서 처음 본 자판기."])
    assert not out["overseas"] and out["posts"]["residence"] == []


def test_korean_residence_stronger_wins():
    spans = {
        "p2": [{"type": "LOC_ADMIN", "subject": "self", "text_id": "body", "start": 0, "end": 3, "text": "망원동"}],
        "p3": [{"type": "LOC_ADMIN", "subject": "self", "text_id": "body", "start": 0, "end": 2, "text": "마포"}],
        "p4": [{"type": "LOC_ADMIN", "subject": "self", "text_id": "body", "start": 0, "end": 2, "text": "서울"}],
    }
    out = _run([
        "미국생활 2년 차 기록을 다시 읽었다.",
        "미국에서 지내다 보니 이런 것도 알게 됐다.",
        "망원동에 산 지 벌써 5년이다.",
        "마포에 살고 있어서 한강이 가깝다.",
        "서울에 살면서 처음으로 눈썰매를 탔다.",
    ], spans)
    assert out["posts"]["korea"] == ["p2", "p3", "p4"]
    assert not out["overseas"] and out["rule"] == "국내 거주 단서가 같거나 더 많음"


def test_foreign_span_is_not_korean_residence():
    # 1단이 「시애틀」를 LOC_ADMIN 으로 잡아도 국내 거주 단서로 세지 않는다
    spans = {"p0": [{"type": "LOC_ADMIN", "subject": "self", "text_id": "body", "start": 0, "end": 3, "text": "시애틀"}]}
    out = _run(["시애틀에 살고 있다. 바람이 세다.", "미국 와서 처음 맞는 겨울."], spans)
    assert out["posts"]["korea"] == [] and out["overseas"]


@pytest.mark.parametrize("word", ["미국산 소고기", "일본어 공부", "중국집 짜장면", "결과에 대만족", "호주머니 속 동전", "LA갈비"])
def test_compound_words_are_not_places(word):
    out = _run([f"{word} 생활 이야기", f"{word} 생활 이야기 둘째"])
    assert out["posts"]["residence"] == [] and out["posts"]["mention"] == []


def test_standalone_words_and_week_count():
    out = _run(["남편 주재원 발령으로 온 가족이 함께 왔다.", "시드니 4주차, 장보기에 적응했다."])
    assert out["overseas"] and out["country"] == "호주"
    # 「n일차」는 여행에도 쓰므로 세지 않는다
    assert not _run(["시드니 2일차, 오페라하우스.", "시드니 3일차, 본다이 비치."])["posts"]["residence"]


def test_offsets_point_at_text():
    texts = {"title": "미국생활 기록", "body": "요즘 미국에서 살면서 느낀 점"}
    out = find_residence({"a": texts, "b": {"body": "캐나다에 살고 있다"}})
    for e in out["evidence"]:
        src = texts if e["post_id"] == "a" else {"body": "캐나다에 살고 있다"}
        assert src[e["text_id"]][e["start"]:e["end"]] == e["value"]


# ── Codex 리뷰(148abb8) 재현 사례 ─────────────────────────────────────────

@pytest.mark.parametrize("bodies", [
    # 1. 가정문 「살면」은 현재 거주가 아니다
    ["미국에 살면 세금이 달라진다.", "미국 주식이 오른다.", "뉴욕 증시가 상승한다."],
    # 2. 생활 콘텐츠 · 직무 명사 · 끝난 해외 생활
    ["미국생활 브이로그를 자주 본다.", "미국일상 유튜브를 구독 중이다."],
    ["주재원 채용 공고를 정리했다.", "주재원 연봉 비교표를 만들었다."],
    ["미국생활 4년을 마치고 한국에 돌아왔다.", "캐나다 생활을 마치고 한국에 정착했다."],
    # 3. 배우자가 주어
    ["남편은 미국에 살고 있다.", "남편은 미국에서 지내고 있다."],
    # 4. 여행 글의 「생활 체험」 · 「n주차」
    ["일본 여행 기록.\n도쿄 생활을 체험하는 한 달이다.", "일본 여행 기록 2.\n도쿄 4주차, 오늘은 쇼핑했다."],
], ids=["conditional", "content", "job_noun", "ended", "spouse", "travel_post"])
def test_codex_review_cases_are_not_overseas(bodies):
    out = _run(bodies)
    assert not out["overseas"], out


def test_ended_life_counts_as_korean_return():
    out = _run(["미국생활 4년을 마치고 한국에 돌아왔다.", "캐나다 생활을 마치고 한국에 정착했다."])
    assert out["posts"]["residence"] == [] and out["posts"]["korea"] == ["p0", "p1"]


def test_other_subject_span_from_stage1_is_not_self_residence():
    # 문장에 주어 표지가 없어도 1단이 위치 스팬을 남의 것으로 봤으면 세지 않는다
    bodies = ["요즘 미국에 살고 있다는 소식.", "미국에서 지내고 있다는 연락."]
    spans = {f"p{i}": [{"type": "LOC_ADMIN", "subject": "other", "text_id": "body", "start": b.index("미국"),
                        "end": b.index("미국") + 2, "text": "미국"}] for i, b in enumerate(bodies)}
    assert _run(bodies)["overseas"]          # 스팬이 없으면 본인 거주로 본다
    assert not _run(bodies, spans)["overseas"]


def test_travel_post_still_counts_verb_residence():
    # 여행 글이라도 「살고 있다」처럼 사는 것을 동사로 말하면 센다 (같은 문장에 여행 표현은 없다)
    out = _run(["캐나다에 살고 있다. 이번 휴가는 집에서.", "토론토 생활 3년째, 겨울이 길다."])
    assert out["overseas"] and out["country"] == "캐나다"


# ── Codex 2차 리뷰(b2a4464) — 거르는 판단은 그 거주 술어의 절 · 주어로 ───────────────

@pytest.mark.parametrize("bodies", [
    # 1. 문장 중간에 주어가 바뀌면 「나는」 절의 거주를 센다
    ["남편이 먼저 와서 나는 미국에 살고 있다.", "아내는 재택근무하고 나는 미국에 산 지 3년째다."],
    # 2. 일상 귀가 · 업무 종료는 해외 생활 종료가 아니다
    ["미국에 살고 있다, 퇴근하면 집에 돌아와 쉰다.", "미국에 산 지 3년째, 일을 마치고 집에서 쉰다."],
    # 3. 생활 중 독서 — 생활 표현이 콘텐츠의 주제가 아니다
    ["미국생활 3년째, 요즘은 책을 읽으며 쉰다.", "미국일상 기록, 퇴근 후 책을 읽었다."],
    # 4. 다른 문장의 여행 계획은 현재 워홀 근거를 지우지 않는다
    ["시드니에서 워홀 중이다. 주말 여행 계획을 세웠다.", "시드니에서 워홀 중이다. 다음 여행은 멜버른이다."],
], ids=["subject_switch", "daily_return", "reading", "travel_other_sentence"])
def test_clause_scoped_filters_keep_self_residence(bodies):
    out = _run(bodies)
    assert out["overseas"], out


def test_spouse_abroad_but_self_in_korea_keeps_korean_evidence():
    # 배우자 필터는 그 절 주어로만 — 「나는 한국에 살고 있다」 국내 근거가 지워지면 해외 오탐이 된다
    out = _run(["미국생활 사진을 정리한다.", "미국일상 사진을 꺼내 본다.",
                "남편은 미국에서 일하지만 나는 한국에 살고 있다.", "남편이 해외에서 일하고 나는 한국에 살고 있다."])
    assert out["posts"]["korea"] == ["p2", "p3"]
    assert not out["overseas"]
