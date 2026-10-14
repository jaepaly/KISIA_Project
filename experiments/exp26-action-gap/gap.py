"""exp26 §2~4 — 추천 vs 최적해 격차 · 조치 곡선 (골드 스팬 · 앱 위험 경로). 정의는 README (결과 전 커밋 0b70fc0).

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp26-action-gap/gap.py

입력: data/corpus/v0/gold/<인물>_spans.jsonl (검수 + 교사 라벨) · experiments/exp10-action-repro/data/inputs_full.jsonl (위치태그)
출력: results/gap.json
"""
from __future__ import annotations

import hashlib
import itertools
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kopl.c2_specificity.engine import risk_by_axis  # noqa: E402
from kopl.c2_specificity.model import AXES, RESOLUTION  # noqa: E402
from kopl.c4_stage2 import infer as s2  # noqa: E402
from kopl.c4_stage2.recommend import recommend, unpublish_k  # noqa: E402

GOLD = ROOT / "data" / "corpus" / "v0" / "gold"
INPUTS = ROOT / "experiments" / "exp10-action-repro" / "data" / "inputs_full.jsonl"
TEST_IDS = ROOT / "data" / "corpus" / "v0" / "splits" / "test_post_ids.json"
TARGET = 40.0
WEIGHTS = {"main": (1, 2, 3), "count": (1, 1, 1), "steep": (1, 2, 4)}  # (비공개/편, 위치태그, 리라이트/편)
GAP_MAX, FAIL_MAX = 0.15, 0.10
EPS = 1e-9


# ── 입력 ────────────────────────────────────────────────────────────────

def test_post_ids() -> set[str]:
    ids = set(json.loads(TEST_IDS.read_text(encoding="utf-8"))["post_ids"])  # 메타 dict — 목록은 post_ids
    if len(ids) != 255:
        raise SystemExit(f"test 글 수가 255 가 아니다: {len(ids)}")
    return ids


def load_accounts() -> list[dict[str, Any]]:
    """[{persona_id, user_ref, posts: [{post_id, spans, geo_tag, texts}]}] — test 글 · level/subject 없는 스팬 제외."""
    test = test_post_ids()
    out = []
    for line in open(INPUTS, encoding="utf-8"):
        row = json.loads(line)
        geo = {p["post_id"]: p.get("geo_tag") for p in row["posts"]}
        posts = {}
        for g in open(GOLD / f"{row['persona_id']}_spans.jsonl", encoding="utf-8"):
            rec = json.loads(g)
            pid = rec.get("post_id")
            if pid in geo and pid not in test:
                posts[pid] = {"post_id": pid, "geo_tag": geo[pid], "texts": rec.get("texts") or {},
                              "spans": [s for s in rec.get("spans") or [] if "level" in s and "subject" in s]}
        if posts:
            out.append({"persona_id": row["persona_id"], "user_ref": row["user_ref"],
                        "posts": [posts[k] for k in sorted(posts)]})
    return out


# ── 글별 상태 · 계정 위험 ───────────────────────────────────────────────

ZERO = {a: 0.0 for a in AXES}


def post_state(post: Mapping[str, Any]) -> dict[str, Any]:
    """원래 · 명시 지운 뒤의 7축 점수, 위치태그 점수 (README §3 「글별 상태」)."""
    pid = post["post_id"]
    spans = list(post.get("spans") or [])
    rewritten = [s for s in spans if s.get("level") != "explicit"]
    geo_cond = s2._app_geo_condition(post["geo_tag"], pid) if post.get("geo_tag") else None
    return {"post_id": pid,
            "orig": risk_by_axis(s2._app_conditions(spans, pid)),
            "rew": risk_by_axis(s2._app_conditions(rewritten, pid)),
            "explicit": len(rewritten) < len(spans),
            "geo": risk_by_axis([geo_cond]) if geo_cond else None}


def account_risk(states: Sequence[Mapping[str, Any]], hidden=frozenset(), rewrite=frozenset(), tags_off=False) -> float:
    top = dict(ZERO)
    for st in states:
        if st["post_id"] in hidden:
            continue
        vec = st["rew"] if st["post_id"] in rewrite else st["orig"]
        for a in AXES:
            top[a] = max(top[a], vec[a])
        if st["geo"] is not None and not tags_off:
            for a in AXES:
                top[a] = max(top[a], st["geo"][a])
    return sum(top.values()) / len(AXES)


