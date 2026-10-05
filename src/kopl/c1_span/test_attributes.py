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
