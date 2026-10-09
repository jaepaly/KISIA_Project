"""글을 합치면 드러나는 시점 — 날짜 + 경과 차수 역산 (합성 문장만).

실행:
    python -m pytest src/kopl/c4_stage2/test_timeline.py -v
"""

import pytest

from kopl.c4_stage2.timeline import find_marks, infer_starts


def _marks(posts):
    return {pid: find_marks(texts) for pid, texts in posts.items()}


def test_cross_post_points_to_one_start_with_business_days():
    posts = {
        "a": {"title": "26.09.03 출근 18일차", "body": "오늘도 일했다"},
        "b": {"title": "인턴일지", "body": "26.09.22 출근 30일차. 간식을 받았다"},
        "c": {"body": "2026년 9월 30일, 출근 34일차. 남은 3일"},
    }
    out = infer_starts(_marks(posts))
    assert len(out) == 1
    ev = out[0]
    assert ev["event"] == "출근" and ev["posts"] == ["a", "b", "c"] and ev["basis"] == "business"
    lo, hi = ev["start_range"]
    assert "2026-08-10" <= lo <= hi <= "2026-08-17"  # 8월 둘째~셋째 주 시작


def test_marks_keep_channel_offsets():
    texts = {"title": "26.09.03 출근 18일차", "body": "본문에는 26.09.04 입사 2일째"}
    for mk in find_marks(texts):
        assert texts[mk["text_id"]][mk["start"]:mk["end"]] == mk["value"]
        assert texts[mk["date_text_id"]][mk["date_start"]:mk["date_end"]] == mk["date_value"]


@pytest.mark.parametrize("texts", [
    {"body": "출근 18일차. 오늘도 일했다"},                  # 날짜가 없으면 역산 못 한다
    {"body": "26.09.03 오늘은 쉬었다"},                     # 차수가 없다
    {"body": "오늘 점수는 4.5점, 3.5km 걸었다"},             # 소수 · 거리
    {"body": "9월 3일 출근 18일차"},                         # 연도를 모르는 날짜만 있으면 역산하지 않는다
    {"body": "26.09.03 회의 18일차"},                        # 묶을 수 있는 사건 말이 아니다
    {"body": "버전 12.2.3 운동 3일차"},                      # 버전 번호 (Codex 10/9)
    {"body": "24.5.1kg 운동 3일차"},                         # 단위가 붙은 수
    {"body": "1.2.3.4 운동 3일차"},
    {"body": "24.5.1kg으로 운동 3일차"},                     # 단위 뒤 조사
    {"body": "26.09.03 장보기. 한참 뒤에 적는다. 이것저것 정리하고 나서야 생각났는데 출근 18일차였다"},  # 너무 멀다
])
def test_no_marks(texts):
    assert find_marks(texts) == []


def test_date_in_title_and_count_on_next_line_pair():
    # 제목에 날짜 · 본문 첫 줄에 차수 — 실제 일지 글에 흔한 모양
    assert [m["n"] for m in find_marks({"title": "26.09.22", "body": "출근 30일차\n오늘은 바빴다"})] == [30]
    assert find_marks({"title": "26.09.22", "body": "\n\n오늘은 바빴다\n\n출근 30일차"}) == []


def test_month_day_uses_year_from_same_post():
    mk = find_marks({"body": "2026.09.01 다짐. 9월 3일 운동 3일차"})
    assert [(m["event"], m["date"]) for m in mk] == [("운동", "2026-09-03")]


def test_dplus_and_weeks():
    out = infer_starts(_marks({"a": {"body": "26.10.01 D+30"}, "b": {"body": "25.10.01 운동 3주차"}}))
    got = {e["event"]: e["start_range"] for e in out}
    assert got["D+"] == ["2026-09-01", "2026-09-01"]   # D+0 이 첫날 · 달력으로 센다
    assert got["운동"] == ["2025-09-11", "2025-09-17"]  # 3주차 = 15~21일째 — 시작은 범위다 (Codex 10/9)


def test_same_word_different_starts_are_not_merged():
    # 같은 말로 다른 일을 센 것 — 시작이 갈리면 따로 묶이고, 여러 글 묶음으로 올리지 않는다
    out = infer_starts(_marks({"a": {"body": "25.01.05 운동 3일차"}, "b": {"body": "25.06.10 운동 5일차"}}))
    assert all(e["n_posts"] == 1 for e in out)


def test_dplus_of_different_things_not_merged_and_calendar_only():
    out = infer_starts(_marks({"a": {"body": "26.10.01 커플 기념일 D+30"}, "b": {"body": "26.10.15 커플 D+40"}}))
    assert all(e["basis"] == "calendar" for e in out)                      # D+ 는 근무일로 세지 않는다
    assert all(e["n_posts"] == 1 for e in out)                             # 9/1 · 9/5 — 근무일로 억지로 맞추지 않는다


