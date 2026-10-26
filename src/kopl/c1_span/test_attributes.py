"""attributes.resolve — level·subject 규칙 판정 (exp16). 손으로 고정한 정답."""
from __future__ import annotations

import pytest

from kopl.c1_span.attributes import level_of, resolve


def _r(sentence: str, span: str, stype: str, occurrence: int = 0) -> dict:
    start = -1
    for _ in range(occurrence + 1):
        start = sentence.index(span, start + 1)
    return resolve({"body": sentence}, {"text_id": "body", "start": start, "end": start + len(span), "text": span, "type": stype})


@pytest.mark.parametrize("stype,text,expected", [
    ("AGE", "마흔여덟", "explicit"), ("AGE", "34살", "explicit"), ("AGE", "세 살", "explicit"),
    ("AGE", "예순여덟인디", "explicit"), ("AGE", "초등학생", "implicit"), ("AGE", "경로당", "inferential"),
    ("LOC_ADMIN", "역삼동에서", "explicit"), ("LOC_ADMIN", "시드니", "inferential"),
    ("LOC_FACILITY", "태화강", "explicit"), ("LOC_FACILITY", "작전역 우체국", "explicit"),
    ("LOC_FACILITY", "한인마트에서", "inferential"), ("LOC_FACILITY", "단골 드립커피집", "inferential"),
    ("LOC_FACILITY", "읍내 도서관에서", "inferential"),
    ("REL_HOME", "옆집", "inferential"), ("REL_WORK", "회사에서", "inferential"),
    ("SEX", "남성", "explicit"), ("SEX", "남편이", "implicit"), ("SEX", "언니가", "implicit"), ("SEX", "립스틱", "inferential"),
    ("FAM", "중학생 아들", "implicit"), ("FAM", "유모차", "inferential"),
    ("INCOME", "이백팔십만 원", "explicit"), ("INCOME", "30,000,000원", "explicit"), ("INCOME", "야간수당", "implicit"),
    ("INCOME", "카드값", "inferential"),
    ("COMMUTE", "832번", "explicit"), ("COMMUTE", "퇴근길 2호선", "explicit"), ("COMMUTE", "KTX", "explicit"),
    ("COMMUTE", "통근 셔틀", "inferential"), ("COMMUTE", "지하철역에서", "inferential"), ("COMMUTE", "걸어서 십오 분", "implicit"),
    ("JOB", "편의점 알바", "explicit"), ("JOB", "야간조", "implicit"), ("JOB", "팀장님", "inferential"),
])
def test_level(stype, text, expected):
    assert level_of(stype, text) == expected


@pytest.mark.parametrize("sentence,span,stype,expected", [
    ("친구가 화정에서 공방 한다고 해서 구경 갔다.", "화정에서", "LOC_ADMIN", "other"),
    ("아홉 살 아들은 옆에서 학예회 대사를 외운다.", "아홉 살", "AGE", "other"),
    ("새벽 퇴근길 편의점 알바 언니가 삼각김밥을 챙겨 줬다.", "편의점 알바", "JOB", "other"),
    ("동탄 사는 친구랑 밤낚시를 갔다.", "동탄", "LOC_ADMIN", "other"),
    ("시누이가 지난달에 전주 효자동 새 아파트로 이사했다.", "전주 효자동", "LOC_ADMIN", "other"),
    ("늘 약속보다 늦는 단골 건축주가 종이 잔을 들고 왔다.", "단골 건축주가", "JOB", "other"),
    # 본인
    ("역삼동에서 친구를 만났다.", "역삼동에서", "LOC_ADMIN", "self"),
    ("나는 마흔여덟이 되니 무릎이 아프다.", "마흔여덟", "AGE", "self"),
    ("옆집 아주머니가 고구마순을 줬다.", "옆집", "REL_HOME", "self"),               # 관계 단서 — 내 이웃
    ("이웃 엄마들 모임에서 들었다.", "이웃", "REL_HOME", "self"),
    ("거래처 사장님이랑 커피 한 잔 했다.", "거래처", "JOB", "self"),               # 내 일의 상대
    ("사장님이 흔들린 라떼아트에 한마디 했다.", "라떼아트에", "JOB", "self"),
    ("아내가 아이를 데리러 갔다.", "아이를", "FAM", "self"),                      # 내 가족 구성
    ("친구가 판교로 이사 갔고 나는 수원에 산다.", "수원에", "LOC_ADMIN", "self"),   # 1인칭 주어가 다시 나옴
    ("친구가 판교로 이사 갔다. 나는 수원에 산다.", "수원에", "LOC_ADMIN", "self"),   # 다른 문장
])
def test_subject(sentence, span, stype, expected):
    assert _r(sentence, span, stype)["subject"] == expected