def burden(w: tuple[int, int, int], n_hidden: int, tags_off: bool, n_rewrite: int) -> int:
    return w[0] * n_hidden + (w[1] if tags_off else 0) + w[2] * n_rewrite


# ── 최적해 ─────────────────────────────────────────────────────────────

def _fits(vec: Mapping[str, float], cap: Mapping[str, float]) -> bool:
    return all(vec[a] <= cap[a] + EPS for a in AXES)


def optimum(states: Sequence[Mapping[str, Any]], k: int, w: tuple[int, int, int], target: float = TARGET):
    """축별 상한 열거 — (부담, 위험, hidden, rewrite, tags_off) 최소. 닿지 못하면 None."""
    has_tags = any(st["geo"] is not None for st in states)
    best = None
    levels = [sorted(set(RESOLUTION[a].values())) for a in AXES]
    for combo in itertools.product(*levels):
        if sum(combo) / len(AXES) > target + EPS:
            continue
        cap = dict(zip(AXES, combo))
        for tags_off in ((False, True) if has_tags else (False,)):
            must, either = [], []
            for st in states:
                tag_ok = tags_off or st["geo"] is None or _fits(st["geo"], cap)
                if tag_ok and _fits(st["orig"], cap):
                    continue
                if tag_ok and st["explicit"] and _fits(st["rew"], cap):
                    either.append(st["post_id"])
                else:
                    must.append(st["post_id"])
            if len(must) > k:
                continue
            slots = k - len(must)
            if w[0] < w[2]:
                hide_more = either[:slots]
            elif w[0] == w[2]:
                hide_more = []  # 같은 부담 — 아래에서 두 경우 다 보고 위험 낮은 쪽
            else:
                hide_more = []
            options = [hide_more] if w[0] != w[2] else [[], either[:slots]]
            for extra in options:
                hidden = frozenset(must) | frozenset(extra)
                rewrite = frozenset(p for p in either if p not in hidden)
                b = burden(w, len(hidden), tags_off, len(rewrite))
                r = account_risk(states, hidden, rewrite, tags_off)
                if r > target + EPS:
                    continue
                cand = (b, r, hidden, rewrite, tags_off)
                if best is None or (b, r) < (best[0], best[1]):
                    best = cand
    return best


def brute_force(states: Sequence[Mapping[str, Any]], k: int, w: tuple[int, int, int], target: float = TARGET):
    """대조용 단순 전수 탐색 (글 ≤ 8편)."""
    ids = [st["post_id"] for st in states]
    exp = {st["post_id"] for st in states if st["explicit"]}
    has_tags = any(st["geo"] is not None for st in states)
    best = None
    for r in range(k + 1):
        for hidden in itertools.combinations(ids, r):
            hidden = frozenset(hidden)
            pub_exp = sorted(exp - hidden)
            for tags_off in ((False, True) if has_tags else (False,)):
                for m in range(len(pub_exp) + 1):
                    for rewrite in itertools.combinations(pub_exp, m):
                        rewrite = frozenset(rewrite)
                        risk = account_risk(states, hidden, rewrite, tags_off)
                        if risk > target + EPS:
                            continue
                        b = burden(w, len(hidden), tags_off, len(rewrite))
                        if best is None or (b, risk) < (best[0], best[1]):
                            best = (b, risk, hidden, rewrite, tags_off)
    return best


# ── 추천 엔진 (앱과 같게 부른다) ────────────────────────────────────────

def run_recommend(acc: Mapping[str, Any], target: float = TARGET) -> dict[str, Any]:
    return recommend(user_ref=acc["user_ref"],
                     posts=[{"post_id": p["post_id"], "spans": p["spans"], "geo_tag": p["geo_tag"]} for p in acc["posts"]],
                     target_risk=target, conditions_fn=s2._app_conditions, geo_condition_fn=s2._app_geo_condition)


def rec_plan(rec: Mapping[str, Any]) -> tuple[int, bool, int]:
    hid = tags = rew = 0
    for a in rec["actions"]:
        if a["action_type"] == "unpublish":
            hid += len(a["targets"])
        elif a["action_type"] == "activity_meta":
            tags = True
        elif a["action_type"] == "rewrite":
            rew += len(a["targets"])
    return hid, bool(tags), rew


# ── 곡선 ───────────────────────────────────────────────────────────────

