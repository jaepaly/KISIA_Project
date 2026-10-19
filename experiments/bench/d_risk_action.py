"""러너 위험도 · 조치 단계 — 1단 예측 스팬으로 사용자별 위험도와 조치 효과를 잰다 (README D 13번).

새로 계산하는 것은 없다. 앱 경로(kopl.c4_stage2.infer 의 조건 함수 + C2 risk_total)와
추천 엔진(kopl.c4_stage2.recommend)을 그대로 부르고 숫자를 한 dict 로 모은다.

- 위험도: 사용자 글 묶음 → ``_app_conditions`` · ``_app_geo_condition`` → ``risk_total``.
  같은 글의 골드 스팬(``gold/<persona_id>_spans.jsonl`` 최상위 · blind 제외)으로 같은 계산을 해 비교한다.
- 조치: ``recommend(target_risk=0)`` — exp10 과 같은 3단계(비공개 k편 LOO greedy → 위치태그 → 리라이트 explicit)를
  끝까지 쌓은 감소율. 앱 기본 목표(40)에서 멈춘 감소율도 함께 낸다.
- 위치태그: ``scripts/seed_sns.py`` 의 ``seed_persona`` 를 DB 없이(가짜 연결) 그대로 돌려 얻는다 —
  exp10 과 같은 값(전체 코퍼스 · seed 42 · 잡담 제외 30%)이고 파일은 만들지 않는다.

사용 예:
    export PYTHONIOENCODING=utf-8 PYTHONPATH=src
    python experiments/bench/d_risk_action.py --preds preds_dev.jsonl --out results/bench/risk_dev
    python experiments/bench/d_risk_action.py --preds preds_dev.jsonl --out results/bench/risk_dev --ablation single_vs_account

test 글이 섞이면 --allow-test 없이는 오류로 멈춘다 (11/2 최종 측정 때만).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "scripts", Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from d_preds import read_pred_rows  # noqa: E402 — spans 없음 · 중복 post_id 는 멈춘다 (#359 B 리뷰)

CORPUS = ROOT / "data" / "corpus" / "v0"
GOLD_DIR = CORPUS / "gold"
TEST_IDS_PATH = CORPUS / "splits" / "test_post_ids.json"
SEED = 42  # seed_sns.py 기본값 — exp10 과 같다
ABLATIONS = ("single_vs_account", "explicit_removed")

Engine = tuple[Callable[..., list], Callable[..., Any], Callable[..., float]]  # (conditions_fn, geo_condition_fn, risk_fn)


# ── 입력 ────────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def load_test_ids(path: Path = TEST_IDS_PATH) -> frozenset[str]:
    # 파일은 메타 dict — 목록은 post_ids (통째로 set 하면 키 6개만 남는다 · 10/13 사고)
    ids = json.loads(Path(path).read_text(encoding="utf-8"))["post_ids"]
    assert len(ids) == 255, f"test_post_ids.json 에 {len(ids)}개 — 255 여야 한다"
    return frozenset(ids)


def read_preds(preds_path: str | Path, *, post_ids: Iterable[str] | None = None,
               allow_test: bool = False, test_ids: frozenset[str] | None = None) -> dict[str, list[dict]]:
    """1단 예측 jsonl → {post_id: spans}. test 글이 섞이면 allow_test 없이는 멈춘다."""
    preds: dict[str, list[dict]] = {row["post_id"]: list(row["spans"]) for row in read_pred_rows(preds_path)}
    if post_ids is not None:
        keep = set(post_ids)
        preds = {pid: s for pid, s in preds.items() if pid in keep}
    test_ids = load_test_ids() if test_ids is None else test_ids
    leaked = sorted(set(preds) & test_ids)
    if leaked and not allow_test:
        raise ValueError(f"⛔ test 글 {len(leaked)}편이 입력에 섞였다 (예: {leaked[:3]}) — "
                         "11/2 최종 측정 때만 allow_test=True(--allow-test) 로 돌린다")
    return preds


def persona_of(post_id: str) -> str:
    return post_id.split("_")[0]


def group_by_user(preds: Mapping[str, list[dict]], limit_users: int | None = None) -> dict[str, list[str]]:
    users: dict[str, list[str]] = defaultdict(list)
    for pid in sorted(preds):
        users[persona_of(pid)].append(pid)
    names = sorted(users)[:limit_users] if limit_users else sorted(users)
    return {u: users[u] for u in names}


def load_gold(persona: str, gold_dir: Path = GOLD_DIR) -> dict[str, list[dict]] | None:
    """최상위 골드(blind 제외) → {post_id: spans}. 파일이 없으면 None."""
    path = Path(gold_dir) / f"{persona}_spans.jsonl"
    if not path.exists():
        return None
    out: dict[str, list[dict]] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "post_id" in row:  # 첫 줄은 메타 헤더
            out[str(row["post_id"])] = list(row.get("spans") or [])
    return out


class _NullConn:
    """seed_persona 가 부르는 conn.execute 를 받아 위치태그만 모은다 — DB 를 만들지 않는다."""

    def __init__(self) -> None:
        self.tags: dict[str, str | None] = {}

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        if "INTO posts" in sql:
            self.tags[str(params[0])] = params[5]
        return type("Cur", (), {"rowcount": 1})()


def seed_geo_tags() -> dict[str, str | None]:
    """seed_sns.py 와 같은 순서·시드로 위치태그를 뽑는다 (exp10 의 임시 DB 결과와 같은 값)."""
    import seed_sns

    posts_dir, personas_dir = CORPUS / "posts", CORPUS / "personas"
    conn, rng = _NullConn(), random.Random(SEED)
    for persona in seed_sns.discover_persona_ids(posts_dir):
        seed_sns.seed_persona(conn, posts_dir, personas_dir, persona, rng)  # type: ignore[arg-type]
    return conn.tags


def load_texts(post_ids: Iterable[str]) -> dict[str, dict[str, str]]:
    """리라이트 후보 계산용 원문 (코퍼스 posts/ · 생성 글)."""
    want = set(post_ids)
    out: dict[str, dict[str, str]] = {}
    for persona in sorted({persona_of(p) for p in want}):
        path = CORPUS / "posts" / f"{persona}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row["post_id"] in want:
                    out[row["post_id"]] = row.get("texts") or {}
    return out


# ── 계산 (앱 경로 그대로) ────────────────────────────────────────────────

def app_engine() -> Engine:
    """앱(infer.analyze → recommend)과 같은 조건 함수 · 위험도."""
    from kopl.c2_specificity.engine import risk_total
    from kopl.c4_stage2.infer import _app_conditions, _app_geo_condition

    return _app_conditions, _app_geo_condition, risk_total


def user_risk(posts: Sequence[Mapping[str, Any]], engine: Engine, *, geo: bool = True) -> float:
    """recommend() 의 risk() 와 같은 조립 — 글별 조건 + 위치태그 조건 → risk_total."""
    conditions_fn, geo_fn, risk_fn = engine
    conds: list[dict] = []
    for p in posts:
        conds.extend(conditions_fn(list(p.get("spans") or []), p["post_id"]))
        if geo and p.get("geo_tag"):
            c = geo_fn(p["geo_tag"], p["post_id"])
            if c is not None:
                conds.append(c)
    return float(risk_fn(conds))


def _recommend(user: str, posts: Sequence[Mapping[str, Any]], engine: Engine, target: float) -> dict:
    from kopl.c4_stage2.recommend import recommend
    from seed_sns import user_ref_for  # 시연 SNS 와 같은 user_ref (LOO 가 형식을 검사한다)

    conditions_fn, geo_fn, risk_fn = engine
    return recommend(user_ref=user_ref_for(user), posts=list(posts), target_risk=target,
                     conditions_fn=conditions_fn, geo_condition_fn=geo_fn, risk_fn=risk_fn)


def _rank(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1  # 동률은 평균 순위
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman ρ (동률 평균 순위 → Pearson). 값이 모두 같으면 None."""
    if len(xs) < 2:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def _dist(xs: Sequence[float]) -> dict[str, float | int | None]:
    if not xs:
        return {"n": 0, "mean": None, "median": None}
    return {"n": len(xs), "mean": round(statistics.fmean(xs), 2), "median": round(statistics.median(xs), 2)}


