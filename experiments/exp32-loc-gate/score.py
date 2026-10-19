"""exp32 채점 (README §4 — 결과 전 고정). 지표 정의는 exp31 score.py 와 같고, V 는 유형 일치(V_typed)가 판정 지표다.

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp32-loc-gate/score.py

입력: results/a0_{set}.jsonl(1단) · results/{S2-seed}_{set}.jsonl(학생 판정) · results/teacher_{set}.jsonl(참고 · 있으면).
구성: H-{seed} = 학생 판정을 LOC 후보에만 · S2-{seed} = 전체 후보에 (exp31 과 같은 적용) · T3 = 교사 판정 전체 · TH = 교사 판정을 LOC 에만.
출력: results/metrics.json · 표준 출력.
"""
from __future__ import annotations

import importlib.util
import json
import statistics
import sys

import common

RES = common.HERE / "results"
_spec = importlib.util.spec_from_file_location("score31", common.EXP31 / "score.py")
s31 = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("common", common)   # exp31 score 의 `import common` 은 쓰지 않는 함수만 부른다
_spec.loader.exec_module(s31)
load, score_g = s31.load, s31.score_g


def d1e_posts() -> list[dict]:
    rows = [json.loads(l) for l in open(common.HERE / "data" / "posts.jsonl", encoding="utf-8")]
    return [r for r in rows if not r.get("excluded")]


def build(a0: dict, dec: dict, how: str) -> dict:
    out = {}
    for pid, r in a0.items():
        d = dec.get(pid, {}).get("decisions") if r["spans"] else []
        # Codex 검토(결과 뒤 추가): 판정이 빠지거나 길이가 다르면 zip 이 뒤쪽 스팬을 조용히 지우므로 멈춘다 — 저장된 판정은 모두 통과(수치 그대로)
        assert d is not None and len(d) == len(r["spans"]) and set(d) <= set(common.LABELS), pid
        sp = common.gate(r["spans"], d) if how == "loc" else common.apply(r["spans"], d)
        out[pid] = {"post_id": pid, "spans": sp, "sec": dec.get(pid, {}).get("sec")}
    return out


def main() -> int:
    posts, gold = d1e_posts(), common.gold_d2()
    a0 = {n: load(RES / f"a0_{n}.jsonl") for n in ("d1e", "d2")}
    srcs = {}
    for seed in ("20261019", "20261023"):
        dec = {n: load(RES / f"S2-{seed}_{n}.jsonl") for n in ("d1e", "d2")}
        srcs[f"H-{seed}"] = (dec, "loc")
        srcs[f"S2-{seed}"] = (dec, "all")
    if all((RES / f"teacher_{n}.jsonl").exists() for n in ("d1e", "d2")):
        dec = {n: load(RES / f"teacher_{n}.jsonl") for n in ("d1e", "d2")}
        srcs["T3"] = (dec, "all")
        srcs["TH"] = (dec, "loc")
    out = {"d1e_posts": len(posts), "d2_posts": len(gold), "configs": {}}
    out["configs"]["a0"] = s31.score_d1d(posts, a0["d1e"], a0["d1e"]) | {"L_median": round(statistics.median(r["sec"] for r in a0["d1e"].values()), 3)}
    for tag, (dec, how) in srcs.items():
        p1, p2 = build(a0["d1e"], dec["d1e"], how), build(a0["d2"], dec["d2"], how)
        m = s31.score_d1d(posts, p1, a0["d1e"]) | score_g(gold, a0["d2"], p2)
        secs = [r["sec"] for r in p1.values() if r["sec"] is not None]
        if secs and not tag.startswith("T"):
            m["L_median"] = round(statistics.median(secs), 3)
        out["configs"][tag] = m
    a = out["configs"]["a0"]
    vt = lambda m: int(m["V_typed"].split("/")[0])
    for tag, m in out["configs"].items():
        if tag == "a0":
            continue
        m["checks"] = {"Ta": m["Ta_n"] <= a["Ta_n"] / 2, "V_typed": vt(m) <= 3, "R": m["R_n"] >= a["R_n"] - 2,
                       "G_drop": m["G_drop_rate"] <= 0.03, "G_flip": m["G_flip_rate"] <= 0.05,
                       "L": m["L_median"] <= 1.0 if "L_median" in m else None}
        m["pass"] = None if None in m["checks"].values() else all(m["checks"].values())
    h = [out["configs"][t]["pass"] for t in ("H-20261019", "H-20261023")]
    out["H_candidate"] = all(x is True for x in h)   # README §4: H 의 두 seed 가 모두 통과
    (RES / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