def test_contract_fields_only_and_offset_mismatch_falls_back_to_self():
    out = resolve({"body": "친구가 화정에서 공방"}, {"text_id": "body", "start": 0, "end": 3, "text": "화정에서", "type": "LOC_ADMIN"})
    assert set(out) == {"level", "subject"} and out["subject"] == "self"   # 오프셋이 안 맞으면 문맥을 쓰지 않는다


@pytest.mark.parametrize("sentence,span,stype,expected", [
    # Codex 1차 반례 — 소유 표현은 본인
    ("친구가 내 나이 서른넷을 듣고 놀랐어.", "서른넷을", "AGE", "self"),
    ("친구가 내 고향인 수원을 한번 가 보고 싶대.", "수원을", "LOC_ADMIN", "self"),
    ("친구가 내 월급 300만 원을 듣더니 부럽대.", "300만 원을", "INCOME", "self"),
    ("친구가 우리 집에 놀러 와서 같이 게임했어.", "우리 집에", "REL_HOME", "self"),
    # 타인 귀속
    ("친구의 집은 수원에 있고 난 서울에 살아.", "수원에", "LOC_ADMIN", "other"),
    ("친구가 동네 주민이라 수원에 산대.", "수원에", "LOC_ADMIN", "other"),
    ("사장님이 약사라서 약 얘기를 자주 해.", "약사라서", "JOB", "other"),
    ("남편은 남자라서 남성복 코너부터 가더라.", "남자라서", "SEX", "other"),
    ("나는 건축주로 이번 공사를 직접 맡겼어.", "건축주로", "JOB", "self"),
])
def test_subject_codex_round1(sentence, span, stype, expected):
    assert _r(sentence, span, stype)["subject"] == expected


@pytest.mark.parametrize("stype,text,expected", [
    ("JOB", "작가로", "explicit"), ("JOB", "개발자로", "explicit"), ("JOB", "디자이너라서", "explicit"),
    ("SEX", "누나가", "implicit"), ("INCOME", "월급 300만", "explicit"),
    ("LOC_FACILITY", "아담한 공원에서", "inferential"), ("INCOME", "활동비가", "inferential"),
])
def test_level_codex_round1(stype, text, expected):
    assert level_of(stype, text) == expected


@pytest.mark.parametrize("sentence,span,stype,expected", [
    # Codex 2차 반례
    ("친구가 제 생일에 마흔이 된대.", "마흔이", "AGE", "other"),
    ("친구가 우리 동네에서 간호사로 일해.", "간호사로", "JOB", "other"),
    ("형은 내 월급보다 많은 500만 원을 번대.", "500만 원을", "INCOME", "other"),
    ("친구가 내 동생이랑 부산에 산대.", "부산에", "LOC_ADMIN", "other"),
    ("우리 형 나이는 마흔이야.", "마흔이야", "AGE", "other"),
    ("내 친구가 수원에 산대.", "수원에", "LOC_ADMIN", "other"),
    ("친구가 서울로 갔다 수원에 사는 나는 집에 있었어.", "수원에", "LOC_ADMIN", "self"),
    ("친구가 서울로 갔음 수원에 사는 나는 집에 있었어.", "수원에", "LOC_ADMIN", "self"),
    ("친구가 부산에 산대 수원에 사는 나는 못 만났어.", "수원에", "LOC_ADMIN", "self"),
    ("친구가 웃는다 해도 부산에 사는 건 맞아.", "부산에", "LOC_ADMIN", "other"),
    ("친구가 부산에서 ㅋㅋ 수원까지 매일 출근한대.", "수원까지", "LOC_ADMIN", "other"),
    ("사장님은 남자라서 남성복만 입는대.", "남자라서", "SEX", "other"),
    ("사장님은 월급 300만 원을 받는대.", "월급 300만 원을", "INCOME", "other"),
    ("바다 근처 친구가 수원에 산대.", "수원에", "LOC_ADMIN", "other"),
])
def test_subject_codex_round2(sentence, span, stype, expected):
    assert _r(sentence, span, stype)["subject"] == expected


