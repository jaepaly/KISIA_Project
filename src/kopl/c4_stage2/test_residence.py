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
        "시카고에 살고 있는 평범한 엄마의 기록.",
        "시카고 겨울은 바람이 매섭다.",
        "시카고 호숫가 산책로를 걸었다.",
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
        "미국생활 브이로그를 자주 본다.",
        "미국에서 지내다 보니 이런 것도 알게 됐다는 유튜버 얘기.",
        "망원동에 산 지 벌써 5년이다.",
        "마포에 살고 있어서 한강이 가깝다.",
        "서울에 살면서 처음으로 눈썰매를 탔다.",
    ], spans)
    assert out["posts"]["korea"] == ["p2", "p3", "p4"]
    assert not out["overseas"] and out["rule"] == "국내 거주 단서가 같거나 더 많음"


def test_foreign_span_is_not_korean_residence():
    # 1단이 「시카고」를 LOC_ADMIN 으로 잡아도 국내 거주 단서로 세지 않는다
    spans = {"p0": [{"type": "LOC_ADMIN", "subject": "self", "text_id": "body", "start": 0, "end": 3, "text": "시카고"}]}
    out = _run(["시카고에 살고 있다. 바람이 세다.", "미국 와서 처음 맞는 겨울."], spans)
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
