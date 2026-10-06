"""조사 맞춤 · 바꿔 쓰기 후보 (josa.py · rewrite.py).

실행:
    python -m pytest src/kopl/c4_stage2/test_rewrite.py -v
"""

import pytest

from kopl.c4_stage2 import josa
from kopl.c4_stage2.rewrite import rewrites_for, suggest


@pytest.mark.parametrize("text,core,tail", [
    ("신촌에서", "신촌", "에서"), ("서른넷인데", "서른넷", "인데"), ("아이들은", "아이", "들은"),
    ("수원이라는", "수원", "이라는"), ("남편이랑", "남편", "이랑"), ("큰애가", "큰애", "가"),
    ("한라수목원으로", "한라수목원", "으로"), ("일흔셋에도", "일흔셋", "에도"), ("11번 버스를", "11번 버스", "를"),
    ("아이", "아이", ""), ("고양이", "고양이", ""), ("아들이", "아들", "이"), ("아들들이", "아들", "들이"),
    ("엄마들", "엄마", "들"), ("울산 쪽", "울산 쪽", ""), ("카드값", "카드값", ""), ("서울로", "서울", "로"),
])
def test_split_tail(text, core, tail):
    sp = josa.split_tail(text)
    assert (sp.core, sp.tail) == (core, tail)


@pytest.mark.parametrize("word,particle,expected", [
    ("40대", "이", "가"), ("서울", "으로", "로"), ("전남", "로", "으로"), ("가족", "랑", "이랑"), ("식구", "이랑", "랑"),
    ("40대", "이에요", "예요"), ("경기도", "이라는", "라는"), ("30", "을", "을"), ("2", "을", "를"),
    ("KTX", "을", "를"), ("ML", "가", "이"), ("의료직", "로", "으로"), ("서울", "에서", "에서"),
])
def test_fit(word, particle, expected):
    assert josa.fit(word, particle) == expected


@pytest.mark.parametrize("text,new,expected", [
    ("서른넷이", "40대", "40대가"), ("마흔여덟이에요", "40대", "40대예요"), ("신촌에서", "이 근처", "이 근처에서"),
    ("광주로", "전남", "전남으로"), ("아이들은", "식구", "식구들은"), ("간호사로", "의료직", "의료직으로"),
])
def test_replace_refits_inside_particle(text, new, expected):
    assert josa.replace(text, new) == expected


def test_outside_particle_filters_candidates():
    """조사가 스팬 밖이면 고칠 수 없다 — 끝소리가 맞는 후보만 (「위험 단어 뒤 조사에 맞는 새 단어」)."""
    assert josa.replace("서른넷", "40대", "이 되니") is None
    assert josa.replace("서른넷", "마흔", "이 되니") == "마흔"
    out = suggest({"text": "마흔여덟", "type": "AGE", "start": 0, "end": 4}, "마흔여덟이 되니")
    assert all(josa.has_batchim(c["core"]) for c in out) and out


def _s(before, text, after, stype):
    full = before + text + after
    return [c["suggestion"] for c in suggest({"text": text, "type": stype, "start": len(before),
                                               "end": len(before) + len(text)}, full)]


@pytest.mark.parametrize("before,text,after,stype,expected_first", [
    ("", "역삼동에서", " 친구를", "LOC_ADMIN", "강남구에서"),
    ("", "완산구", "에 산다", "LOC_ADMIN", "전주시"),
    ("", "영통구에서", " 살아요", "LOC_ADMIN", "수원시에서"),
    ("", "서른넷인데", " 아직", "AGE", "30대 초반인데"),
    ("했는데, ", "쉰여덟인", " 지금은", "AGE", "50대 후반인"),
    ("", "판교역", " 근처", "LOC_FACILITY", "분당구의 한 역"),
    ("", "한라수목원으로", " 산책", "LOC_FACILITY", "한 수목원으로"),
    ("", "11번 버스를", " 탔다", "COMMUTE", "버스를"),
    ("", "통근버스엔", " 탔어", "COMMUTE", "버스엔"),
    ("", "남편이랑", " 산책", "SEX", "가족이랑"),
    ("", "막내아들은", " 독립", "FAM", "아이는"),
    ("말 나온 김에 ", "딸애 등록금", " 빠지는", "FAM", "아이 등록금"),
    ("", "간호사로", " 일한다", "JOB", "의료직 종사자로"),
    ("", "회사 단톡방에는", " 누가", "REL_WORK", "직장 단톡방에는"),
])
def test_suggestions(before, text, after, stype, expected_first):
    out = _s(before, text, after, stype)
    assert out and out[0] == expected_first, out