@pytest.mark.parametrize("stype,text,expected", [
    ("LOC_FACILITY", "광진 도서관에서", "explicit"), ("LOC_FACILITY", "낡고 작은 공원에서", "inferential"),
])
def test_level_codex_round2(stype, text, expected):
    assert level_of(stype, text) == expected


@pytest.mark.parametrize("sentence,span,stype,expected", [
    # 인스턴스 테스트 10/5 — 1단이 「동탄」을 시설로 잡은 경우
    ("동탄 사는 친구가 놀러 왔다.", "동탄", "LOC_FACILITY", "other"),
    ("광교 호수공원 근처 사는 동생이 왔다.", "광교 호수공원 근처", "LOC_FACILITY", "other"),
    ("단골 카페 사장님이 쿠키를 줬다.", "단골 카페", "LOC_FACILITY", "self"),
    ("옆집 사는 언니가 반찬을 줬다.", "옆집", "REL_HOME", "self"),        # 옆집 = 내 집 기준 관계
])
def test_subject_facility_residence_of_other(sentence, span, stype, expected):
    assert _r(sentence, span, stype)["subject"] == expected


@pytest.mark.parametrize("sentence,span", [("나는 동탄 사는 아빠야", "동탄"), ("나도 선릉역 사는 친구야", "선릉역")])
def test_first_person_resident_is_self(sentence, span):
    """Codex 검토(10/5): 1인칭 주어가 있으면 「동탄 사는 + 사람」도 본인."""
    assert _r(sentence, span, "LOC_FACILITY")["subject"] == "self"


@pytest.mark.parametrize("sentence,span,expected", [
    ("나는 동탄 사는 친구를 만났다", "동탄", "other"),     # Codex 2차 — 친구의 거주지
    ("나는 동탄 사는 아빠를 만났다", "동탄", "other"),
    ("나는 동탄 사는 아빠야", "동탄", "self"),            # 자기소개
    ("저는 동탄 사는 직장인입니다", "동탄", "self"),
    ("나는 동탄 사는 아빠라서 주말이 바쁘다", "동탄", "self"),   # Codex 3차 — 활용형도 자기소개로 맞힘
    ("저는 동탄 사는 사람인데요", "동탄", "self"),
])
def test_first_person_self_intro_vs_modifier(sentence, span, expected):
    assert _r(sentence, span, "LOC_FACILITY")["subject"] == expected


def test_resident_rule_actually_matches_copula_forms():
    """Codex 3차 — 「아빠라서」 「사람인데요」가 기본값이 아니라 자기소개 규칙으로 self 가 되는지, 「친구에게」는 other 인지."""
    from kopl.c1_span.attributes import _COPULA_AFTER, _RESIDENT_AFTER
    m = _RESIDENT_AFTER.match(" 사는 아빠라서 주말이")
    assert m and _COPULA_AFTER.match(" 사는 아빠라서 주말이"[m.end():])
    assert _RESIDENT_AFTER.match(" 사는 사람인데요") is None   # 「사람」은 특정한 타인이 아니다 — 거주 규칙 대상 아님(기본 self)
    assert _r("나는 동탄 사는 친구에게 갔다", "동탄", "LOC_FACILITY")["subject"] == "other"