def test_one_mismatch_does_not_erase_matching_group():
    out = infer_starts(_marks({"a": {"body": "26.01.03 수영 운동 3일차"}, "b": {"body": "26.01.04 수영 운동 4일차"},
                               "c": {"body": "26.06.10 헬스 운동 5일차"}}))
    top = out[0]
    assert top["n_posts"] == 2 and top["posts"] == ["a", "b"] and top["start"] == "2026-01-01"


def test_months_range():
    out = infer_starts(_marks({"a": {"body": "26.03.01 자취 2개월차"}}))
    assert out[0]["start_range"] == ["2026-01-02", "2026-02-01"]  # 2개월차 = 1개월 지나고 2개월 안 됨


def test_single_post_is_reported_with_one_post():
    out = infer_starts(_marks({"a": {"body": "26.03.10 입사 5일차"}}))
    # 입사 · 출근 같은 일은 근무일로 센다 — 26.03.10(화)의 5번째 근무일 시작 = 3/4(수)
    assert out and out[0]["n_posts"] == 1 and out[0]["start"] == "2026-03-04" and out[0]["strength"] == "weak"


def test_date_trailing_dot_still_pairs():
    assert [m["n"] for m in find_marks({"body": "26.9.3. 출근 18일차"})] == [18]


def test_dplus_split_by_preceding_word():
    out = infer_starts(_marks({"a": {"body": "26.10.01 커플 D+30"}, "b": {"body": "26.10.02 시험 D+31"}}))
    assert sorted(e["event"] for e in out) == ["D+ 시험", "D+ 커플"] and all(e["n_posts"] == 1 for e in out)
    same = infer_starts(_marks({"a": {"body": "26.10.01 커플 D+30"}, "b": {"body": "26.10.11 커플 D+40"}}))
    assert same[0]["n_posts"] == 2 and same[0]["start"] == "2026-09-01"


def test_intervals_do_not_chain_across_months():
    posts = {f"m{m}": {"body": f"26.{m:02d}.28 자취 2개월차"} for m in range(3, 9)}
    assert all(e["n_posts"] <= 2 for e in infer_starts(_marks(posts)))


def test_post_date_anchor_mixed_words_and_no_word():
    # 코퍼스 A13 · E02 모양 — 본문 날짜 없이 작성일 + 「n주차」. 말이 제각각이거나 없어도 3편 이상이 같은 시작이면 낸다
    posts = {"a": ({"title": "워홀 1주차 장바구니"}, "2026-03-02"), "b": ({"title": "시드니 4주차 야식"}, "2026-03-26"),
             "c": ({"title": "블로그 8주차 이어폰"}, "2026-04-25"), "d": ({"title": "13주차: 날파리"}, "2026-05-31")}
    out = infer_starts({p: find_marks(t, post_date=d) for p, (t, d) in posts.items()})
    assert out[0]["n_posts"] == 4 and out[0]["anchor"] == "post_date" and out[0]["start_range"][0] <= "2026-03-02"
    no_word = {f"e{i}": ({"title": f"{n}주차: 하루"}, d) for i, (n, d) in
               enumerate([(1, "2026-03-02"), (3, "2026-03-18"), (5, "2026-04-01"), (11, "2026-05-17")])}
    assert infer_starts({p: find_marks(t, post_date=d) for p, (t, d) in no_word.items()})[0]["n_posts"] == 4


def test_repeated_same_count_is_a_cycle_not_a_start():
    # 「야간 3일차」가 다른 날 두 번 — 교대 근무 주기이지 하나의 시작이 아니다 (코퍼스 D12)
    posts = {"a": ({"body": "야간 3일차"}, "2026-03-17"), "b": ({"body": "야간 3일차"}, "2026-03-20")}
    assert infer_starts({p: find_marks(t, post_date=d) for p, (t, d) in posts.items()}) == []


def test_post_date_only_single_unknown_word_is_not_reported():
    assert infer_starts({"a": find_marks({"body": "블로그 시작한 지 3주째"}, post_date="2026-03-17")}) == []


def test_역산이_날짜_범위를_넘으면_그_차수만_버린다():
    """작성일 0001-01-01 + 「운동 2일차」 · 아주 큰 차수 — 예외 없이 빈 결과 (Codex 10/9)"""
    marks = {"p1": find_marks({"body": "운동 2일차"}, "0001-01-01"),
             "p2": find_marks({"body": "운동 3일차"}, "0001-01-02"),
             "p3": find_marks({"body": "출근 999999일차"}, "2026-03-02")}
    assert infer_starts(marks) == []


def test_상한은_역산_전에_자른다(monkeypatch):
    import kopl.c4_stage2.timeline as tl
    calls = []
    real = tl._start_interval
    monkeypatch.setattr(tl, "_start_interval", lambda mk, b: calls.append(1) or real(mk, b))
    marks = {f"p{i}": find_marks({"body": "운동 3일차"}, "2026-03-04") for i in range(1000)}
    tl.infer_starts(marks)
    assert len(calls) <= tl._MAX_MARKS