@pytest.mark.parametrize("before,text,after,stype", [
    ("", "분기 부가세", " 숫자를", "JOB"),        # 업무 단서를 「일」로 뭉개지 않는다
    ("", "이유식을", " 나눠 담아", "FAM"),        # 「가족을 나눠 담아」 ✗
    ("", "경유값이", " 올라", "COMMUTE"),          # 「대중교통이 올라」 ✗
    ("", "딸기", " 농사", "FAM"),                 # 「딸」 단어 경계
    ("", "집", " 가는 길에", "REL_HOME"),          # 관계어 자체는 안 바꾼다
    ("", "상하이", "에서 산다", "LOC_ADMIN"),      # 해석 못 하는 지명에 「우리 동네」를 지어내지 않는다
])
def test_no_suggestion_when_unsure(before, text, after, stype):
    assert _s(before, text, after, stype) == []


def test_no_echo_with_neighbours():
    assert "근처 근처 공원을" not in " ".join(_s("마치고 근처 ", "복개천 공원을", " 한 바퀴", "LOC_FACILITY"))
    assert not any(x.startswith("일") for x in _s("", "간호사로", " 일한 지", "JOB"))


def test_park_is_not_mistaken_for_station():
    out = _s("봉투를 들고 ", "체육공원", " 쪽으로", "LOC_FACILITY")
    assert out == ["한 공원"]  # 체육공원역의 동네로 넓히지 않는다 · 「동네/근처 공원」은 원문에 없는 생활권·가까움이 생긴다


def test_outside_particle_blocks_mismatched_word():
    """「간호사」 뒤 「로」는 스팬 밖이라 못 고친다 — 받침 있는 「의료직」은 「의료직로」가 되므로 내지 않는다."""
    assert "의료직" not in _s("", "간호사", "로 일한다", "JOB")


def test_homonym_region_is_not_widened():
    assert _s("", "광주로", " 이사 왔다", "LOC_ADMIN") == []


def test_hada_slot_abstains():
    """「하다」 자리는 활동을 바꾸면 사실이 바뀔 수 있다 (퇴근했다 ≠ 귀가했다) — 기권."""
    assert _s("", "출근", "하고 나서", "COMMUTE") == []
    assert _s("", "퇴근", "했다. 집에 가지 않고", "COMMUTE") == []


def test_rewrites_for_contract_shape():
    import json
    from pathlib import Path

    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((Path(__file__).resolve().parents[3] / "docs/contracts/stage2-io.schema.json")
                        .read_text(encoding="utf-8"))
    body = "역삼동에서 일하는 마흔여덟 간호사예요."
    posts = [{"post_id": "p1", "texts": {"body": body}, "spans": [
        {"span_id": "p1_s01", "text_id": "body", "start": 0, "end": 5, "text": "역삼동에서", "type": "LOC_ADMIN",
         "level": "explicit", "subject": "self"},
        {"span_id": "p1_s02", "text_id": "body", "start": 10, "end": 14, "text": "마흔여덟", "type": "AGE",
         "level": "explicit", "subject": "self"},
    ]}]
    out = rewrites_for(posts)
    assert {r["span_id"] for r in out} == {"p1_s01", "p1_s02"}
    for r in out:
        jsonschema.validate(r, {"$defs": schema["$defs"], "$ref": "#/$defs/Rewrite"})


# ── 손으로 고정한 정답 (생성기와 독립) — Codex 검토 반례 · exp15 표본 검토 ──────────────

