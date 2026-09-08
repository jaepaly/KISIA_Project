"""시딩 인물별 k 회귀 — 본 프로젝트 자원(src/kopl · 코퍼스 · 모델)을 갈아끼운 뒤 숫자가 어디서 바뀌는지 본다.

    PYTHONPATH=src python apps/demo/probe.py            # 4명 · 위치태그 ON/OFF · 깔때기 경로
    PYTHONPATH=src python apps/demo/probe.py D05 D06    # 인물 지정
    PYTHONPATH=src python apps/demo/probe.py --save     # apps/demo/probe.baseline.json 갱신
    PYTHONPATH=src python apps/demo/probe.py --diff     # baseline 과 비교 — 바뀐 인물만 출력, 바뀌면 exit 1

서버 불필요. README 「실측 수치」 표와 LOG 의 숫자는 이 스크립트 출력이 정본이다.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from engine.pipeline import analyze, compute  # noqa: E402

BASELINE = HERE / "probe.baseline.json"
DEFAULT = ["D05", "D01", "D11", "D06"]


def export_for(pid: str, geo: bool) -> dict:
    persona = json.loads((ROOT / f"data/corpus/v0/personas/{pid}.json").read_text(encoding="utf-8"))
    posts = [json.loads(l) for l in (ROOT / f"data/corpus/v0/posts/{pid}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    posts.sort(key=lambda p: p["post_id"])
    uref = "u_" + hashlib.sha1(pid.encode()).hexdigest()[:8]
    parts = ((persona.get("ground_truth") or {}).get("location") or "").split()
    tag = " ".join(parts[-2:]) if len(parts) >= 2 else None
    out, tagged = [], False
    for p in posts:
        t, g = p["texts"], None
        if geo and tag and not tagged and p["kind"] == "ambient":
            g, tagged = tag, True
        caps = [{"caption": t[k]} for k in sorted(k for k in t if k.startswith("photo_caption"))]
        out.append({"post_id": p["post_id"], "user_ref": uref, "title": t.get("title"), "body": t["body"],
                    "photos": caps, "activity_meta": {"nickname": pid, "geo_tag": g, "post_time": p["created_at"][11:16]}})
    return {"schema_version": "1.0", "user_ref": uref, "nickname": pid,
            "profile_bio": (persona.get("account") or {}).get("profile_intro"), "posts": out}


def probe(pid: str) -> dict:
    res = {}
    for geo in (True, False):
        f = compute(analyze(export_for(pid, geo)))
        res["on" if geo else "off"] = {"k": f["k"],
                                       "path": [f"{s['axis']}:{s.get('kind') or s['method']}={s['n_after']}" for s in f["steps"]]}
    return res


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    pids = args or DEFAULT
    cur = {pid: probe(pid) for pid in pids}
    if "--save" in flags:
        BASELINE.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"saved {BASELINE.name}: " + " · ".join(f"{p} {v['on']['k']:,}/{v['off']['k']:,}" for p, v in cur.items()))
        return 0
    if "--diff" in flags:
        base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
        changed = 0
        for pid, v in cur.items():
            b = base.get(pid)
            for mode in ("on", "off"):
                if not b or b[mode]["k"] != v[mode]["k"]:
                    changed += 1
                    print(f"{pid} [{mode}] {b[mode]['k'] if b else '—'} → {v[mode]['k']:,}")
                    print("   " + " → ".join(v[mode]["path"]))
        print("변화 없음" if not changed else f"{changed}건 바뀜")
        return 1 if changed else 0
    for pid, v in cur.items():
        print(f"{pid}  ON {v['on']['k']:>10,}   OFF {v['off']['k']:>10,}")
        print("   ON  " + " → ".join(v["on"]["path"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
