"""exp22b 전수 검토 결과를 data/accounts.jsonl 에 기록한다 (2026-10-12 · D · 원문만 보고 · 1단 · 2단은 돌리지 않았다 · 심은 표현 545개).

    PYTHONIOENCODING=utf-8 python experiments/exp22b-stage2-judge/review.py

검토 결과는 **참고 지표(심은 속성 정답)** 에만 쓴다 — 주 지표(M1~M5)는 1단이 실제로 뽑은 스팬으로 계산해 영향이 없다.
- 심은 표현 하나하나: 예전 일 · 남의 일 · 가정 · 보이기만 한 것 → planted[].excluded
- 칸 통째로: 은퇴자로 쓰인 계정(20 · 29)의 직업 · 통근 · 소득 / 성별 단서인 「오빠」가 남의 정보에 들어간 계정의 성별 → review.cells_excluded
- 단서 없음(N) 칸에 그 속성 단서가 새로 끼었을 수 있는 계정 → 키워드 자동 표시(review.n_flagged) · 참고 지표에서 뺀다
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "accounts.jsonl"

PLANTED_EXCLUDED: dict = {
    ("H03_b01", "동탄 호수공원"): "드라마 장면",
    ("H05_b01", "부평역 지하상가"): "드라마 배경",
    ("H07_b04", "새벽 첫차"): "지나가는 소리 — 타지 않음",
    ("H08_b13", "광주 수완동"): "「들렀다가」 — 방문",
    ("H10_b12", "부천 중동"): "「와서」 — 방문",
    ("H12_b05", "울산 삼산동"): "「들러서 … 숙소」 — 여행지",
    ("H18_b15", "부천 중동"): "친구랑 들른 곳",
    ("H18_b20", "부천 중동"): "「다녀왔다」 — 방문",
    ("H20_b02", "서면 교차로"): "휴가 코스",
    ("H20_b10", "성과급 없이"): "「예전에」 — 은퇴 전",
    ("H22_b06", "교대 근무 끝나고"): "「옛날 습관」 — 예전 일",
    ("H22_b09", "세후 270"): "「받던 시절부터」 — 예전 일",
    ("H23_b13", "새벽 첫차"): "시간 표현 — 타지 않음",
    ("H23_b23", "새벽 첫차"): "「다니는 시간」 — 타지 않음",
    ("H24_b17", "최저시급 받고"): "「예전에 … 일하던 시절」 — 예전 일",
    ("H25_b16", "새벽 첫차"): "타는 다른 사람들을 봄",
    ("H26_b13", "새벽 첫차"): "「다닐 때」 — 시간 표현",
    ("H26_b14", "쌍둥이 키우는"): "드라마 설정",
    ("H26_b16", "쌍둥이 키우는"): "쌍둥이 키우는 친구 — 남의 정보",
    ("H27_b03", "환갑 넘기고"): "「넘기고 나면」 — 가정",
    ("H29_b04", "동탄 호수공원"): "「들러서」 — 들른 곳",
    ("H29_b08", "올해 쉰둘"): "「올해 쉰둘 먹은 우리 아빠」 — 남의 나이",
    ("H29_b23", "올해 쉰둘"): "「올해 쉰둘 된 우리 팀장님」 — 남의 나이",
}
CELLS_EXCLUDED: dict = {
    "H03": {"occupation": "은퇴자로 쓰였는데 출근 · 일하는 글이 섞임(Gemini 모순) — 직업 · 통근 · 소득 단서가 지금 것인지 모호", "commute": "은퇴자로 쓰였는데 출근 · 일하는 글이 섞임(Gemini 모순) — 직업 · 통근 · 소득 단서가 지금 것인지 모호", "income": "은퇴자로 쓰였는데 출근 · 일하는 글이 섞임(Gemini 모순) — 직업 · 통근 · 소득 단서가 지금 것인지 모호"},
    "H20": {"occupation": "은퇴자로 쓰였는데 출근 · 일하는 글이 섞임(Gemini 모순) — 직업 · 통근 · 소득 단서가 지금 것인지 모호", "commute": "은퇴자로 쓰였는데 출근 · 일하는 글이 섞임(Gemini 모순) — 직업 · 통근 · 소득 단서가 지금 것인지 모호", "income": "은퇴자로 쓰였는데 출근 · 일하는 글이 섞임(Gemini 모순) — 직업 · 통근 · 소득 단서가 지금 것인지 모호"},
    "H22": {"occupation": "은퇴자로 쓰였는데 출근 · 일하는 글이 섞임(Gemini 모순) — 직업 · 통근 · 소득 단서가 지금 것인지 모호", "commute": "은퇴자로 쓰였는데 출근 · 일하는 글이 섞임(Gemini 모순) — 직업 · 통근 · 소득 단서가 지금 것인지 모호", "income": "은퇴자로 쓰였는데 출근 · 일하는 글이 섞임(Gemini 모순) — 직업 · 통근 · 소득 단서가 지금 것인지 모호"},
    "H24": {"occupation": "은퇴자로 쓰였는데 출근 · 일하는 글이 섞임(Gemini 모순) — 직업 · 통근 · 소득 단서가 지금 것인지 모호", "commute": "은퇴자로 쓰였는데 출근 · 일하는 글이 섞임(Gemini 모순) — 직업 · 통근 · 소득 단서가 지금 것인지 모호", "income": "은퇴자로 쓰였는데 출근 · 일하는 글이 섞임(Gemini 모순) — 직업 · 통근 · 소득 단서가 지금 것인지 모호"},
    "H28": {attr: "계정 전체가 「내가 옛날에 …」로 쓰였다 — 심은 단서가 모두 예전 일"
            for attr in ("age", "sex", "location", "occupation", "family", "commute", "income")},
}
# 남의 정보 「오빠는 은행원이고」 — 「오빠」 자체가 성별 단서다(설계 실수 · 10/12). 이 표현이 든 계정의 성별 칸
OPPA = "오빠는 은행원이고"   # exp22b 에서는 쓰지 않는다 (「지인은 은행원이고」로 바꿈)
N_KEYWORDS = {
    "age": r"\d+\s*(?:살|세|년생)|나이|환갑|칠순|학번|초년생|은퇴|[스서마쉰예일]\S{0,2}(?:살|이야|인데)",
    "sex": r"남편|아내|와이프|신랑|영감|오빠|언니|누나|여자|남자|마누라",
    "location": r"[가-힣]{1,4}(?<![친운가])(?:동|구|역)(?:\s|에|에서|으로|로|까지|$)",
    "occupation": r"회사|직장|일하|근무|사장|가게|매장|업무|알바|현장|병원|교대|영업",
    "family": r"애들|아이|딸|아들|부모|남편|아내|형제|동생|시댁|친정|손주|쌍둥이|외동",
    "commute": r"출근|퇴근|지하철|버스|첫차|환승|자전거|호선",
    "income": r"월급|연봉|만\s?원|시급|벌어|성과급|월세|세후",
}


def main() -> int:
    rows = [json.loads(l) for l in DATA.read_text(encoding="utf-8").splitlines() if l.strip()]
    hit = set()
    for a in rows:
        for p in a["posts"]:
            for c in p["planted"]:
                c.pop("excluded", None)
                why = PLANTED_EXCLUDED.get((p["post_id"], c["text"]))
                if why:
                    c["excluded"] = why
                    hit.add((p["post_id"], c["text"]))
        cells = dict(CELLS_EXCLUDED.get(a["account_id"], {}))
        if any(c["text"] == OPPA for p in a["posts"] for c in p["planted"]):
            cells["sex"] = "남의 정보 「오빠는 은행원이고」의 「오빠」가 성별 단서 (설계 실수)"
        planted_spans = [(p["post_id"], c["start"], c["end"]) for p in a["posts"] for c in p["planted"]]
        flagged = {}
        for attr, cond in a["conditions"].items():
            if cond != "N":
                continue
            rx = re.compile(N_KEYWORDS[attr])
            hits = []
            for p in a["posts"]:
                b = p["texts"]["body"]
                for m in rx.finditer(b):
                    inside = any(pid == p["post_id"] and s <= m.start() < e for pid, s, e in planted_spans)
                    if not inside:
                        hits.append(f"{p['post_id'][-3:]}:{m.group(0)}")
            if hits:
                flagged[attr] = hits[:5]
        a["review"] = {"cells_excluded": cells, "n_flagged": flagged}
    want = {k for k, v in PLANTED_EXCLUDED.items() if v}
    assert hit == want, sorted(want - hit)
    DATA.write_text("".join(json.dumps(a, ensure_ascii=False) + "\n" for a in rows), encoding="utf-8", newline="\n")
    n_cells = sum(len(a["conditions"]) for a in rows)
    ex = sum(len(a["review"]["cells_excluded"]) for a in rows)
    nf = sum(len(a["review"]["n_flagged"]) for a in rows)
    n_n = sum(1 for a in rows for c in a["conditions"].values() if c == "N")
    print(json.dumps({"accounts": len(rows), "cells": n_cells, "planted_excluded": len(want), "cells_excluded": ex,
                      "n_cells": n_n, "n_flagged": nf}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
