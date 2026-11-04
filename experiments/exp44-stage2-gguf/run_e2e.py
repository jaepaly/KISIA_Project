"""종단 실측 — 떠 있는 분석기(빠른 결과 먼저 · progressive)에 freeze-W11 의 11계정을 점검하고 두 시각을 잰다.

    python experiments/exp44-stage2-gguf/run_e2e.py --base http://127.0.0.1:8100 --out <결과.json> --label gguf

- 빠른 결과 도착: POST /scan/{user_ref}?progressive=true 응답까지(1단 + 규칙 2단 · 위험도 · 추천)
- 정밀 판정 도착: 같은 POST 시작부터 /api/stage2-followup 이 done|fallback|failed 를 돌려줄 때까지(0.25초 간격 폴링)
- 계정을 하나씩 — 앞 계정의 정밀 판정이 끝난 뒤 다음 계정을 보낸다(1단 CPU 와 2단 GPU 가 겹치지 않게)
- 첫 계정을 한 번 먼저 점검해 버린다(워밍업 · 기록 안 함)
분석기 · Veilo 는 따로 띄운다(README). 이 스크립트는 127.0.0.1 로만 요청한다.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path

# freeze-W11 (docs/evidence/freeze-W11.md) 표의 11계정 — 메인 · 예비 먼저
ACCOUNTS = ["u_8c53e7b89615", "u_00ceeab4df70", "u_40ef42660c42", "u_5985f6f8353e", "u_231b2f8e3757",
            "u_72ce87717c0c", "u_bf3d2191e215", "u_084835c6a489", "u_0dfab5acbae0", "u_99e3940e063f",
            "u_c9c1dd0d52c9"]
_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _call(url: str, data: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    with _HTTP.open(req, timeout=900) as r:
        return json.loads(r.read())


def scan(base: str, uref: str) -> dict:
    t0 = time.perf_counter()
    out = _call(f"{base}/scan/{uref}?progressive=true", data=b"")
    fast = time.perf_counter() - t0
    fol = out.get("stage2_followup") or {}
    rec = {"user_ref": uref, "fast_s": round(fast, 2), "followup_submit": fol.get("status"),
           "n_posts": len(out.get("posts") or out.get("diagnosis", {}).get("posts") or []),
           "fast_verdicts": {a: f["verdict"] for a, f in out["stage2"]["output"]["findings"].items()},
           "fast_version": out["stage2"]["output"]["provenance"]["model_version"],
           "risk": out["stage2"]["output"]["recommendation"]["projected"]["current_risk"]}
    if "job" not in fol:
        rec.update(precise_s=None, status=fol.get("status"))
        return rec
    while True:
        q = _call(f"{base}/api/stage2-followup?job={fol['job']}")
        if q["status"] not in ("pending", "running"):
            break
        time.sleep(0.25)
    rec.update(precise_s=round(time.perf_counter() - t0, 2), status=q["status"], model_version=q.get("model_version"),
               reason=q.get("reason"))
    if q.get("findings"):
        rec["model_verdicts"] = {a: f["verdict"] for a, f in q["findings"].items()}
        rec["model_evidence"] = {a: f["evidence"] for a, f in q["findings"].items()}
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8100")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--label", required=True)
    a = ap.parse_args()
    mode = _call(f"{a.base}/api/engine-mode")
    warm = scan(a.base, ACCOUNTS[0])
    print("warmup", warm["fast_s"], warm["precise_s"], warm["status"], flush=True)
    rows = []
    for u in ACCOUNTS:
        r = scan(a.base, u)
        rows.append(r)
        print(u, r["fast_s"], r["precise_s"], r["status"], r.get("model_version"), flush=True)
    done = [r for r in rows if r["status"] == "done"]
    summary = {"label": a.label, "engine_mode": mode, "measured": time.strftime("%Y-%m-%d %H:%M"),
               "fast_median_s": round(statistics.median(r["fast_s"] for r in rows), 2),
               "precise_median_s": round(statistics.median(r["precise_s"] for r in done), 2) if done else None,
               "model_only_median_s": round(statistics.median(r["precise_s"] - r["fast_s"] for r in done), 2) if done else None,
               "done": len(done), "accounts": len(rows), "warmup": warm, "rows": rows}
    a.out.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("fast median", summary["fast_median_s"], "precise median", summary["precise_median_s"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