@pytest.mark.parametrize("sentence,span,stype,expected", [
    # 인스턴스 재측정(10/5) — 1단이 꾸밈말까지 스팬에 넣은 경우 · 나이와 사람 사이 꾸밈말
    ("동탄 사는 친구가 놀러 왔다", "동탄 사는", "LOC_ADMIN", "other"),
    ("아홉 살 된 아들이 학교 간다", "아홉 살", "AGE", "other"),
    ("아홉 살짜리 아들이 떼를 쓴다", "아홉 살", "AGE", "other"),
    ("아홉 살인 아들이 학교 간다", "아홉 살", "AGE", "other"),
    ("아홉 살 된 아들이 학교 간다", "아홉 살 된", "AGE", "other"),
    # 본인 그대로
    ("나는 동탄 사는 직장인이야", "동탄 사는", "LOC_ADMIN", "self"),
    ("나는 동탄 사는 아빠야", "동탄", "LOC_ADMIN", "self"),          # 자기소개 — 지명 규칙에도 같은 예외
    ("나는 동탄 사는 친구를 만났다", "동탄", "LOC_ADMIN", "other"),
    ("마흔여덟 된 나는 요즘 무릎이 아프다", "마흔여덟", "AGE", "self"),
    ("서른 살인데 난 아들이 아직 없어", "서른 살인데", "AGE", "self"),      # Codex — 「난」은 1인칭
    ("내 직업은 회사원 난 아들이랑 저녁 먹으러 감", "회사원", "JOB", "self"),
])
def test_subject_modifier_between_clue_and_person(sentence, span, stype, expected):
    assert _r(sentence, span, stype)["subject"] == expected


@pytest.mark.parametrize("sentence,span,stype,expected", [
    # #306 리뷰(B) — 상대 호칭이 주어여도 술어가 그 사람의 속성이면 타인
    ("사장님은 부산역 앞에 산다", "부산역", "LOC_FACILITY", "other"),
    ("손님은 야간조로 일한다", "야간조로", "JOB", "other"),
    ("사장님은 2호선으로 출근한다", "2호선으로", "COMMUTE", "other"),
    # 내 일·생활의 상대가 내 일에 대해 말하는 경우는 그대로 본인
    ("사장님이 라떼아트에 한마디 했다", "라떼아트에", "JOB", "self"),
    ("단골 손님이 사진을 찾으러 왔다", "사진을", "JOB", "self"),
    ("옆집 아주머니가 회관 윷놀이 때 같은 편 하자고 했다", "회관", "LOC_FACILITY", "self"),
])
def test_counterpart_with_own_predicate_is_other(sentence, span, stype, expected):
    assert _r(sentence, span, stype)["subject"] == expected


@pytest.mark.parametrize("sentence,span,stype", [
    # Codex 검토 — 다른 절·명사의 술어로 타인이 되지 않는다
    ("사장님이 라떼아트에 한마디, 난 일하러 감ㅋㅋ", "라떼아트에", "JOB"),
    ("사장님이 라떼아트에 한마디, 내가 다니는 카페임", "라떼아트에", "JOB"),
    ("사장님이 라떼아트에 한마디 하더니 근무표 줌", "라떼아트에", "JOB"),
    ("사장님이 라떼아트에 한마디, 출근길부터 연습했는데ㅠ", "라떼아트에", "JOB"),
    ("손님이 포스에 한마디 할 때 근무표 알림 옴", "포스에", "JOB"),
    ("사장님이 2호선으로 오라길래 출근길 검색함", "2호선으로", "COMMUTE"),
    ("아주머니가 아이를 봐줘서 난 일하러 감", "아이를", "FAM"),
])
def test_counterpart_other_clause_predicate_stays_self(sentence, span, stype):
    assert _r(sentence, span, stype)["subject"] == "self"


@pytest.mark.parametrize("sentence,span,stype,expected", [
    # Codex 2차 — 연결 어미 뒤 다른 주체의 술어는 보지 않는다 (self 유지)
    ("사장님이 라떼아트에 한마디 해줘서 일하고 왔다", "라떼아트에", "JOB", "self"),
    ("손님이 포스에 불평해서 일하는 내내 신경 쓰였다", "포스에", "JOB", "self"),
    ("사장님이 라떼아트에 한마디 할 때 일하는 동료가 웃었다", "라떼아트에", "JOB", "self"),
    ("사장님이 라떼아트에 한마디 하고 일하는 내 모습을 찍어줬다", "라떼아트에", "JOB", "self"),
    ("사장님이 2호선으로 오라고 해서 출근하고 보니 휴무였다", "2호선으로", "COMMUTE", "self"),
    ("아주머니가 아이를 봐주면 일하고 올 수 있다", "아이를", "FAM", "self"),
    # 높임·합쇼체도 그 사람 속성
    ("사장님은 부산역 근처에 삽니다", "부산역", "LOC_FACILITY", "other"),
    ("손님은 야간조로 일하신다", "야간조로", "JOB", "other"),
])
def test_counterpart_predicate_must_follow_span(sentence, span, stype, expected):
    assert _r(sentence, span, stype)["subject"] == expected