def _compare(pred: Sequence[float], gold: Sequence[float]) -> dict[str, Any]:
    """사용자별 예측 스팬 위험 vs 골드 스팬 위험 — 보조 지표.

    exp11 의 ρ(위험 vs LLM 추론 성공 · README G1)와 **다른 지표**다. 1단 예측이 위험 순위를 골드만큼 매기는지만 본다.
    """
    n = len(pred)
    rho = spearman(pred, gold)
    return {
        "n_users": n,
        "pred_vs_gold_risk_spearman": None if rho is None else round(rho, 4),
        "mae": round(statistics.fmean(abs(a - b) for a, b in zip(pred, gold)), 2) if n else None,
        "pred_gt_gold": round(sum(a > b for a, b in zip(pred, gold)) / n, 4) if n else None,
        "pred_lt_gold": round(sum(a < b for a, b in zip(pred, gold)) / n, 4) if n else None,
        "pred_mean": round(statistics.fmean(pred), 2) if n else None,
        "gold_mean": round(statistics.fmean(gold), 2) if n else None,
    }


def _meta(preds_path: str | Path, preds: Mapping[str, Any], users: Mapping[str, Any], started: float,
          extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "preds_path": str(preds_path),
        "preds_sha256": _sha256(Path(preds_path)),
        "n_users": len(users),
        "n_posts": sum(len(v) for v in users.values()),
        "n_posts_in_file": len(preds),
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "elapsed_sec": round(time.perf_counter() - started, 1),
        **(extra or {}),
    }


