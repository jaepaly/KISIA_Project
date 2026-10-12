"""exp22b 전수 검토 결과를 data/accounts.jsonl 에 기록한다 (2026-10-12 · D · 원문만 보고 · 1단 · 2단은 돌리지 않았다).

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
    # (post_id, 표현): 이유 — 검토 뒤 채운다
}
CELLS_EXCLUDED: dict = {
    # account_id: {attr: 이유} — 검토 뒤 채운다
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
