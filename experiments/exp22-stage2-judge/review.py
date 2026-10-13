"""exp22 전수 검토 결과를 data/accounts.jsonl 에 기록한다 (2026-10-12 · D · 원문만 보고 · 1단 · 2단은 돌리지 않았다).

    PYTHONIOENCODING=utf-8 python experiments/exp22-stage2-judge/review.py

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

PLANTED_EXCLUDED = {
    ("G22_02_p15", "광주 수완동"): "동창 만나러 간 곳 — 사는 곳 아님",
    ("G22_03_p14", "새벽 첫차"): "고향 내려가는 다른 사람들",
    ("G22_04_p06", "새벽 첫차"): "다닐 시간이 지났다 — 타지 않음",
    ("G22_04_p16", "새벽 첫차"): "지나가는 버스가 보였다 — 타지 않음",
    ("G22_04_p17", "새벽 첫차"): "안내문을 봤다 — 타지 않음",
    ("G22_07_p06", "부평역 지하상가"): "「예전에 자주 가던」 — 예전 일",
    ("G22_09_p05", "새벽 첫차"): "다니는 시간이 됐다 — 타지 않음",
    ("G22_17_p10", "새벽 첫차"): "시간 표현 — 타지 않음",
    ("G22_20_p04", "연봉 4천"): "「예전 연봉 4천」 — 은퇴 전",
    ("G22_20_p14", "주유소 점장"): "「신세였는데」 — 예전 일",
    ("G22_20_p20", "1호선 타고 출근"): "「옛날에」 — 예전 일",
    ("G22_21_p18", "최저시급 받고"): "「알바 시절에도」 — 예전 일",
    ("G22_21_p22", "환갑 넘기고"): "「넘기고 나면」 — 가정",
    ("G22_23_p20", "성과급 없이"): "드라마 주인공 이야기",
    ("G22_25_p16", "제약회사 영업"): "「다닐 때 쓰던」 — 예전 일",
    ("G22_26_p12", "제약회사 영업"): "「한때」 — 예전 일",
    ("G22_26_p20", "제약회사 영업"): "「예전에」 — 예전 일",
    ("G22_28_p07", "최저시급 받고"): "「일하던 시절」 — 예전 일",
    ("G22_29_p08", "제약회사 영업"): "「뛰던 시절」 — 예전 일",
    ("G22_29_p10", "제약회사 영업"): "「할 때」 — 은퇴 전",
    ("G22_29_p22", "제약회사 영업"): "「할 때」 — 은퇴 전",
    ("G22_29_p12", "자전거로 출퇴근"): "「하던 시절」 — 예전 일",
    ("G22_29_p16", "자전거로 출퇴근"): "「하던 그때」 — 예전 일",
    ("G22_29_p21", "자전거로 출퇴근"): "「하던 체력으로」 — 예전 일",
    ("G22_30_p01", "서면 교차로"): None,   # 확인 결과 지금 일 — 제외하지 않음 (목록에서 뺄 때 이유를 남기려고 둔다)
}
CELLS_EXCLUDED = {
    "G22_20": {"occupation": "은퇴자로 쓰였다(「은퇴한 지 3년째」) — 직업 · 통근 · 소득 단서가 지금 것인지 섞임",
               "commute": "은퇴자 — 위와 같음", "income": "은퇴자 — 위와 같음"},
    "G22_29": {"occupation": "은퇴자로 쓰였다 — 직업 단서가 모두 예전 일", "commute": "은퇴자 — 통근 단서가 모두 예전 일",
               "income": "은퇴자 — 위와 같음"},
}
# 남의 정보 「오빠는 은행원이고」 — 「오빠」 자체가 성별 단서다(설계 실수 · 10/12). 이 표현이 든 계정의 성별 칸
OPPA = "오빠는 은행원이고"
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