@pytest.mark.parametrize("text,new,after,kwargs,expected", [
    ("서른셋이지만", "30대 초반", " 아직", {"copula_in": True}, "30대 초반이지만"),
    ("서른셋이어서", "30대 초반", " 그런지", {"copula_in": True}, "30대 초반이어서"),
    ("서른셋이었지만", "30대 초반", " 지금은", {"copula_in": True}, "30대 초반이었지만"),
    ("서른셋엔", "30대 초반", " 몰랐다", {"copula_in": True}, "30대 초반엔"),
    ("서른셋인걸", "30대 초반", " 뭐", {"copula_in": True}, "30대 초반인걸"),
    ("서른셋이에요!", "30대 초반", "", {"copula_in": True}, "30대 초반이에요!"),
    ("마흔일곱🙂", "40대 후반", "", {"copula_in": True}, "40대 후반🙂"),
    ("서른넷이", "40대", "", {}, "40대가"),
    ("서울서", "부산", " 왔다", {"loc": True}, "부산서"),
    ("통근버스엔", "버스", " 탔다", {}, "버스엔"),
    ("서른셋이", "30대 초반", "야", {}, "30대 초반이"),      # 밖으로 이어진 「이야」 — 형태가 같아 허용
    ("서른셋이", "40대", "야", {}, None),                  # 「40대가야」 ✗ — 기권
    ("간호사", "의료직", "로: 일했다", {}, None),           # 바깥 「로」 + 문장부호 — 「의료직로」 ✗
    ("서른셋", "40대", "이 되니", {}, None),
])
def test_replace_golden(text, new, after, kwargs, expected):
    assert josa.replace(text, new, after, **kwargs) == expected


@pytest.mark.parametrize("word,particle,expected", [
    ("R", "으로", "로"), ("L", "으로", "로"), ("Google", "이", None), ("game", "을", None), ("²", "을", None),
])
def test_fit_golden(word, particle, expected):
    assert josa.fit(word, particle) == expected


@pytest.mark.parametrize("text,core", [("회의", "회의"), ("지도", "지도"), ("부산대로", "부산대로"), ("종로", "종로")])
def test_nouns_that_look_like_particles(text, core):
    assert josa.split_tail(text).core == core


@pytest.mark.parametrize("before,text,after,stype,expected", [
    ("", "삼십구 살", " 때", "AGE", "30대 후반"),
    ("", "대전 유성구 회사에서", " 일해", "REL_WORK", None),     # 지명이 남는다 — 기권
    ("", "딸과 아들", " 둘", "FAM", None),                    # 관계어가 남는다 — 기권
    ("", "친정 언니가", " 왔다", "SEX", None),                 # 친정 지인 ✗
    ("", "주식회사", " 다닌다", "REL_WORK", None),             # 「주식직장」 ✗
    ("", "신촌역", " 3번 출구", "LOC_FACILITY", "서대문구의 한 역"),
    ("‘", "수원시", "’라는 글자", "LOC_ADMIN", None),          # 인용된 이름
    ("마치고 근처의 ", "복개천 공원을", " 걸었다", "LOC_FACILITY", "한 공원을"),
    ("", "간호사로서", " 일했다", "JOB", "의료직 종사자로서"),
])
def test_suggest_golden(before, text, after, stype, expected):
    out = _s(before, text, after, stype)
    assert (out[0] if out else None) == expected, out


@pytest.mark.parametrize("before,text,after,stype,expected", [
    ("", "서른셋", " 먹고도", "AGE", None),               # 나이를 먹다 — 구간 밖을 고쳐야 한다
    ("", "서른셋이나", " 먹고", "AGE", None),
    ("", "삼십구", " 살 때", "AGE", None),                # 단위가 밖
    ("", "막내", " 동생이", "FAM", None),                 # 수식어
    ("", "막내 딸내미가", " 왔다", "FAM", None),
    ("", "퇴근", "했다", "COMMUTE", None),
    ("", "출근", "하고", "COMMUTE", None),
    ("", "간호사를", " 만났다", "JOB", "의료직 종사자를"),
    ("", "사장님이", " 왔다", "JOB", None),
    ("", "서른셋", "th", "AGE", None),
    ("", "출근길", " 자전거", "COMMUTE", None),
    ("", "스타벅스 카페에서", " 만났다", "LOC_FACILITY", "한 카페에서"),
])
def test_suggest_golden_round2(before, text, after, stype, expected):
    out = _s(before, text, after, stype)
    assert (out[0] if out else None) == expected, out


@pytest.mark.parametrize("before,text,after,stype,expected", [
    ("", "의성군", " 보건소에", "LOC_ADMIN", None),             # 기관 이름의 일부
    ("", "신림동", " 쪽 고시촌", "LOC_ADMIN", "관악구"),          # 시도(서울 쪽)까지는 안 넓힌다
    ("원주시청 뒤편 ", "단계동", " 근린공원", "LOC_ADMIN", None),  # 앞에 이미 지명 — 넓히면 겹친다
    ("", "회사", " 옆자리 언니", "REL_WORK", None),
    ("", "마흔둘", "이라는 나이가", "AGE", "40대 초반"),
    ("", "반월당역", " 상가거리", "LOC_FACILITY", None),
])
def test_suggest_golden_round3(before, text, after, stype, expected):
    out = _s(before, text, after, stype)
    assert (out[0] if out else None) == expected, out
    assert "중년" not in " ".join(out) or "나이" not in after