def curves(acc: Mapping[str, Any], states: Sequence[Mapping[str, Any]], k: int) -> dict[str, Any]:
    from kopl.c3_contribution import leave_one_out

    ids = [st["post_id"] for st in states]
    base = account_risk(states)
    loo = leave_one_out(user_ref=acc["user_ref"], post_ids=ids,
                        risk_fn=lambda sel: account_risk(states, frozenset(ids) - frozenset(sel)),
                        max_greedy_remove=k)
    order = [s["remove"] for s in loo["output"]["greedy_path"]]
    unpub = [base]
    for j in range(1, k + 1):
        unpub.append(account_risk(states, frozenset(order[:j])) if j <= len(order) else unpub[-1])
    exp_ids = [st["post_id"] for st in states if st["explicit"]]
    solo = sorted(exp_ids, key=lambda p: (account_risk(states, rewrite=frozenset([p])), p))
    rew = [base] + [account_risk(states, rewrite=frozenset(solo[:j])) for j in range(1, len(solo) + 1)]
    return {"base": base, "unpublish": unpub, "unpublish_stopped_at": len(order) if len(order) < k else None,
            "rewrite": rew, "tags": [base, account_risk(states, tags_off=True)]}


# ── 실행 ───────────────────────────────────────────────────────────────

def fingerprint() -> dict[str, Any]:
    import subprocess
    import time

    def sha(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    gold = hashlib.sha256(b"".join(sha(p).encode() for p in sorted(GOLD.glob("*_spans.jsonl")))).hexdigest()
    return {"commit": commit, "target": TARGET, "weights": WEIGHTS, "inputs_full_sha256": sha(INPUTS),
            "gold_files_sha256": gold, "test_ids_sha256": sha(TEST_IDS),
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def summarize(vals: Sequence[float]) -> dict[str, Any]:
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "median": round(statistics.median(vals), 4), "mean": round(statistics.fmean(vals), 4),
            "zero": sum(v == 0 for v in vals), "max": round(max(vals), 4)}


def main() -> int:
    accounts = load_accounts()
    rows = []
    for acc in accounts:
        states = [post_state(p) for p in acc["posts"]]
        k = unpublish_k(len(states))
        base = account_risk(states)
        rec = run_recommend(acc)
        if abs(rec["projected"]["current_risk"] - round(base, 2)) > 0.011:
            raise SystemExit(f"{acc['persona_id']}: 위험 계산이 추천 엔진과 다르다 {base} vs {rec['projected']['current_risk']}")
        hid, tags, rew = rec_plan(rec)
        row = {"persona_id": acc["persona_id"], "n_posts": len(states), "k": k, "base": round(base, 4),
               "rec": {"hidden": hid, "tags_off": tags, "rewrite": rew, "met": rec["projected"]["target_met"],
                       "risk": rec["projected"]["projected_risk"]}, "opt": {}, "curves": curves(acc, states, k)}
        for name, w in WEIGHTS.items():
            best = optimum(states, k, w)
            row["opt"][name] = None if best is None else {
                "burden": best[0], "risk": round(best[1], 4), "hidden": len(best[2]), "rewrite": len(best[3]),
                "tags_off": best[4]}
            row.setdefault("rec_burden", {})[name] = burden(w, hid, tags, rew)
        rows.append(row)

    report = {}
    for name in WEIGHTS:
        over = [r for r in rows if r["base"] > TARGET + EPS]
        reach = [r for r in over if r["opt"][name] is not None]
        fail = [r for r in reach if not r["rec"]["met"]]
        both = [r for r in reach if r["rec"]["met"]]
        gaps = [(r["rec_burden"][name] - r["opt"][name]["burden"]) / r["opt"][name]["burden"] for r in both]
        fail_rate = len(fail) / len(reach) if reach else None
        med = statistics.median(gaps) if gaps else None
        report[name] = {"accounts": len(rows), "over_target": len(over), "opt_unreachable": len(over) - len(reach),
                        "rec_fail": len(fail), "fail_rate": None if fail_rate is None else round(fail_rate, 4),
                        "gap": summarize(gaps), "rec_better_than_opt": sum(g < -EPS for g in gaps)}
        if name == "main":
            report[name]["pass"] = {"gap_median": med is not None and med <= GAP_MAX + EPS,
                                    "fail_rate": fail_rate is not None and fail_rate <= FAIL_MAX + EPS}
    out = {"fingerprint": fingerprint(), "report": report, "accounts": rows}
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "gap.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
                                               newline="\n")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