@pytest.mark.parametrize("sentence,span,stype", [
    # Codex 3차 — 술어가 1인칭을 꾸미거나, 시키는·옮기는 말이면 본인 유지
    ("사장님이 야간조로 일하는 나를 불렀다", "야간조로", "JOB"),
    ("손님이 야간조로 일하는 내 모습을 찍었다", "야간조로", "JOB"),
    ("사장님이 2호선으로 출근하는 내게 연락했다", "2호선으로", "COMMUTE"),
    ("손님이 부산역 앞에 사는 내게 길을 물었다", "부산역", "LOC_FACILITY"),
    ("사장님이 부산역 근처에 살고 있는 나를 찾아왔다", "부산역", "LOC_FACILITY"),
    ("사장님이 야간조로 일해 보라고 했다", "야간조로", "JOB"),
    ("사장님이 2호선으로 출근하세요 하고 말했다", "2호선으로", "COMMUTE"),
    ("사장님이 야간조로 일하세요 하고 말했다", "야간조로", "JOB"),
])
def test_counterpart_predicate_about_me_or_directive_stays_self(sentence, span, stype):
    assert _r(sentence, span, stype)["subject"] == "self"


@pytest.mark.parametrize("sentence,span,expected", [
    # #308 리뷰(E) — 「X네」(그 집)는 주어 쪽 사람의 가족
    ("같이 화투 치던 양반이 딸네 있는 여수로 갔다", "딸네", "other"),
    ("옆집 아주머니가 아들네 갔다 오셨다", "아들네", "other"),
    ("사장님이 우리 딸네 왔다 가셨다", "딸네", "self"),
    # 「X네」가 아닌 가족 단서는 그대로 (「아내가 아이 데리러」 류)
    ("사장님이 아이를 봐주면 일하고 올 수 있다", "아이를", "self"),
])
def test_household_ne_belongs_to_actor(sentence, span, expected):
    assert _r(sentence, span, "FAM")["subject"] == expected



@pytest.mark.parametrize("sentence,span,expected", [
    # Codex 10/6 — 조사가 붙어도 주어 쪽 가족
    ("옆집 아주머니가 딸네는 자주 가셨다", "딸네는", "other"),
    ("옆집 아주머니가 딸네를 다녀오셨다", "딸네를", "other"),
    # 술어가 주어 자신의 이동·거주가 아니면 내 가족 그대로
    ("사장님이 언니네 데려다주셔서 오랜만에 언니를 만났다", "언니네", "self"),
    ("사장님이 동생네 김치를 보내 주셨다", "동생네", "self"),
])
def test_household_ne_needs_actor_predicate(sentence, span, expected):
    assert _r(sentence, span, "FAM")["subject"] == expected



@pytest.mark.parametrize("sentence,span,expected", [
    # Codex 10/6 재검토 — 흔한 활용형
    ("옆집 아주머니가 딸네로 가요", "딸네로", "other"),
    ("옆집 아주머니가 딸네에 갑니다", "딸네에", "other"),
    ("옆집 아주머니가 딸네에서 살았다", "딸네에서", "other"),
    # 사이에 명사가 끼거나 술어가 나를 꾸미면 내 가족
    ("사장님이 언니네 가족이 있는 곳까지 나를 데려다주셨다", "언니네", "self"),
    ("사장님이 언니네 있는 나를 데려다주셨다", "언니네", "self"),
])
def test_household_ne_conjugations_and_me(sentence, span, expected):
    assert _r(sentence, span, "FAM")["subject"] == expected



@pytest.mark.parametrize("sentence,span,expected", [
    ("옆집 아주머니가 딸네에 매일 간다", "딸네에", "other"),
    ("사장님이 언니네로 가려는 나를 데려다주셨다", "언니네로", "self"),
])
def test_household_ne_adverb_and_me_word(sentence, span, expected):
    assert _r(sentence, span, "FAM")["subject"] == expected