def _prepare(preds_path: str | Path, *, post_ids, limit_users, allow_test, test_ids, geo_tags):
    preds = read_preds(preds_path, post_ids=post_ids, allow_test=allow_test, test_ids=test_ids)
    users = group_by_user(preds, limit_users)
    geo_note = "seed_sns 재현 (seed 42 · 잡담 제외 30%)"
    if geo_tags is None:
        try:
            geo_tags = seed_geo_tags()
        except Exception as e:  # noqa: BLE001 — 위치태그 없이도 나머지는 잰다
            geo_tags, geo_note = {}, f"위치태그 단계 미포함 ({type(e).__name__}: {str(e)[:120]})"
    elif not geo_tags:
        geo_note = "위치태그 단계 미포함"
    else:
        geo_note = "주입값"
    return preds, users, geo_tags, geo_note


def _write(out_dir: str | Path, name: str, result: Mapping[str, Any]) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ── 공개 API ────────────────────────────────────────────────────────────

def run_risk_action(preds_path: str | Path, out_dir: str | Path, *, post_ids: Iterable[str] | None = None,
                    limit_users: int | None = None, allow_test: bool = False, gold_dir: Path = GOLD_DIR,
                    geo_tags: Mapping[str, str | None] | None = None, engine: Engine | None = None,
                    test_ids: frozenset[str] | None = None, app_target: float = 40.0) -> dict[str, Any]:
    """사용자별 위험도(예측 vs 골드) + 조치 3단계 감소율(예측 스팬 기준) → risk_action.json.

    app_target: 앱 목표 위험도(STAGE2_TARGET_RISK · 기본 40) — 묶음 CLI 는 지문에 적는 값과 같은 숫자를 넘긴다.
    둘 다 보조 지표다: 위험 상관은 exp11(위험 vs LLM 추론 성공)과, 조치 감소율은 exp10(골드 · clues.build_conditions)과
    다르다. 기존 exp10 · exp11 회귀는 ``regression_commands`` 로 따로 돈다(--final).
    """
    started = time.perf_counter()
    preds, users, geo_tags, geo_note = _prepare(preds_path, post_ids=post_ids, limit_users=limit_users,
                                                allow_test=allow_test, test_ids=test_ids, geo_tags=geo_tags)
    engine = engine or app_engine()

    per_user: list[dict[str, Any]] = []
    skipped: dict[str, list[str]] = {"no_gold_file": [], "gold_missing_posts": []}
    for user, pids in users.items():
        posts = [{"post_id": p, "spans": preds[p], "geo_tag": geo_tags.get(p)} for p in pids]
        row: dict[str, Any] = {"user": user, "n_posts": len(pids),
                               "n_tagged": sum(1 for p in posts if p["geo_tag"]),
                               "pred_risk": round(user_risk(posts, engine), 2),
                               "pred_risk_spans_only": round(user_risk(posts, engine, geo=False), 2)}
        gold = load_gold(user, gold_dir)
        if gold is None:
            skipped["no_gold_file"].append(user)
        else:
            missing = [p for p in pids if p not in gold]
            if missing:
                skipped["gold_missing_posts"].append(user)
            gposts = [{"post_id": p["post_id"], "spans": gold[p["post_id"]], "geo_tag": p["geo_tag"]}
                      for p in posts if p["post_id"] in gold]
            if gposts:
                # 골드와 견줄 때는 두 쪽 다 골드가 있는 글만 쓴다
                both = [p for p in posts if p["post_id"] in gold]
                row["pred_risk_on_gold_posts"] = round(user_risk(both, engine), 2)
                row["pred_risk_on_gold_posts_spans_only"] = round(user_risk(both, engine, geo=False), 2)
                row["gold_risk"] = round(user_risk(gposts, engine), 2)
                row["gold_risk_spans_only"] = round(user_risk(gposts, engine, geo=False), 2)
        # 조치 — exp10 3단계 끝까지(target 0) · 앱 기본 목표에서 멈춘 것
        if row["pred_risk"] > 0:
            full = _recommend(user, posts, engine, 0.0)
            app = _recommend(user, posts, engine, app_target)
            row["action_full"] = {"projected_risk": full["projected"]["projected_risk"],
                                  "reduction_pct": full["projected"]["reduction_pct"],
                                  "steps": [a["action_type"] for a in full["actions"]]}
            row["action_app"] = {"projected_risk": app["projected"]["projected_risk"],
                                 "reduction_pct": app["projected"]["reduction_pct"],
                                 "target_met": app["projected"]["target_met"],
                                 "steps": [a["action_type"] for a in app["actions"]]}
        per_user.append(row)

    cmp_rows = [r for r in per_user if "gold_risk" in r]
    acted = [r for r in per_user if "action_full" in r]
    full_red = [r["action_full"]["reduction_pct"] for r in acted]
    app_red = [r["action_app"]["reduction_pct"] for r in acted]
    step_counts: dict[str, int] = defaultdict(int)
    for r in acted:
        for s in r["action_full"]["steps"]:
            step_counts[s] += 1

    result = {
        "meta": _meta(preds_path, preds, users, started, {"geo_tag": geo_note, "app_target_risk": app_target}),
        "risk": {
            "note": "보조 지표 — 예측 스팬 위험 vs 골드 스팬 위험 (pred_vs_gold_risk_spearman). "
                    "exp11 의 ρ(위험 vs LLM 추론 성공)와 다른 지표다",
            "pred_mean": round(statistics.fmean(r["pred_risk"] for r in per_user), 2) if per_user else None,
            "vs_gold": _compare([r["pred_risk_on_gold_posts"] for r in cmp_rows], [r["gold_risk"] for r in cmp_rows]),
            "vs_gold_spans_only": _compare([r["pred_risk_on_gold_posts_spans_only"] for r in cmp_rows],
                                           [r["gold_risk_spans_only"] for r in cmp_rows]),
            "skipped_users": {k: len(v) for k, v in skipped.items()},
            "skipped_detail": skipped,
        },
        "action": {
            "basis": "예측 스팬 · 앱 조건 생성(infer._app_conditions) · recommend(target 0) = exp10 3단계 끝까지 "
                     "(비공개 → 위치태그 → 리라이트 explicit)",
            "note": "exp10(골드 스팬 · clues.build_conditions) 재현값 아님 — 같은 3단계를 예측 스팬 · 앱 경로로 잰 보조 지표",
            "n_users": len(acted),
            "n_zero_baseline_excluded": len(per_user) - len(acted),
            "full_reduction_pct": _dist(full_red),
            "full_projected_risk_mean": _dist([r["action_full"]["projected_risk"] for r in acted])["mean"],
            "full_step_users": dict(step_counts),
            "app_target_reduction_pct": _dist(app_red),
            "app_target_met_ratio": (round(sum(r["action_app"]["target_met"] for r in acted) / len(acted), 4)
                                     if acted else None),
            "rewrite_candidates": _rewrite_coverage(preds, users),
        },
        "per_user": per_user,
    }
    _write(out_dir, "risk_action.json", result)
    return result


