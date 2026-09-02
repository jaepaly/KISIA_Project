"""스캔 파이프라인 — export JSON 하나가 들어와 진단 결과 하나가 나간다.

입력은 `GET /api/export/<user_ref>` 응답(sns-minimal-spec.md)뿐이다. DB 도, 파일도 안 읽는다.
결과는 호출자가 메모리에 들고 있다가 버린다 (E-system.md §2 「분석기는 어떤 DB 도 갖지 않는다」).

what-if(조치 시뮬레이션)는 같은 스팬 위에서 «이 글·이 태그·이 스팬을 빼면» 을 다시 세는 것이라
추천 엔진이 실제 계산으로 예상 효과를 낸다 — 예시값이 아니다.
"""

from __future__ import annotations

import re
from typing import Any

from .detect import detect_post, detect_profile
from .dialect import dominant_region
from .specificity import funnel, resolve_place, risk_label, risk_score

_DIRECT_ID = [
    ("전화번호", re.compile(r"01[016789]-?\d{3,4}-?\d{4}")),
    ("이메일", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("주민번호", re.compile(r"\d{6}-[1-4]\d{6}")),
]


def analyze(export: dict[str, Any]) -> dict[str, Any]:
    """export → 스팬·플래그·텍스트를 한 번 뽑아 둔 «뷰». funnel 은 뷰 위에서 여러 번 돈다."""
    posts = []
    for p in export.get("posts") or []:
        d = detect_post(p)
        posts.append({
            "post_id": p["post_id"],
            "texts": d["texts"],
            "spans": d["record"]["spans"],
            "flags": d["record"].get("flags") or {},
            "notes": d["notes"],
            "activity_meta": p.get("activity_meta") or {},
            "post_time": (p.get("activity_meta") or {}).get("post_time"),
        })
    prof = detect_profile(export["user_ref"], export.get("profile_bio"))
    direct = []
    for name, rx in _DIRECT_ID:
        for p in posts:
            for tid, txt in p["texts"].items():
                if rx.search(txt):
                    direct.append({"kind": name, "post_id": p["post_id"], "text_id": tid})
    return {
        "user_ref": export["user_ref"],
        "nickname": export.get("nickname"),
        "profile": {"texts": prof["texts"], "spans": prof["record"]["spans"] if prof["record"] else [],
                    "flags": (prof["record"] or {}).get("flags") or {}, "notes": prof["notes"]},
        "posts": posts,
        "direct_identifiers": direct,
    }


def _iter_spans(view: dict[str, Any], *, exclude_posts=frozenset(), exclude_spans=frozenset()):
    for p in view["posts"]:
        if p["post_id"] in exclude_posts:
            continue
        for sp in p["spans"]:
            if sp["span_id"] in exclude_spans:
                continue
            yield p["post_id"], sp, p["notes"].get(sp["span_id"], {}), p["texts"]
    for sp in view["profile"]["spans"]:
        if sp["span_id"] in exclude_spans:
            continue
        yield None, sp, view["profile"]["notes"].get(sp["span_id"], {}), view["profile"]["texts"]


def signals_from(view: dict[str, Any], *, exclude_posts=frozenset(), exclude_meta=frozenset(),
                 exclude_spans=frozenset()) -> dict[str, Any]:
    """스팬·플래그 → funnel 입력. subject=other 와 notes.exclude 가 붙은 스팬은 k 에 안 들어간다."""
    sig: dict[str, Any] = {"places": [], "age": None, "sex": None, "admin_unit": None,
                           "dialect_region": None, "dialect_src": None}
    hits: list[str] = []
    dialect_posts: list[str] = []
    for p in view["posts"]:
        if p["post_id"] in exclude_posts:
            continue
        h = p["flags"].get("dialect_hits") or []
        if h:
            hits.extend(h)
            dialect_posts.append(p["post_id"])
    hits.extend(view["profile"]["flags"].get("dialect_hits") or [])
    region = dominant_region(hits)
    if region:
        sig["dialect_region"] = region
        sig["dialect_src"] = {"post_id": None, "span_id": None, "channel": "flags.dialect_hits",
                              "text": " · ".join(sorted({h.split(":", 1)[1] for h in hits if h.startswith(region)})),
                              "posts": dialect_posts[:6]}

    for post_id, sp, note, _texts in _iter_spans(view, exclude_posts=exclude_posts, exclude_spans=exclude_spans):
        if sp["subject"] != "self" or note.get("exclude"):
            continue
        src = {"post_id": post_id, "span_id": sp["span_id"], "text": sp["text"], "channel": sp["text_id"]}
        t = sp["type"]
        if t == "LOC_ADMIN" and note.get("place"):
            sig["places"].append({"canonical": note["place"], "src": src})
        elif t == "LOC_FACILITY" and note.get("admin_unit"):
            if sig["admin_unit"] is None or note["admin_unit"] == "면":
                sig["admin_unit"] = {"unit": note["admin_unit"], "src": src}
        elif t == "AGE":
            cur = sig["age"]
            if note.get("age") is not None and (cur is None or cur.get("value") is None):
                sig["age"] = {"value": note["age"], "src": src}
            elif note.get("age_decade") is not None and (cur is None or (cur.get("value") is None and cur.get("decade") is None)):
                sig["age"] = {"decade": note["age_decade"], "src": src}
            elif note.get("age_min") is not None and cur is None:
                sig["age"] = {"min": note["age_min"], "src": src}
        elif t == "SEX" and note.get("sex") and sig["sex"] is None:
            sig["sex"] = {"value": note["sex"], "src": src}

    for p in view["posts"]:
        if p["post_id"] in exclude_posts or p["post_id"] in exclude_meta:
            continue
        g = p["activity_meta"].get("geo_tag")
        if g:
            canon = _canonical_geo(g)
            if canon:
                sig["places"].append({"canonical": canon, "src": {"post_id": p["post_id"], "span_id": None,
                                                                   "text": g, "channel": "geo_tag"}})
    return sig


def _canonical_geo(tag: str) -> str | None:
    """위치태그 문자열을 사전 정본 이름으로. 「담양군 창평면」 → 마지막 토큰을 상위 맥락으로 해석."""
    parts = tag.split()
    if not parts:
        return None
    from kopl.c2_specificity.engine import resolve, _get_default_dictionary
    cands = resolve(parts[-1], context=" ".join(parts[:-1]) or None)
    if len(cands) == 1:
        return _get_default_dictionary().regions[cands[0]]["full_name"]
    if resolve_place(tag):
        return tag
    return None


def compute(view: dict[str, Any], **exclusions) -> dict[str, Any]:
    sig = signals_from(view, **exclusions)
    f = funnel(sig)
    f["risk"] = risk_score(f["k"])
    f["label"], f["css"] = risk_label(f["k"])
    f["signals"] = sig
    return f


def findings(view: dict[str, Any], f: dict[str, Any]) -> dict[str, Any]:
    """7속성 판정 — stage2-io `findings`. 값이 아니라 «무엇이 특정 가능한가» 까지만.

    evidence 는 span_id 와 관계만 담는다. 실제 지명·나이 값은 여기 없다(계약 설계 제약 1).
    """
    ev: dict[str, list[dict[str, Any]]] = {a: [] for a in
                                            ("age", "sex", "location", "occupation", "family", "commute", "income")}
    posts_of: dict[str, set[str]] = {a: set() for a in ev}
    type_attr = {"AGE": "age", "SEX": "sex", "LOC_ADMIN": "location", "LOC_FACILITY": "location",
                 "REL_HOME": "location", "REL_WORK": "commute", "JOB": "occupation", "FAM": "family",
                 "COMMUTE": "commute", "INCOME": "income"}
    relation = {"LOC_FACILITY": "residence_proximity", "REL_HOME": "residence_proximity",
                "COMMUTE": "commute_link", "REL_WORK": "commute_link", "FAM": "family_structure",
                "INCOME": "temporal_pattern"}
    for post_id, sp, note, _ in _iter_spans(view):
        if sp["subject"] != "self" or note.get("exclude"):
            continue
        a = type_attr[sp["type"]]
        ev[a].append({"post_id": post_id, "span_id": sp["span_id"], "label": None,
                      "relation": relation.get(sp["type"])})
        posts_of[a].add(post_id or "profile")

    out: dict[str, Any] = {}
    steps = {s["axis"]: s for s in f["steps"]}
    loc_step = [s for s in f["steps"] if s["axis"] == "location"]
    for a, items in ev.items():
        if not items and not (a == "location" and loc_step):
            out[a] = {"verdict": "abstain", "granularity": None, "evidence": [], "confidence": 0.1, "cross_post": False}
            continue
        cross = len(posts_of[a]) > 1
        if a == "location" and loc_step:
            last = loc_step[-1]
            gran = {"dialect_region": "sido", "admin_unit": "sigungu", "admin_code": "eupmyeondong"}[last["kind"]]
            if last["kind"] == "admin_code":
                n_codes = f.get("n_codes", 1)
                gran = "eupmyeondong" if n_codes == 1 else ("sigungu" if n_codes < 40 else "sido")
            verdict = "specified" if gran == "eupmyeondong" else "narrowed"
            conf = 0.85 if verdict == "specified" else 0.6
            out[a] = {"verdict": verdict, "granularity": gran, "evidence": items, "confidence": conf,
                      "cross_post": cross or f["signals"].get("dialect_region") is not None}
        elif a == "age" and "age" in steps:
            age = f["signals"]["age"]
            gran = "exact_year" if age.get("value") is not None else ("decade" if age.get("decade") is not None else "category")
            out[a] = {"verdict": "specified" if gran == "exact_year" else "narrowed", "granularity": gran,
                      "evidence": items, "confidence": 0.9 if gran == "exact_year" else 0.55, "cross_post": cross}
        elif a == "sex" and f["signals"].get("sex"):
            out[a] = {"verdict": "specified", "granularity": "category", "evidence": items, "confidence": 0.7, "cross_post": cross}
        else:
            out[a] = {"verdict": "weak_signal", "granularity": "category", "evidence": items,
                      "confidence": 0.4, "cross_post": cross}
    return out


def evidence_posts(view: dict[str, Any]) -> list[dict[str, Any]]:
    """화면 「근거」 카드 — 스팬이 하나라도 있는 글만, 원문 그대로 + 스팬 좌표."""
    out = []
    for p in view["posts"]:
        if not p["spans"] and not p["flags"].get("dialect_hits"):
            continue
        out.append(p)
    return out
