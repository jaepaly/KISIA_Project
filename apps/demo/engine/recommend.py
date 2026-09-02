"""조치 추천 — D-stage2.md §2 조치 3종 + 예외 1, 출력은 stage2-io.schema.json `Stage2Output` 꼴.

예상 효과는 예시값이 아니다. 조치 하나를 적용한 상태로 깔때기를 다시 세서 k' 를 낸다.
부담 오름차순으로 낸다 — ① 부분 비공개(low) · ② 활동 메타(low) · ③ 리라이트(medium/high).
④ 삭제 권고는 `exceptional` 로 분리하고 기본 추천에 올리지 않는다.

리라이트는 후보 3안이다. 현행 계약의 `Rewrite.suggestion` 은 단수라, **같은 span_id 로 Rewrite
레코드를 3개** 낸다 — 계약을 바꾸지 않고도 복수 후보를 실을 수 있다는 것을 보이는 방식이다.
(`suggestions` 배열로 계약을 손볼지는 팀 논점 — README §미결)
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import external
from .pipeline import compute, findings
from .specificity import dict_version

MODEL_VERSION = "demo-rules-0.1.0"

# 인물 말투를 살린 손질 후보 — 외부 LLM 이 꺼져 있을 때 쓰는 캐시.
# 키는 스팬 원문. 없으면 유형별 일반 후보로 떨어진다.
_CACHE: dict[str, list[dict[str, str]]] = {
    "면사무소 앞에서 기다렸는디 버스가 한 시간에 한 대라": [
        {"text": "버스가 하도 안 와서", "note": "배차 정보만 지움 — 추천"},
        {"text": "차 시간이 영 안 맞아서", "note": "교통수단 언급은 남음"},
        {"text": "볕도 좋고 다리도 풀 겸", "note": "이유 자체가 바뀜 — 의미 손실 큼"},
    ],
    "한 대 놓치면 두 시간": [
        {"text": "오늘도 걸었다", "note": "배차 간격 지움"},
        {"text": "차 기다리다 말고", "note": "기다림은 남음"},
        {"text": "정류장 볕이 좋았다", "note": "장소 언급은 남음"},
    ],
}
_GENERIC: dict[str, list[dict[str, str]]] = {
    "LOC_ADMIN": [{"text": "우리 동네", "note": "지명 지움"}, {"text": "이 근처", "note": "지명 지움"},
                  {"text": "여기", "note": "가장 짧게"}],
    "LOC_FACILITY": [{"text": "근처", "note": "시설 이름 지움"}, {"text": "동네 어귀", "note": "장소 느낌만"},
                     {"text": "그 앞", "note": "가장 짧게"}],
    # 명사형으로 둔다 — 나이 스팬 뒤에 「인디·인데·이다」 가 붙어 있어서 그대로 이어져야 한다
    "AGE": [{"text": "이 나이", "note": "숫자 지움 — 추천"}, {"text": "이만한 나이", "note": "세대 느낌만"},
            {"text": "나이가 나이", "note": "나이 언급 자체를 흐림"}],
    "COMMUTE": [{"text": "차가 뜸해서", "note": "배차 지움"}, {"text": "차 시간이 안 맞아서", "note": "교통수단 남음"},
                {"text": "걷기 좋은 날이라", "note": "이유가 바뀜"}],
    "INCOME": [{"text": "돈 들어오는 날에", "note": "수입 종류 지움"}, {"text": "형편 봐서", "note": "주기 지움"},
               {"text": "장 볼 때", "note": "소득 언급 자체를 뺌"}],
    "FAM": [{"text": "식구가", "note": "관계 지움"}, {"text": "집에 손님이", "note": "가족 여부 지움"},
            {"text": "누가", "note": "가장 짧게"}],
    "JOB": [{"text": "일 나가는", "note": "직종 지움"}, {"text": "바쁜", "note": "일 언급 최소"},
            {"text": "그냥 지내는", "note": "직업 언급 자체를 뺌"}],
    "SEX": [{"text": "식구", "note": "관계 지움"}, {"text": "집사람·바깥사람 대신 «우리»", "note": ""},
            {"text": "그이", "note": ""}],
    "REL_HOME": [{"text": "가끔 가는", "note": "거리 지움"}, {"text": "근처", "note": ""}, {"text": "", "note": "삭제"}],
    "REL_WORK": [{"text": "일 끝나고", "note": "직장 위치 지움"}, {"text": "저녁에", "note": ""}, {"text": "", "note": "삭제"}],
}


def _bigrams(s: str) -> set[str]:
    s = "".join(s.split())
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def similarity(a: str, b: str) -> float:
    """문자 2-gram Jaccard. 임베딩이 아니다 — 화면에도 그렇게 적는다."""
    A, B = _bigrams(a), _bigrams(b)
    return round(len(A & B) / len(A | B), 2) if A | B else 1.0


def _line_of(text: str, start: int, end: int) -> tuple[int, int]:
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", end)
    return ls, (len(text) if le < 0 else le)


def _is_backbone(text_all: dict[str, str], sp: dict[str, Any]) -> bool:
    """계약 Action.burden 주석의 뼈대 판정 — 같은 표현이 한 글에 2회 이상, 또는 제목과 본문에 함께."""
    t = sp["text"]
    n = sum(v.count(t) for v in text_all.values())
    in_title = "title" in text_all and t in text_all["title"]
    in_body = t in text_all.get("body", "")
    return n >= 2 or (in_title and in_body)


def recommend(view: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """조치 목록. 두 가지 예상값을 함께 낸다 —

    - `projected_delta` (계약): 이 조치 **단독**의 위험 점수 변화.
    - `_k_cum` (화면): 부담 순서대로 **앞 조치까지 적용한 뒤** 이 조치를 더했을 때의 k.
      위치태그가 켜져 있으면 본문 리라이트 단독 효과가 0 으로 보이는데, 태그를 끈 뒤에는 효과가
      살아난다. 사용자는 순서대로 실행하므로 누적값이 실제 체감과 맞는다.
    """
    k0, r0 = base["k"], base["risk"] or 0
    meta_posts = {s["src"]["post_id"] for s in base["steps"]
                  if s.get("src") and s["src"].get("channel") == "geo_tag"}
    # 본문 단서의 효과는 «위치태그를 끈 상태» 를 기준으로 잰다 (②가 항상 먼저 권고되므로)
    after_meta = compute(view, exclude_meta=frozenset(meta_posts))
    used_ids = {s["src"]["span_id"] for s in after_meta["steps"] if s.get("src") and s["src"].get("span_id")}
    used_posts = {s["src"]["post_id"] for s in after_meta["steps"] if s.get("src") and s["src"].get("post_id")}

    def delta(f: dict[str, Any]) -> tuple[int, float]:
        return f["k"], round((f["risk"] or 0) - r0, 1)

    actions: list[dict[str, Any]] = []

    # ② 활동 메타 — 위치태그 (부담 낮음 · 확실 · 선행 PoC 감소폭 1위)
    for pid in sorted(meta_posts):
        f = compute(view, exclude_meta=frozenset({pid}))
        k1, d = delta(f)
        actions.append({"action_type": "activity_meta", "burden": "low", "certainty": "high",
                        "targets": [{"kind": "meta_field", "ref": "geo_tag"}], "projected_delta": min(d, 0.0),
                        "rationale": "글 본문에 지명이 없어도 위치태그 하나가 읍·면을 확정한다. 본문을 안 읽는 채널이라 본문 스캔 도구는 못 본다.",
                        "_k": k1, "_post_id": pid})

    # ① 부분 비공개 — (태그 끈 뒤) k 에 기여한 글 중 빼면 가장 넓어지는 글 하나
    best = None
    for pid in used_posts:
        f = compute(view, exclude_posts=frozenset({pid}), exclude_meta=frozenset(meta_posts))
        if best is None or f["k"] > best[1]["k"]:
            best = (pid, f)
    if best:
        pid, f = best
        k1, d = delta(compute(view, exclude_posts=frozenset({pid})))
        actions.append({"action_type": "unpublish", "burden": "low", "certainty": "highest",
                        "targets": [{"kind": "post", "ref": pid}], "projected_delta": min(d, 0.0),
                        "rationale": "이 글 한 편만 비공개하면 명시 단서 경로가 끊긴다. 삭제가 아니라 되돌릴 수 있다.",
                        "_k": k1, "_post_id": pid})

    # ③ 리라이트 — (태그 끈 뒤) k 단계에 쓰인 본문 스팬 중 효과가 큰 순서로 최대 2건
    rw_cands = []
    for p in view["posts"]:
        for sp in p["spans"]:
            if sp["span_id"] in used_ids and sp["text_id"] != "profile_bio":
                f = compute(view, exclude_spans=frozenset({sp["span_id"]}), exclude_meta=frozenset(meta_posts))
                rw_cands.append((f["k"], p, sp, f))
    rw_cands.sort(key=lambda x: -x[0])
    rewrites: list[dict[str, Any]] = []
    ext_used = False
    for k1, p, sp, f in rw_cands[:2]:
        burden = "high" if _is_backbone(p["texts"], sp) else "medium"
        _, d = delta(compute(view, exclude_spans=frozenset({sp["span_id"]})))
        actions.append({"action_type": "rewrite", "burden": burden, "certainty": "medium",
                        "targets": [{"kind": "post", "ref": p["post_id"]}], "projected_delta": min(d, 0.0),
                        "rationale": f"「{sp['text']}」 만 바꾸면 글을 내리지 않고 경로가 끊긴다. 잔존 단서는 남을 수 있다.",
                        "_k": k1, "_post_id": p["post_id"], "_span_id": sp["span_id"]})
        text = p["texts"][sp["text_id"]]
        ls, le = _line_of(text, sp["start"], sp["end"])
        sentence = text[ls:le]
        cands = external.rewrite_candidates(sentence, sp["text"], "평서형 · 구어체 어미 · 방언 유지")
        if cands:
            ext_used = True
        else:
            cands = _CACHE.get(sp["text"]) or _GENERIC.get(sp["type"]) or [{"text": "", "note": "삭제"}] * 3
        for c in cands:
            new_sentence = sentence[: sp["start"] - ls] + c["text"] + sentence[sp["end"] - ls:]
            rewrites.append({"post_id": p["post_id"], "span_id": sp["span_id"], "suggestion": c["text"][:200],
                             "semantic_similarity": similarity(sentence, new_sentence),
                             "residual_risk": "partial" if f["k"] < 100_000 else "none",
                             "_note": c["note"], "_text_id": sp["text_id"], "_sentence": sentence,
                             "_new_sentence": new_sentence})

    order = {"low": 0, "medium": 1, "high": 2}
    kind_order = {"activity_meta": 0, "unpublish": 1, "rewrite": 2}
    actions.sort(key=lambda a: (order[a["burden"]], kind_order[a["action_type"]], a["projected_delta"]))

    # 누적 k — 부담 순서대로 하나씩 더 적용해 가며 센다
    ex_p, ex_m, ex_s = set(), set(), set()
    for a in actions:
        {"unpublish": ex_p, "activity_meta": ex_m}.get(a["action_type"], set()).add(a["_post_id"])
        if a["action_type"] == "rewrite":
            ex_s.add(a["_span_id"])
        a["_k_cum"] = compute(view, exclude_posts=frozenset(ex_p), exclude_meta=frozenset(ex_m),
                              exclude_spans=frozenset(ex_s))["k"]

    # 전부 적용했을 때
    all_f = compute(view,
                    exclude_posts=frozenset(a["_post_id"] for a in actions if a["action_type"] == "unpublish"),
                    exclude_meta=frozenset(a["_post_id"] for a in actions if a["action_type"] == "activity_meta"),
                    exclude_spans=frozenset(a["_span_id"] for a in actions if a["action_type"] == "rewrite"))
    projected = {"current_risk": float(r0), "projected_risk": float(all_f["risk"] or 0),
                 "reduction_pct": float(max(0, r0 - (all_f["risk"] or 0))), "target_met": (all_f["risk"] or 0) < 45}

    return {"actions": actions, "rewrites": rewrites, "projected": projected, "projected_k": all_f["k"],
            "exceptional": [], "external_llm_used": ext_used}


def stage2_output(view: dict[str, Any], base: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any]:
    """계약 `$defs/Stage2Output` 에 맞는 객체. 화면용 `_` 필드는 뺀다."""
    strip = lambda d: {k: v for k, v in d.items() if not k.startswith("_")}  # noqa: E731
    return {
        "schema_version": "0.1.0",
        "findings": findings(view, base),
        "recommendation": {"actions": [strip(a) for a in rec["actions"]], "projected": rec["projected"],
                           "optimality_gap_pct": None},
        "exceptional": rec["exceptional"],
        "rewrites": [strip(r) for r in rec["rewrites"]],
        "provenance": {
            "measured_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds"),
            "model_version": MODEL_VERSION + ("+" + external.MODEL if rec["external_llm_used"] else ""),
            "dict_version": dict_version(),
            "data_version": "corpus-v0 (synthetic)",
            "label_level": "L1",
            "external_llm_used": rec["external_llm_used"],
        },
    }