def _rewrite_coverage(preds: Mapping[str, list[dict]], users: Mapping[str, list[str]]) -> dict[str, Any]:
    """리라이트 조치 대상(본인 명시 스팬) 중 rewrite.rewrites_for 가 후보를 낸 비율 — 앱 「바꿔 쓰기」 화면과 같은 함수."""
    from kopl.c4_stage2.rewrite import rewrites_for

    pids = [p for v in users.values() for p in v]
    try:
        texts = load_texts(pids)
    except Exception as e:  # noqa: BLE001
        return {"skipped": f"원문 읽기 실패: {type(e).__name__}"}
    targets = covered = 0
    for pid in pids:
        spans = [{**s, "span_id": f"{pid}#{i}"} for i, s in enumerate(preds[pid])]
        want = {s["span_id"] for s in spans if s.get("subject") == "self" and s.get("level") == "explicit"}
        if not want:
            continue
        got = {r["span_id"] for r in rewrites_for([{"post_id": pid, "texts": texts.get(pid, {}), "spans": spans}])}
        targets += len(want)
        covered += len(want & got)
    return {"explicit_self_spans": targets, "with_candidate": covered,
            "ratio": round(covered / targets, 4) if targets else None}


def run_ablation(name: str, preds_path: str | Path, out_dir: str | Path, *, post_ids: Iterable[str] | None = None,
                 limit_users: int | None = None, allow_test: bool = False,
                 geo_tags: Mapping[str, str | None] | None = None, engine: Engine | None = None,
                 test_ids: frozenset[str] | None = None) -> dict[str, Any]:
    """name ∈ single_vs_account · explicit_removed. 위치태그 포함(앱과 같음)과 스팬만 두 갈래를 낸다."""
    if name not in ABLATIONS:
        raise ValueError(f"ablation: {name!r} — {ABLATIONS} 중 하나")
    started = time.perf_counter()
    preds, users, geo_tags, geo_note = _prepare(preds_path, post_ids=post_ids, limit_users=limit_users,
                                                allow_test=allow_test, test_ids=test_ids, geo_tags=geo_tags)
    engine = engine or app_engine()

    per_user: list[dict[str, Any]] = []
    for user, pids in users.items():
        posts = [{"post_id": p, "spans": preds[p], "geo_tag": geo_tags.get(p)} for p in pids]
        row: dict[str, Any] = {"user": user, "n_posts": len(pids)}
        for geo, key in ((True, "with_geo"), (False, "spans_only")):
            if name == "single_vs_account":
                single = max(user_risk([p], engine, geo=geo) for p in posts)
                account = user_risk(posts, engine, geo=geo)
                row[key] = {"single_max": round(single, 2), "account": round(account, 2)}
            else:
                before = user_risk(posts, engine, geo=geo)
                after = user_risk([{**p, "spans": [s for s in p["spans"] if s.get("level") != "explicit"]}
                                   for p in posts], engine, geo=geo)
                row[key] = {"before": round(before, 2), "after": round(after, 2)}
        per_user.append(row)

    summary: dict[str, Any] = {}
    for key in ("with_geo", "spans_only"):
        rows = [r[key] for r in per_user]
        if name == "single_vs_account":
            live = [r for r in rows if r["account"] > 0]
            ups = [r["account"] - r["single_max"] for r in live if r["account"] > r["single_max"]]
            summary[key] = {
                "n_users": len(live),
                "n_zero_excluded": len(rows) - len(live),
                "raised_ratio": round(len(ups) / len(live), 4) if live else None,
                "raise_among_raised": _dist(ups),
                "raise_all": _dist([r["account"] - r["single_max"] for r in live]),
                "single_max_mean": _dist([r["single_max"] for r in live])["mean"],
                "account_mean": _dist([r["account"] for r in live])["mean"],
            }
        else:
            live = [r for r in rows if r["before"] > 0]
            red = [100.0 * (r["before"] - r["after"]) / r["before"] for r in live]
            summary[key] = {
                "n_users": len(live),
                "n_zero_excluded": len(rows) - len(live),
                "before_mean": _dist([r["before"] for r in live])["mean"],
                "after_mean": _dist([r["after"] for r in live])["mean"],
                "reduction_pct": _dist(red),
                "pooled_reduction_pct": (round(100.0 * (1 - sum(r["after"] for r in live)
                                                        / sum(r["before"] for r in live)), 2) if live else None),
            }

    result = {"meta": _meta(preds_path, preds, users, started, {"ablation": name, "geo_tag": geo_note}),
              "summary": summary, "per_user": per_user}
    _write(out_dir, f"ablation_{name}.json", result)
    return result


