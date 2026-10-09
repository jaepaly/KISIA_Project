"""글을 합치면 드러나는 시점 — 「날짜 + 경과 차수」(「26.09.03 출근 18일차」)에서 시작일을 역산한다.

한 글의 날짜나 차수는 흔하지만, 둘이 같이 있으면 **언제 시작했는지**가 나오고 여러 글이 같은 시작을 가리키면 확실해진다.
「8월 셋째 주에 인턴을 시작한 사람」은 다른 공개 기록(채용 공고 · 동기 글)과 맞춰 보기 쉽다.

계기: 동의받은 실제 글 내부 시험(10/8)에서 외부 LLM 검토자는 「출근 18일차 → 30일차 → 34일차」를 위험도 1순위로 꼽았는데,
우리 도구에는 이 유형이 없었다. 스팬 계약(label-schema 10유형) 밖의 화면 전용 경고로 둔다 (links.py 와 같은 방식).

    from kopl.c4_stage2.timeline import find_marks, infer_starts
    marks = {post_id: find_marks(texts) for ...}      # 글마다 [{text_id, start, end, date, event, n, unit, value}]
    infer_starts(marks)                                 # → [{event, start, start_range, basis, posts, n_marks}]
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

# 경과 차수 — 무엇의 몇 번째 날/주인지. 사건 말이 있어야 글끼리 묶을 수 있다
_EVENTS = r"출근|입사|근무|인턴|실습|알바|아르바이트|연수|교육|입대|복무|훈련|전역|휴직|육아휴직|이직|퇴사|등교|개강|입학|이사|자취|운동|다이어트|금연|금주|공부|수험|재수|취준"
_COUNT = re.compile(
    r"(?P<event>" + _EVENTS + r")\s*(?:한\s*지\s*)?(?P<n>\d{1,3})\s*(?P<unit>일차|일째|주차|주째|개월차|개월째|달째)"
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


def find_marks(texts: Mapping[str, str | None]) -> list[dict[str, Any]]:
    """채널별 원문 → 날짜와 짝지은 경과 차수. 날짜가 없는 차수는 역산할 수 없어 내지 않는다.

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
    out: list[dict[str, Any]] = []
    for m in _COUNT.finditer(joined):
        if m.group("dplus"):
            # D+ 는 무엇을 셌는지 말이 없다 — 바로 앞 낱말(「커플」 「시험」)로 갈라, 다른 일끼리 묶이지 않게 (Codex 10/9)
            prev = re.findall(r"[가-힣A-Za-z]+", joined[max(0, m.start() - 12):m.start()].split("\n")[-1])
            event, n, unit = ("D+ " + prev[-1]) if prev else "D+", int(m.group("dn")), "일째"
            n += 1  # D+0 이 첫날 — 「D+30」은 31일째
        else:
            event, n, unit = m.group("event"), int(m.group("n")), m.group("unit")
        if n < 1:
            continue
        near = [(abs((s + e) / 2 - (m.start() + m.end()) / 2), dt, s, e) for s, e, dt in ds
                if min(abs(m.start() - e), abs(s - m.end())) <= _PAIR_WINDOW
                and not _broken(joined[min(e, m.end()):max(s, m.start())])]
        if not near:
            continue
        _, dt, ds_s, ds_e = min(near, key=lambda x: x[0])
        tid, st = locate(m.start())
        dtid, dst = locate(ds_s)
        out.append({"text_id": tid, "start": st, "end": st + (m.end() - m.start()), "value": m.group(0),
                    "date": dt.isoformat(), "date_text_id": dtid, "date_start": dst, "date_end": dst + (ds_e - ds_s),
                    "date_value": joined[ds_s:ds_e], "event": event, "n": n, "unit": unit})
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


def _clusters(items: list[tuple[str, dict[str, Any]]], basis: str) -> list[list[tuple[str, dict[str, Any], date, date]]]:
    rows = sorted(((pid, mk, *_start_interval(mk, basis)) for pid, mk in items), key=lambda r: r[2])
    out: list[list[tuple[str, dict[str, Any], date, date]]] = []
    for r in rows:
        if out:
            lo = max([x[2] for x in out[-1]] + [r[2]])
            hi = min([x[3] for x in out[-1]] + [r[3]])
            if (lo - hi).days <= _TOLERANCE:  # 묶음 전체가 (오차 안에서) 같은 시작을 가질 때만 — 사슬로 늘어나지 않게 (Codex 10/9)
                out[-1].append(r)
                continue
        out.append([r])
    return out


def infer_starts(marks_by_post: Mapping[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """시작일 역산. 같은 사건 말 안에서 **시작 구간이 겹치는 글끼리만** 묶는다 (Codex 10/9).

    - 「커플 D+30」과 「시험 D+31」, 「수영 운동」과 「헬스 운동」처럼 같은 말로 다른 일을 센 글은 시작이 갈려 따로 묶인다.
      어긋난 글이 하나 끼어도 맞는 글끼리의 경고는 남는다
    - 근무일(주말 뺌) 셈은 출근 · 근무 · 인턴 같은 일에만, 「n일차/일째」에만 쓴다. D+ · 운동 · 주 · 개월은 달력으로 센다
    - 글 하나짜리 묶음도 낸다 (n_posts 1 — 화면은 「이 글만으로도」라고 약하게)
    """
    by_event: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for pid, marks in marks_by_post.items():
        for mk in marks:
            by_event.setdefault(mk["event"], []).append((pid, mk))
    out: list[dict[str, Any]] = []
    for event, items in by_event.items():
        bases = ["calendar"]
        if event in _WORK_EVENTS and any(mk["unit"] in ("일차", "일째") for _, mk in items):
            bases.append("business")
        best = None
        for basis in bases:
            cl = _clusters(items, basis)
            key = (-max(len({r[0] for r in c}) for c in cl), len(cl))  # 가장 큰 묶음의 글 수 · 묶음 수가 적을수록
            if best is None or key < best[0]:
                best = (key, basis, cl)
        _, basis, cl = best
        for c in cl:
            lo, hi = max(r[2] for r in c), min(r[3] for r in c)  # 공통 구간 · 점들이 오차 안에서 어긋나면 그 사이
            lo, hi = min(lo, hi), max(lo, hi)
            posts = sorted({r[0] for r in c})
            out.append({"event": event, "start": lo.isoformat() if lo == hi else None,
                        "start_range": [lo.isoformat(), hi.isoformat()], "basis": basis,
                        "posts": posts, "n_posts": len(posts), "n_marks": len(c),
                        "marks": [{"post_id": r[0], **r[1]} for r in c]})
    return sorted(out, key=lambda x: (-x["n_posts"], x["event"], x["start_range"][0]))