def test_household_ne_me_in_next_clause_is_not_modifier():
    """「[딸네로] 가셨는데 나를 보고」 — 다음 절의 「나를」은 술어가 꾸미는 말이 아니다 (Codex 10/6)."""
    assert _r("옆집 아주머니가 딸네로 가셨는데 나를 보고 손을 흔드셨다", "딸네로", "FAM")["subject"] == "other"


# ── 실제 글 시험(10/16)에서 찾은 오탐 — 글쓴이의 부모 · 여행지 ─────────────────────
def test_commute_fragment_is_unknown():
    """exp39 — 1단이 「오늘」 「갔다가」 「매일 타는」을 COMMUTE 로 잡으면 unknown. 교통 이름이 있으면(「GTX로」 「수인분당선으로」) 그대로."""
    body = "오늘 버스타서 시내 나가서 영화 봤다. 매일 타는 GTX로 갔다가 수인분당선으로 갈아탔다."
    for t in ("오늘", "시내 나가서", "갔다가"):
        assert _r(body, t, "COMMUTE")["subject"] == "unknown", t
    for t in ("버스타서", "GTX로", "수인분당선으로", "매일 타는"):
        assert _r(body, t, "COMMUTE")["subject"] == "self", t
    # 조각이 모여 된 통근 패턴은 그대로 (Codex 검토) — 세 어절 이상 · 두 어절에 반복 말
    for t in ("평일마다 새벽에 나가서 밤에 돌아오는", "매일 아침에 나가서 저녁에 돌아오는", "시내로 매일 다니는", "매일 다니는", "시내로 다니는", "시내로 다니며"):
        assert _r(t, t, "COMMUTE")["subject"] == "self", t


@pytest.mark.parametrize("sentence,span,expected", [
    # 자녀 입장 — 성별 단서로 잡힌 「아빠가」는 글쓴이의 아버지(남의 성별)
    ("엄마아빠가 혼자는 안 된다고 했다. 아빠가 진짜 싫다고 해서 엄마랑 나랑 옴", "아빠가", "other"),
    ("아빠가 그 정도는 괜찮대", "아빠가", "other"),               # 자녀 표지도 없다 → 글쓴이 부모
    ("아이참 아빠가 또 그러네", "아빠가", "other"),               # 「아이참」은 감탄사 — 자녀 표지가 아니다
    # 부모 블로거 — 자기를 「아빠」로 부른다 (골드 A23 관례)
    ("아이가 아빠는 여기 앉아 있으라고 자리를 정해 줬다", "아빠는", "self"),
    ("가족 다 자는 밤 혼자 맥주 한 캔 마시는 아빠의 유일한 시간", "아빠의", "self"),
    ("엄마들 단톡방에서 하원 시간 얘기가 나왔다", "엄마들", "self"),  # 복수 — 이 규칙 밖
])
def test_parent_term_sex_subject(sentence, span, expected):
    assert _r(sentence, span, "SEX")["subject"] == expected


@pytest.mark.parametrize("sentence,span,stype,expected", [
    ("일본에 디자인 여행이나 가 볼까", "일본에", "LOC_ADMIN", "unknown"),   # 여행지 — 사는 곳이 아니다
    ("이번 주말엔 부산 놀러 가요", "부산", "LOC_ADMIN", "unknown"),
    ("제주 여행 숙소 예약 끝", "제주", "LOC_ADMIN", "unknown"),
    ("농협에 들러 비료를 샀다", "농협에", "LOC_FACILITY", "self"),          # 동네 볼일 — 그대로 본인 (골드 관례)
    ("본가인 창원에 내려가면 꼭 먹는 국밥", "창원에", "LOC_ADMIN", "self"),  # 본가 — 그대로 본인
    ("친구가 대전 놀러 갔다가 사진을 보냈다", "대전", "LOC_ADMIN", "other"),  # 남의 것은 남의 것
])
def test_travel_place_is_not_home(sentence, span, stype, expected):
    assert _r(sentence, span, stype)["subject"] == expected