@pytest.mark.parametrize("before,text,after,stype,expected", [
    ("", "안동", " 옥동에서 붓을", "LOC_ADMIN", None),         # 안동시·김해시 안동 둘 다 — 기권 (김해시로 넓히지 않는다 · B18_b10)
    ("", "일산동에서", " 대왕암공원까지", "LOC_ADMIN", None),   # 울산 일산동·고양 일산동구 — 기권 (Codex 10/5)
    ("", "전주도", " 요즘 비가 와", "LOC_ADMIN", None),        # 「전북도」는 도 이름처럼 읽힌다
])
def test_suggest_golden_instance(before, text, after, stype, expected):
    out = _s(before, text, after, stype)
    assert (out[0] if out else None) == expected, out
    assert "김해시" not in out


@pytest.mark.parametrize("before,text,after", [
    ("시청에서 보낸 ", "서른", " 해보다 길었다"),
    ("씨감자 묻고 ", "쉰", " 날"),
    ("책이 ", "스물세", " 권이나 쌓였다"),
])
def test_age_before_unit_abstains(before, text, after):
    """뒤에 단위가 오면 나이가 아니다 — 「보낸 30대 초반 해보다」 같은 후보를 내지 않는다 (인스턴스 B18)."""
    assert _s(before, text, after, "AGE") == []


def test_age_with_unit_like_word_still_rewrites():
    """「벌써」의 「벌」은 단위(옷 한 벌)가 아니다 — 나이로 바꿔 쓴다."""
    assert _s("", "스물다섯인데", " 벌써 이렇게", "AGE")[:1] == ["20대 후반인데"]


def test_age_line_idiom_still_rewrites():
    """「서른 줄에」는 나이 — 단위로 보고 기권하지 않는다 (Codex 10/5)."""
    assert _s("어느새 ", "서른", " 줄에 접어들었네", "AGE")


@pytest.mark.parametrize("before,text,after,expected", [
    ("주말에는 ", "시누이가", " 찻잔 세트를", "가족이"),
    ("", "처남이", " 동탄 살아서", "가족이"),
    ("", "언니가", " 놀러 왔다", "지인이"),
])
def test_in_law_stays_family(before, text, after, expected):
    """처남·시누이는 반드시 가족 — 「지인」으로 바꾸면 뜻이 바뀐다 (#304 리뷰)."""
    assert _s(before, text, after, "FAM")[:1] == [expected]


def _r(before, text, after, stype):
    full = before + text + after
    return [c["residual"] for c in suggest({"text": text, "type": stype, "start": len(before),
                                             "end": len(before) + len(text)}, full)]


@pytest.mark.parametrize("before,text,after,stype", [
    ("밖으로 나갔습니다. 일산 ", "호수공원", " 산책로는", "LOC_FACILITY"),
    ("걷는 사이 곡성 ", "마을버스를", " 또 놓쳤다", "COMMUTE"),
])
def test_place_right_before_is_residual(before, text, after, stype):
    """바로 앞 지명이 남으면 단서가 약해질 뿐 사라지지 않는다 — residual (#304 리뷰)."""
    res = _r(before, text, after, stype)
    assert res and all(res)



def test_place_like_modifier_on_job_is_not_residual():
    """「수영 [강사로]」 — 수영(수영구)은 여기서 운동이다. 직업 단서에는 앞 지명 검사를 하지 않는다 (Codex 10/6)."""
    res = _r("이번에 수영 ", "강사로", " 취직했다", "JOB")
    assert res and not any(res)



@pytest.mark.parametrize("before,text,after,stype", [
    ("", "회사에서", " 일한다", "REL_WORK"),
    ("", "간호사로", " 일한다", "JOB"),
])
def test_real_place_before_any_type_is_residual(before, text, after, stype):
    """「서울 [회사에서]」 「부산 [간호사로]」 — 실제 지명이 앞에 남으면 타입과 상관없이 residual (Codex 10/6 재검토)."""
    for place in ("서울 ", "부산 "):
        res = _r(place + before, text, after, stype)
        assert res and all(res), (place, text, res)