# ── 기존 exp10 · exp11 회귀 (11/2 최종 측정 때만) ───────────────────────

EXP10 = ROOT / "experiments" / "exp10-action-repro"
EXP11 = ROOT / "experiments" / "exp11-risk-correlation"


def regression_commands(out_dir: str | Path) -> dict[str, list[list[str]]]:
    """README D13 의 기존 지표를 그 실험 코드로 다시 내는 명령 — 결과는 전부 ``out_dir`` 아래에 쓴다(실험 폴더를 덮지 않는다).

    - exp10: build_inputs.py — 골드 스팬 · clues.build_conditions · 조치 3단계 (모델 · 외부 API 호출 없음 · test 표본)
    - exp11: score.py(저장된 교사 판정 teacher_all_scored.csv 재채점) → sensitivity.py(저장된 B 예측 2종 재채점)
      run_teacher.py 는 외부 LLM 을 부르므로 넣지 않는다
    """
    out = Path(out_dir)
    e11 = out / "exp11"
    return {
        "exp10": [[sys.executable, str(EXP10 / "build_inputs.py"), "--out", str(out / "exp10")]],
        "exp11": [
            [sys.executable, str(EXP11 / "score.py"), "--scored", str(EXP11 / "results" / "teacher_all_scored.csv"),
             "--windows-out", str(e11 / "teacher_window_scores.csv"), "--metrics-out", str(e11 / "teacher_metrics.json")],
            [sys.executable, str(EXP11 / "sensitivity.py"), "--results", str(e11)],
        ],
    }


