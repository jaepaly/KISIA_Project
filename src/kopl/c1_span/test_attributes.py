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