@pytest.mark.parametrize("sentence,span,stype,expected", [
    # Codex 반례 — 같은 문단 · 1인칭 자기소개 · 아들/딸 대칭
    ("가족 다 자는 밤 혼자 맥주 마시는 아빠의 유일한 시간\n\n내일은 부모님께 전화해야겠다.", "아빠의", "SEX", "self"),
    ("아빠가 반대했다.\n\n미국 하원 소식을 봤다.", "아빠가", "SEX", "other"),
    ("나는 아빠가 됐다", "아빠가", "SEX", "self"),
    ("아빠는 딸만 키운다", "아빠는", "SEX", "self"),
    ("아빠는 아들만 키운다", "아빠는", "SEX", "self"),
    # Codex 반례 — 여행 말이 지명을 꾸미지 않으면 그대로
    ("나는 서울에서 살며 여행을 즐긴다", "서울에서", "LOC_ADMIN", "self"),
    ("부산에서 여행사를 운영한다", "부산에서", "LOC_ADMIN", "self"),
    ("한국관광공사에서 매일 일한다", "한국관광공사", "LOC_FACILITY", "self"),
    ("서울\n\n휴가 끝나고 출근했다", "서울", "LOC_ADMIN", "self"),
])
def test_codex_counterexamples(sentence, span, stype, expected):
    assert _r(sentence, span, stype)["subject"] == expected


def test_travel_place_is_not_promoted_by_home_marker():
    """여행지(unknown) 위치는 같은 글의 「집 근처」(REL_HOME) 때문에 확실한 거주 단서로 오르지 않는다 (Codex)."""
    from kopl.c2_specificity.clues import build_conditions
    body = "집 근처에서 밥을 먹었다. 강남구 여행을 예약했다"
    spans = []
    for text, stype in (("집 근처에서", "REL_HOME"), ("강남구", "LOC_ADMIN")):
        i = body.index(text)
        spans.append({"span_id": f"p_s{len(spans) + 1:02d}", "text_id": "body", "start": i, "end": i + len(text),
                      "text": text, "type": stype, **resolve({"body": body}, {"text_id": "body", "start": i,
                                                                             "end": i + len(text), "text": text, "type": stype})})
    assert spans[1]["subject"] == "unknown"
    loc = [c for c in build_conditions(spans, "p") if c["axis"] == "location"]
    assert loc and all(c["confidence"] < 1.0 for c in loc)


@pytest.mark.parametrize("sentence,span,stype,expected", [
    # Codex 재검토 — 1인칭이 있어도 자기소개가 아니면 글쓴이의 아버지 · 「아이들이」 · 「제주 휴가」
    ("나는 아빠가 싫다", "아빠가", "SEX", "other"),
    ("아이들이 자는 밤 아빠의 시간", "아빠의", "SEX", "self"),
    ("제주 휴가를 다녀왔다", "제주", "LOC_ADMIN", "unknown"),
    ("서울 휴가 끝나고 출근했다", "서울", "LOC_ADMIN", "self"),
])
def test_codex_recheck(sentence, span, stype, expected):
    assert _r(sentence, span, stype)["subject"] == expected


@pytest.mark.parametrize("sentence,span,stype,expected", [
    ("나는 아빠였다", "아빠", "SEX", "self"),                    # Codex 3차 — 과거 · 이어 말하기 자기소개
    ("나는 엄마이고 직장인이다", "엄마", "SEX", "self"),
    ("서울 휴가철에도 출근한다", "서울", "LOC_ADMIN", "self"),     # 휴가철은 여행이 아니다
])
def test_codex_third(sentence, span, stype, expected):
    assert _r(sentence, span, stype)["subject"] == expected


