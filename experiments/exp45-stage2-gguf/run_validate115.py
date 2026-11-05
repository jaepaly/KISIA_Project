"""종단 전수 — 떠 있는 분석기(빠른 결과 먼저)에 Veilo DB 의 계정 전체(115명)를 점검하고 판정 칸을 모은다.

    python experiments/exp45-stage2-gguf/run_validate115.py --base http://127.0.0.1:8100 \\
        --sns-db <Veilo 3100 DB> --label gguf --out <저장소 밖>/validate115_gguf.jsonl

- run_e2e.py 와 같은 하네스(POST /scan/{user_ref}?progressive=true → /api/stage2-followup 0.25초 폴링). 시간은 덤이고
  핵심은 칸 — 빠른 결과(규칙 판정 · 위험도 · 추천)와 정밀 판정(모델 판정 · 근거 · 신뢰도 · 범위)을 계정마다 한 줄로 남긴다
- 계정 목록은 Veilo DB authors 표(author_id 순). 읽기 전용으로 연다
- 한 줄씩 바로 써서 중간에 끊겨도 이어 돌린다(이미 있는 user_ref 는 건너뜀). 첫 계정을 한 번 먼저 점검해 버린다(워밍업)
- 출력에는 원문이 없다 — 판정 · 스팬 번호 · 숫자 · 추천의 해시만. 그래도 저장소 밖에 쓴다
분석기 · Veilo 는 따로 띄운다(README). 이 스크립트는 127.0.0.1 로만 요청한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import urllib.request
from pathlib import Path

_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _call(url: str, data: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    with _HTTP.open(req, timeout=900) as r:
        return json.loads(r.read())


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _cells(findings: dict) -> dict:
    return {a: {"verdict": f.get("verdict"), "granularity": f.get("granularity"), "confidence": f.get("confidence"),
                "cross_post": f.get("cross_post"),
                "evidence": sorted(e.get("span_id") or e.get("post_id") for e in f.get("evidence") or [])}
            for a, f in findings.items()}


def accounts(db: Path) -> list[str]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute("SELECT user_ref FROM authors ORDER BY author_id")]
    finally:
        con.close()


def scan(base: str, uref: str) -> dict:
    t0 = time.perf_counter()
    out = _call(f"{base}/scan/{uref}?progressive=true", data=b"")
    fast = time.perf_counter() - t0
    fol = out.get("stage2_followup") or {}
    s2 = out["stage2"]["output"]
    rec = s2["recommendation"]
    row = {"user_ref": uref, "fast_s": round(fast, 2), "followup_submit": fol.get("status"),
           "n_posts": len(out.get("posts") or out.get("diagnosis", {}).get("posts") or []),
           "fast_version": s2["provenance"]["model_version"], "fast": _cells(s2["findings"]),
           "risk": rec["projected"]["current_risk"], "projected_risk": rec["projected"].get("projected_risk"),
           "n_actions": len(rec.get("actions") or []), "rec_sha": _sha(rec)}
    if "job" not in fol:
        row.update(precise_s=None, status=fol.get("status"))
        return row
    while True:
        q = _call(f"{base}/api/stage2-followup?job={fol['job']}")
        if q["status"] not in ("pending", "running"):
            break
        time.sleep(0.25)
    row.update(precise_s=round(time.perf_counter() - t0, 2), status=q["status"], model_version=q.get("model_version"),
               reason=q.get("reason"))
    if q.get("findings"):
        row["model"] = _cells(q["findings"])
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8100")
    ap.add_argument("--sns-db", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--label", required=True)
    a = ap.parse_args()
    users = accounts(a.sns_db)
    done = set()
    if a.out.exists():
        done = {json.loads(l)["user_ref"] for l in a.out.read_text(encoding="utf-8").splitlines() if l.strip()}
    mode = _call(f"{a.base}/api/engine-mode")
    print("accounts", len(users), "already", len(done), "mode", mode, flush=True)
    warm = scan(a.base, users[0])
    print("warmup", warm["fast_s"], warm["precise_s"], warm["status"], warm.get("model_version"), flush=True)
    with a.out.open("a", encoding="utf-8") as fh:
        for i, u in enumerate(users, 1):
            if u in done:
                continue
            r = scan(a.base, u)
            r.update(label=a.label, i=i, measured=time.strftime("%Y-%m-%d %H:%M:%S"))
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            print(i, u, r["fast_s"], r["precise_s"], r["status"], r.get("model_version"), flush=True)
    print("ALL DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
