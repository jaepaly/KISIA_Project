"""글을 합치면 드러나는 시점 — 「날짜 + 경과 차수」(「26.09.03 출근 18일차」)에서 시작일을 역산한다.

한 글의 날짜나 차수는 흔하지만, 둘이 같이 있으면 **언제 시작했는지**가 나오고 여러 글이 같은 시작을 가리키면 확실해진다.
「8월 셋째 주에 인턴을 시작한 사람」은 다른 공개 기록(채용 공고 · 동기 글)과 맞춰 보기 쉽다.

계기: 동의받은 실제 글 내부 시험(10/8)에서 외부 LLM 검토자는 「출근 18일차 → 30일차 → 34일차」를 위험도 1순위로 꼽았는데,
우리 도구에는 이 유형이 없었다. 스팬 계약(label-schema 10유형) 밖의 화면 전용 경고로 둔다 (links.py 와 같은 방식).

    from kopl.c4_stage2.timeline import find_marks, infer_starts
    marks = {post_id: find_marks(texts, post_date="2026-04-01") for ...}   # 글마다 [{text_id, start, end, date, anchor, event, n, unit, value}]
    infer_starts(marks)                                 # → [{event, words, start, start_range, basis, posts, n_posts, strength}]

기준점(10/9 일반화): 본문 날짜(「26.09.03」)와 짝지은 차수를 먼저 쓰고, 없으면 **글 작성일**(post_date)을 쓴다. 코퍼스 3,392편에는
본문 날짜가 0편이었지만, A13 은 작성일 + 「워홀 n주차」 28편 중 27편이 같은 3월 초 시작을 가리켰다 — 본문 날짜만 보면 전부 놓친다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

# 날짜 — 연도가 있는 것만 (「9월 3일」은 연도를 모르면 역산이 흔들린다 · 같은 글에 연도 있는 날짜가 있으면 그 해로 읽는다)
# 앞뒤에 숫자 · 점 · 버전 표시가 붙거나 뒤에 단위가 오면 날짜가 아니다 — 「버전 12.2.3」 「24.5.1kg」 「1.2.3.4」 (Codex 10/9)
_DATE_FULL = re.compile(r"(?<![\d.vV])(?:(20)?(\d{2}))[./-]\s?(\d{1,2})[./-]\s?(\d{1,2})"
                        r"(?![\d.]\d|\d|\s?(?:kg|km|cm|mm|g|m|l|L|%|원|점|배|개|명|회|위|번|분|초|시간|kcal)(?![A-Za-z]))")  # 「kg으로」도 단위
_VERSION_BEFORE = re.compile(r"(?:버전|ver\.?|version|v)\s*$", re.IGNORECASE)
_DATE_MD = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_DATE_YMD_KO = re.compile(r"(?<!\d)(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")

# 경과 차수 — 무엇의 몇 번째 날/주인지. 아래 사건 말은 「알려진 사건」(글 하나로도 약하게 낸다) · 그 밖의 말도 차수는 잡는다
_EVENTS = r"출근|입사|근무|인턴|실습|알바|아르바이트|연수|교육|입대|복무|훈련|전역|휴직|육아휴직|이직|퇴사|등교|개강|입학|이사|자취|운동|다이어트|금연|금주|공부|수험|재수|취준"
_KNOWN = set(_EVENTS.split("|"))
_COUNT = re.compile(
    r"(?:(?P<event>[가-힣A-Za-z]{1,8})\s*(?:한\s*지\s*)?)?(?<![\d.])(?P<n>\d{1,3})\s*(?P<unit>일차|일째|주차|주째|개월차|개월째|달째)"
    r"|(?P<dplus>[Dd]\s*\+\s*(?P<dn>\d{1,4}))")
_UNIT_DAYS = {"일차": 1, "일째": 1, "주차": 7, "주째": 7, "개월차": 30, "개월째": 30, "달째": 30}
_PAIR_WINDOW = 40  # 날짜와 차수가 이 글자 안에 있어야 짝으로 본다 (제목 「26.09.03 출근 18일차」 · 본문 첫 줄)
_SENT_BREAK = re.compile(r"[.!?。…]\s")  # 짝 사이에 문장이 끊기면 다른 이야기다


def _broken(gap: str) -> bool:
    """날짜와 차수 사이가 끊겼나 — 문장 부호, 또는 빈 줄 · 긴 줄바꿈. 「26.09.22⏎출근 30일차」(제목 · 첫 줄)는 잇는다"""
    gap = gap[1:] if gap.startswith(".") else gap  # 「26.9.3. 출근」 — 날짜 끝 점은 문장 끝이 아니다 (Codex 10/9)
    return bool(_SENT_BREAK.search(gap)) or gap.count("\n") >= 2 or ("\n" in gap and len(gap.strip()) > 15)


def _valid(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _dates(text: str) -> list[tuple[int, int, date]]:
    out: list[tuple[int, int, date]] = []
    years: list[int] = []
    for m in _DATE_YMD_KO.finditer(text):
        dt = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            out.append((m.start(), m.end(), dt))
            years.append(dt.year)
    for m in _DATE_FULL.finditer(text):
        if any(s <= m.start() < e for s, e, _ in out) or _VERSION_BEFORE.search(text[max(0, m.start() - 10):m.start()]):
            continue
        y = 2000 + int(m.group(2))
        dt = _valid(y, int(m.group(3)), int(m.group(4)))
        if dt:
            out.append((m.start(), m.end(), dt))
            years.append(dt.year)
    if years:  # 「9월 3일」은 같은 글의 연도로만 읽는다
        y = max(set(years), key=years.count)
        for m in _DATE_MD.finditer(text):
            if any(s <= m.start() < e for s, e, _ in out):
                continue
            dt = _valid(y, int(m.group(1)), int(m.group(2)))
            if dt:
                out.append((m.start(), m.end(), dt))
    return sorted(out, key=lambda x: x[0])


def find_marks(texts: Mapping[str, str | None], post_date: str | None = None) -> list[dict[str, Any]]:
    """채널별 원문 → 기준 날짜와 짝지은 경과 차수. 본문 날짜가 없으면 post_date(글 작성일 · YYYY-MM-DD…)를 쓴다.
    기준 날짜가 하나도 없는 차수는 역산할 수 없어 내지 않는다.

    채널을 하나로 이어 본다 — 제목에 날짜, 본문 첫 줄에 차수가 있는 글이 흔하다. 오프셋은 각 채널 기준이다.
    """
    joined, spans_of = "", []
    for tid, t in texts.items():
        if not t:
            continue
        spans_of.append((tid, len(joined), t))
        joined += t + "\n"

    def locate(pos: int) -> tuple[str, int]:
        for tid, base, t in spans_of:
            if base <= pos <= base + len(t):
                return tid, pos - base
        return spans_of[-1][0], pos - spans_of[-1][1]

    ds = _dates(joined)
    pdate = None
    if post_date:
        try:
            pdate = date.fromisoformat(str(post_date)[:10])
        except ValueError:
            pdate = None
    out: list[dict[str, Any]] = []
    for m in _COUNT.finditer(joined):
        if m.group("dplus"):
            # D+ 는 무엇을 셌는지 말이 없다 — 바로 앞 낱말(「커플」 「시험」)로 갈라, 다른 일끼리 묶이지 않게 (Codex 10/9)
            prev = re.findall(r"[가-힣A-Za-z]+", joined[max(0, m.start() - 12):m.start()].split("\n")[-1])
            event, n, unit = ("D+ " + prev[-1]) if prev else "D+", int(m.group("dn")), "일째"
            n += 1  # D+0 이 첫날 — 「D+30」은 31일째
        else:
            event, n, unit = (m.group("event") or "?"), int(m.group("n")), m.group("unit")
        if n < 1:
            continue
        near = [(abs((s + e) / 2 - (m.start() + m.end()) / 2), dt, s, e) for s, e, dt in ds
                if min(abs(m.start() - e), abs(s - m.end())) <= _PAIR_WINDOW
                and not _broken(joined[min(e, m.end()):max(s, m.start())])]
        tid, st = locate(m.start())
        mark = {"text_id": tid, "start": st, "end": st + (m.end() - m.start()), "value": m.group(0),
                "event": event, "n": n, "unit": unit}
        if near:
            _, dt, ds_s, ds_e = min(near, key=lambda x: x[0])
            dtid, dst = locate(ds_s)
            out.append({**mark, "date": dt.isoformat(), "anchor": "text", "date_text_id": dtid, "date_start": dst,
                        "date_end": dst + (ds_e - ds_s), "date_value": joined[ds_s:ds_e]})
        elif pdate is not None:
            out.append({**mark, "date": pdate.isoformat(), "anchor": "post_date"})
    return out


def _business_back(d: date, n_days: int) -> date:
    """n 번째 근무일이 d 일 때 첫 근무일 (주말만 뺀다 · 공휴일은 모른다)"""
    cur, left = d, n_days - 1
    while left > 0:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            left -= 1
    return cur


_WORK_EVENTS = {"출근", "입사", "근무", "인턴", "실습", "알바", "아르바이트", "연수", "교육", "등교"}  # 근무일로 셀 수 있는 사건
_MAX_MARKS_PER_POST = 3
_MAX_MARKS = 400
_TOLERANCE = 3  # 시작 구간끼리 이 날수 안에서 겹치면 같은 시작으로 본다


def _sub_months(d: date, k: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - k, 12)
    m += 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return date(y, m, 28)


def _start_interval(mk: Mapping[str, Any], basis: str) -> tuple[date, date]:
    """시작일이 될 수 있는 구간 [lo, hi]. 일 단위는 한 점, 주 · 개월은 범위다 (3주차 → 15~21일째 · Codex 10/9)"""
    d, n, unit = date.fromisoformat(mk["date"]), mk["n"], mk["unit"]
    if unit in ("주차", "주째"):
        return d - timedelta(days=7 * n - 1), d - timedelta(days=7 * (n - 1))
    if unit in ("개월차", "개월째", "달째"):
        return _sub_months(d, n) + timedelta(days=1), _sub_months(d, n - 1)
    if basis == "business":
        s = _business_back(d, n)
        return s, s
    s = d - timedelta(days=n - 1)
    return s, s


def _stab(rows: list[tuple[str, dict[str, Any], date, date]]) -> list[list[tuple[str, dict[str, Any], date, date]]]:
    """구간들을 「가장 많은 구간이 공통으로 품는 날」부터 묶는다 — 정렬 순서에 끌려 이상치가 묶음을 깨지 않게 (10/9).

    한 날 p 를 (오차 안에서) 품는 구간끼리 한 묶음 → 빼고 반복. 같으면 이른 날.
    p 마다 품는 수는 정렬 + 이분 탐색으로 센다 — 한 바퀴 O(m log m) (Codex 10/9: 단순 반복은 O(m³) 라 수백 개에서 수십 초)
    """
    from bisect import bisect_left, bisect_right

    tol = timedelta(days=_TOLERANCE)
    left = list(rows)
    out = []
    while left:
        los = sorted(r[2] - tol for r in left)
        his = sorted(r[3] + tol for r in left)
        best_p, best_n = None, -1
        for q in sorted({r[2] for r in left} | {r[3] for r in left}):
            n = bisect_right(los, q) - bisect_left(his, q)  # lo-tol ≤ q 인 수 − hi+tol < q 인 수
            if n > best_n:
                best_p, best_n = q, n
        best = [r for r in left if r[2] - tol <= best_p <= r[3] + tol]
        out.append(best)
        ids = {id(r) for r in best}
        left = [r for r in left if id(r) not in ids]
    return out


def _basis(mk: Mapping[str, Any]) -> str:
    return "business" if mk["event"] in _WORK_EVENTS and mk["unit"] in ("일차", "일째") else "calendar"


def _distinct_n(c) -> int:
    return len({(r[1]["n"], r[1]["unit"]) for r in c})


def _report(c, words: list[str]) -> dict[str, Any]:
    lo, hi = max(r[2] for r in c), min(r[3] for r in c)  # 공통 구간 · 점들이 오차 안에서 어긋나면 그 사이
    lo, hi = min(lo, hi), max(lo, hi)
    posts = sorted({r[0] for r in c})
    anchors = {r[1].get("anchor", "text") for r in c}
    return {"event": words[0] if len(words) == 1 else "여러 표현", "words": words,
            "start": lo.isoformat() if lo == hi else None, "start_range": [lo.isoformat(), hi.isoformat()],
            "basis": "business" if all(_basis(r[1]) == "business" for r in c) else "calendar",
            "anchor": "text" if anchors == {"text"} else ("post_date" if anchors == {"post_date"} else "mixed"),
            "posts": posts, "n_posts": len(posts), "n_marks": len(c),
            "strength": "strong" if len(posts) >= 2 else "weak",
            "marks": [{"post_id": r[0], **r[1]} for r in c]}


def infer_starts(marks_by_post: Mapping[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """시작일 역산 — 두 단계로 묶는다.

    1. 같은 사건 말 안에서 시작 구간이 겹치는 글끼리 (「커플 D+30」과 「시험 D+31」, 「수영 운동」과 「헬스 운동」은 따로)
    2. 사건 말이 달라도 **3편 이상**이 같은 시작을 가리키면 하나로 — 「워홀 3주차 · 시드니 7주차 · 블로그 9주차」(A13)
    낼 것: 글 2편 이상 묶음(strong) · 글 1편이라도 알려진 사건 말(출근 · 인턴 · D+ …)이고 본문 날짜가 기준인 것(weak).
    근무일(주말 뺌) 셈은 출근 · 인턴 같은 일의 n일차에만. 나머지는 달력으로 센다.
    """
    # 글마다 차수 앞 3개 · 전체 400개까지만 — 일지 계정이 글마다 차수를 수십 개 써도 분석이 늘어지지 않게 (Codex 10/9)
    rows = [(pid, mk, *_start_interval(mk, _basis(mk)))
            for pid, marks in marks_by_post.items() for mk in marks[:_MAX_MARKS_PER_POST]][:_MAX_MARKS]
    by_word: dict[str, list] = {}
    for r in rows:
        by_word.setdefault(r[1]["event"], []).append(r)
    groups = [(w, c) for w, rs in by_word.items() for c in _stab(rs)]
    # 2단계 — 사건 말이 다른 묶음끼리 3편 이상이면 합친다
    merged: list[list] = []
    used: set[int] = set()
    big = _stab([r for _, c in groups for r in c])
    for c in big:
        words = sorted({r[1]["event"] for r in c})
        if len(words) >= 2 and len({r[0] for r in c}) >= 3 and _distinct_n(c) >= 2:
            merged.append(c)
            used |= {id(r) for r in c}
    out = [_report(c, sorted({r[1]["event"] for r in c})) for c in merged]
    for w, c in groups:
        c = [r for r in c if id(r) not in used]
        if not c:
            continue
        n_posts = len({r[0] for r in c})
        known = w in _KNOWN or w.startswith("D+")
        text_anchored = all(r[1].get("anchor", "text") == "text" for r in c)
        # 같은 차수만 되풀이(「야간 3일차」 ×2)면 하나의 시작이 아니라 반복 주기다 — 차수가 둘 이상 달라야 묶음 (코퍼스 D12 · 10/9)
        # 사건 말이 없는 차수(「1주차: …」 제목)도 3편 이상이 같은 시작을 가리키면 낸다 (코퍼스 E02 · 10/9)
        multi = _distinct_n(c) >= 2 and (n_posts >= 3 or (n_posts >= 2 and w != "?"))
        if multi or (n_posts == 1 and known and text_anchored):
            out.append(_report(c, [w]))
    return sorted(out, key=lambda x: (-x["n_posts"], x["event"], x["start_range"][0]))