@pytest.mark.parametrize("sentence,span,stype,expected", [
    # B 리뷰 — 짧은 자기소개 어미(다 · 자)가 「다쳤다」 「자랑스럽다」의 앞부분에 걸리면 안 된다
    ("나는 아빠가 자랑스럽다", "아빠가", "SEX", "other"),
    ("나는 엄마가 다쳤다는 소식을 들었다", "엄마가", "SEX", "other"),
    ("나는 엄마가 고마워서 울었다", "엄마가", "SEX", "other"),
    ("나는 아빠다.", "아빠", "SEX", "self"),
    ("나는 엄마인데요 요즘 바빠요", "엄마", "SEX", "self"),
    ("나는 아빠가 됐다", "아빠가", "SEX", "self"),
    ("나는 엄마로서는 아직 부족하다", "엄마", "SEX", "self"),   # Codex — 로서 뒤 조사
    ("나는 엄마인데도 육아가 어렵다", "엄마", "SEX", "self"),
    ("나는 엄마가 고요한 목소리로 부르는 노래를 좋아한다", "엄마가", "SEX", "other"),   # Codex — 고 + 요한
    ("나는 아빠고요 딸이 둘이에요", "아빠", "SEX", "self"),
])
def test_b_review_intro_suffix(sentence, span, stype, expected):
    assert _r(sentence, span, stype)["subject"] == expected


@pytest.mark.parametrize("sentence,span,stype,expected", [
    # exp42 R2 — 「나이 + 의 + 다른 사람」은 그 사람의 나이 (합성 문장)
    ("라디오에 70세의 한 청취자가 엽서를 보냈다.", "70세의", "AGE", "other"),
    ("마흔둘의 어느 여성이 편지를 보냈다.", "마흔둘의", "AGE", "other"),
    ("일흔의 시청자가 전화를 걸어왔다.", "일흔의", "AGE", "other"),
    ("예순넷의 봄 텃밭 준비", "예순넷의", "AGE", "self"),                 # 사람이 아니다
    ("마흔의 엄마로 산다는 것", "마흔의", "AGE", "self"),                 # 꾸밈말 없는 일반 사람 명사는 그대로
    ("나는 마흔의 한 여자일 뿐이다.", "마흔의", "AGE", "self"),           # 1인칭 자기소개
    ("강의에서 쉰두 살 수강생이 합격 후기를 말했다.", "쉰두 살", "AGE", "other"),   # 「의」 없이 남을 가리키는 사람 명사
    ("저는 49세 여성입니다.", "49세", "AGE", "self"),                     # 자기소개
    ("서른에 아이를 낳았다.", "서른에", "AGE", "self"),                     # 조사 붙은 나이는 뒤 사람을 꾸미지 않는다
    # 아이 나이 — label-schema 「[아홉 살] 아들」 = other
    ("세 살 아기인데 벌써 말을 잘한다.", "세 살 아기인데", "AGE", "other"),  # 1단이 아이 명사까지 스팬에 넣은 것
    ("네 살 저희 아기와 함께 갔다.", "네 살", "AGE", "other"),
    ("아이가 벌써 네 살이 됐다.", "네 살이", "AGE", "other"),
    ("세 살 때 이사했다고 들었다.", "세 살", "AGE", "self"),                # 「때」 — 글쓴이의 옛 나이
    ("세 살 키에 맞춘 의자를 샀다.", "세 살", "AGE", "unknown"),            # 주인이 문장에 없는 아기 나이
    ("18개월 무렵 걷기 시작했다.", "18개월", "AGE", "self"),
    ("마흔 살 키에 맞춘 의자", "마흔 살", "AGE", "self"),
    ("딸기 세 살 때부터 좋아했다.", "세 살", "AGE", "self"),                # 「딸기」는 아이가 아니다
    # exp42 R4 — 지명을 셋 이상 늘어놓은 줄의 항목은 unknown
    ("행사 지역은 📍강릉,📍경주,📍목포,📍순천 네 곳이다.", "경주", "LOC_ADMIN", "unknown"),
    ("대전, 통영, 속초 등에서 열린다.", "대전", "LOC_ADMIN", "unknown"),
    ("와인, 샴페인, 부산 지역 맥주를 마셨다.", "부산 지역", "LOC_ADMIN", "self"),   # 지명 나열이 아니다
    ("서울, 부산 두 곳을 오간다.", "서울", "LOC_ADMIN", "self"),                    # 둘은 나열로 보지 않는다
    ("나는 부산에 산다.", "부산에", "LOC_ADMIN", "self"),
])
def test_subject_exp42(sentence, span, stype, expected):
    assert _r(sentence, span, stype)["subject"] == expected