def regression_outputs(out_dir: str | Path) -> dict[str, list[Path]]:
    """``regression_commands`` 가 반드시 만들어야 하는 파일 — 각 스크립트가 실제로 쓰는 이름 그대로.

    - exp10 build_inputs.py: data/inputs_sample.jsonl · data/inputs_full.jsonl · results/preview.json
    - exp11 score.py: --windows-out · --metrics-out / sensitivity.py: 예측 2종(v1 · v1_rules) × scored · window_scores · metrics
      + sensitivity_person_block_permutation.json
    """
    out = Path(out_dir)
    e10, e11 = out / "exp10", out / "exp11"
    sens = [e11 / f"sensitivity_{label}_{kind}" for label in ("v1", "v1_rules")
            for kind in ("scored.csv", "window_scores.csv", "metrics.json")]
    return {
        "exp10": [e10 / "data" / "inputs_sample.jsonl", e10 / "data" / "inputs_full.jsonl", e10 / "results" / "preview.json"],
        "exp11": [e11 / "teacher_window_scores.csv", e11 / "teacher_metrics.json", *sens,
                  e11 / "sensitivity_person_block_permutation.json"],
    }


# ── CLI ─────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="러너 위험도 · 조치 단계 (D)")
    ap.add_argument("--preds", required=True, type=Path, help="1단 예측 jsonl")
    ap.add_argument("--out", required=True, type=Path, help="결과 디렉터리")
    ap.add_argument("--ablation", nargs="*", choices=ABLATIONS, default=None,
                    help="ablation 만 돌린다 (여러 개 가능). 생략하면 위험도·조치")
    ap.add_argument("--limit-users", type=int, default=None)
    ap.add_argument("--no-geo-tag", action="store_true", help="위치태그 단계를 빼고 잰다")
    ap.add_argument("--allow-test", action="store_true", help="11/2 최종 측정용 — test 글이 섞여도 허용")
    a = ap.parse_args()

    geo = {} if a.no_geo_tag else None
    if a.ablation:
        for name in a.ablation:
            r = run_ablation(name, a.preds, a.out, limit_users=a.limit_users, allow_test=a.allow_test, geo_tags=geo)
            print(f"[{name}] users={r['meta']['n_users']} {r['meta']['elapsed_sec']}s")
            print(json.dumps(r["summary"], ensure_ascii=False, indent=2))
        return 0
    r = run_risk_action(a.preds, a.out, limit_users=a.limit_users, allow_test=a.allow_test, geo_tags=geo)
    m = r["meta"]
    print(f"users={m['n_users']} posts={m['n_posts']} {m['elapsed_sec']}s · 위치태그: {m['geo_tag']}")
    print(json.dumps({"risk": {k: v for k, v in r["risk"].items() if k != "skipped_detail"},
                      "action": r["action"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
