"""exp10 입력 초안 — [필수] 조치 3단계 재현을 위해 D 가 C 에 넘길 인물별 입력과 미리보기.

    PYTHONIOENCODING=utf-8 python experiments/exp10-action-repro/build_inputs.py

- 표본(본): exp09 와 같은 239편·105명 — test − 옛 IAA 16편 · clue 는 blind 검수본 · noise 는 최상위 검수본 (#278 답글)
- 표본(참고 full): 같은 105명의 **전체 글** (최상위 검수 골드) — 표본이 인물당 2.3편이라 비공개 단계가 과장되는지 보려는 비교용
- 위치태그: scripts/seed_sns.py 를 임시 DB 에 그대로 돌려 읽는다 (전체 코퍼스 · seed 42 · 잡담 제외 글의 30%)
- 위험도: C2 risk_total (7축별 최고 해상도의 평균) — condition 은 골드 스팬(전 채널) + 위치태그 condition
- 조치 순서: 비공개 → 활동 메타(위치태그 제거) → 리라이트 (#278 답글 1·2번)
- 리라이트 모사 세 가지 (2단 리라이터는 W9 · 교사 리라이트 라벨은 0건이라 규칙으로 모사한다):
  explicit(명시 단서만 교체 — 암묵·추론 단서는 문맥이라 남는다) · weaken(모든 단서 해상도 한 단계 낮춤) · remove(모든 단서 삭제 — 상한)
- 모델 호출 없음. 전부 결정적 규칙이다.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import math
import os
import sqlite3
import statistics
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORPUS = ROOT / "data/corpus/v0"
EXP09_MANIFEST = ROOT / "experiments/exp09-external-agreement/data/manifest.json"

# 비공개 편수 — 선행 PoC 예시 「이 글 3개를 비공개하면 79.7 → 41」(D-stage2.md §1 ④) 과
# R1 19편(C-specificity.md §3)에서 3/19. 인물 글 수에 비례시키고, 최소 1편 · 최소 1편은 공개로 남긴다.
UNPUBLISH_FRACTION = 3 / 19
# 나이는 규칙이 해상도 2 를 내지 않는다 (clues._age_resolution: 정확 3 · 5세 구간/힌트 1).
# 한 단계 = 그 축에서 규칙이 실제로 내는 바로 아래 해상도.
AGE_WEAKEN = {3: 1, 2: 1, 1: 0}
POC_RANGE = (54.0, 61.0)
REWRITE_MODES = ("explicit", "weaken", "remove")
# 본 지표는 explicit (PM 결정 2026-09-29) — weaken·remove 는 참고치(규칙 민감도)로 같이 낸다
MAIN_REWRITE_MODE = "explicit"
SCHEMA_PATH = ROOT / "docs/contracts/specificity.schema.json"


# ── 엔진 ────────────────────────────────────────────────────────────────

class Engine:
    def __init__(self, src: Path) -> None:
        sys.path.insert(0, str(src))
        self.clues = importlib.import_module("kopl.c2_specificity.clues")
        engine = importlib.import_module("kopl.c2_specificity.engine")
        model = importlib.import_module("kopl.c2_specificity.model")
        loo = importlib.import_module("kopl.c3_contribution.loo")
        self.src = Path(self.clues.__file__).resolve().parents[2]
        self.risk_total = engine.risk_total
        self.risk_by_axis = engine.risk_by_axis
        self.dictionary = engine.RegionDictionary()
        self.level_resolution = model.REGION_LEVEL_RESOLUTION
        self.leave_one_out = loo.leave_one_out

    def span_conditions(self, span: dict, post_id: str) -> list[dict]:
        """스팬 하나가 만드는 condition (관계 수식자·배우자 호칭 파생 포함)."""
        return self.clues.build_conditions([span], post_id, dictionary=self.dictionary)

    def post_conditions(self, spans: list[dict], post_id: str) -> list[dict]:
        return self.clues.build_conditions(spans, post_id, dictionary=self.dictionary)

    def geo_condition(self, tag: str, post_id: str) -> tuple[dict, str]:
        """위치태그 → location condition. 후보가 하나일 때만 geo_code (#272 7번 규칙)."""
        info = self.dictionary.resolve_info(tag)
        codes = list(info["codes"])
        resolution, status = 2, str(info["resolution"])
        cond = {"axis": "location", "kind": "administrative_area", "value": tag}
        if status == "unique" and len(codes) == 1:
            cond["geo_code"] = codes[0]
            level = str(self.dictionary.regions.get(codes[0], {}).get("level", ""))
            # seed_sns.geo_tag_for 는 주소가 두 토막이면 동까지 담는다 — 그때는 실제 수준을 쓴다
            resolution = self.level_resolution.get(level, 2)
        cond.update({"resolution": resolution, "confidence": 1.0, "source_post_ids": [post_id]})
        return cond, status

    def ancestor_at(self, code: str, resolution: int) -> str | None:
        seen: set[str] = set()
        while code and code not in seen:
            seen.add(code)
            region = self.dictionary.regions.get(code)
            if region is None:
                return None
            if self.level_resolution.get(str(region.get("level", ""))) == resolution:
                return code
            code = str(region.get("parent") or "")
        return None

    def weaken(self, cond: dict) -> dict | None:
        """해상도를 한 단계 낮춘다. 0 이 되면 condition 이 사라진다."""
        axis, res = cond["axis"], cond["resolution"]
        new = AGE_WEAKEN.get(res, res - 1) if axis == "age" else res - 1
        if new <= 0:
            return None
        out = copy.deepcopy(cond)
        out["resolution"] = new
        if axis == "age":
            out["kind"] = "age_hint"
        if axis == "location":
            out["kind"] = "administrative_area"
            code = cond.get("geo_code")
            if code:
                parent = self.ancestor_at(code, new)
                if parent:
                    out["geo_code"] = parent
                else:
                    out.pop("geo_code")
                    out.setdefault("value", code)
        return out


# ── 데이터 ──────────────────────────────────────────────────────────────

def read_jsonl(path: Path):
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def user_ref(persona: str) -> str:
    """exp09 (#278) 와 같은 8자리 — u_ + sha256(persona_id)[:8]."""
    return "u_" + hashlib.sha256(persona.encode()).hexdigest()[:8]


def select_sample() -> tuple[dict[str, dict], dict[str, dict], dict[str, str]]:
    """exp09 build_inputs.select_posts() 와 같은 규칙 (evaluate_test import 없이 다시 쓴 것)."""
    tests: dict[str, dict] = {}
    for row in read_jsonl(CORPUS / "splits/test.jsonl"):
        pid = row["post_id"]
        if pid in tests:
            raise SystemExit(f"test 중복 post_id: {pid}")
        tests[pid] = row
    assignment = json.loads((CORPUS / "gold/iaa/_assignment.json").read_text(encoding="utf-8-sig"))
    excluded = {f"{r['persona_id']}_{r['post']}" for r in assignment["글"]}
    if len(excluded) != 16 or not excluded <= set(tests):
        raise SystemExit(f"옛 IAA 제외 목록이 exp09 와 다르다: {len(excluded)}편")
    selected = {pid: row for pid, row in tests.items() if pid not in excluded}
    gold: dict[str, dict] = {}
    source_of: dict[str, str] = {}
    for source, pattern in (("blind", "gold/blind/*_spans.jsonl"), ("reviewed", "gold/*_spans.jsonl")):
        for path in sorted(CORPUS.glob(pattern)):
            for row in read_jsonl(path):
                pid = row.get("post_id")
                if pid not in selected or row.get("reviewed") is not True or pid in gold:
                    continue
                kind = selected[pid]["kind"]
                if (kind == "clue" and source == "blind") or (kind == "noise" and source == "reviewed"):
                    gold[pid] = row
                    source_of[pid] = source
    missing = set(selected) - set(gold)
    if missing:
        raise SystemExit(f"골드 없는 글: {sorted(missing)[:5]} …")
    return selected, gold, source_of


def check_against_exp09(selected: dict, gold: dict, *, allow_mismatch: bool) -> dict:
    """표본이 #278 과 같은지 — 입력 해시와 건수를 exp09 manifest 와 대조한다.

    splits/*.jsonl 은 커밋되지 않고, 다시 생성하면 잡담 80편 표본이 그때의 골드로 새로 뽑힌다.
    그래서 해시가 다르면 #278 과 다른 표본이다 — 기본은 멈추고, --allow-split-mismatch 면 기록만 한다.
    """
    m = json.loads(EXP09_MANIFEST.read_text(encoding="utf-8"))
    body_spans = sum(1 for g in gold.values() for s in g["spans"] if s["text_id"] == "body")
    got = {
        "posts": len(selected),
        "kinds": dict(Counter(r["kind"] for r in selected.values())),
        "personas": len({r["persona_id"] for r in selected.values()}),
        "body_spans": body_spans,
    }
    mismatches = [f"{key}: exp09 {m[key]} · 지금 {value}" for key, value in got.items() if m[key] != value]
    for rel in ("data/corpus/v0/splits/test.jsonl", "data/corpus/v0/gold/iaa/_assignment.json"):
        if m["sha256"][rel] != sha256(ROOT / rel):
            mismatches.append(f"sha256 다름: {rel}")
    if mismatches and not allow_mismatch:
        raise SystemExit("exp09(#278) 표본과 다르다 — " + " / ".join(mismatches))
    return {**got, "matches_exp09": not mismatches, "mismatches": mismatches}


def full_history(personas: set[str]) -> tuple[dict[str, dict], Counter]:
    """참고 표본 — 같은 인물의 전체 글 (최상위 골드 = 교사 라벨, 일부만 사람 검수).

    최상위 골드는 인물의 모든 글을 덮지만 reviewed:true 는 10~30% 뿐이다 (2026-09-29 실측).
    그래서 검수 여부와 무관하게 쓰고 검수 비율을 같이 남긴다 — #269 증류 타깃과 같은 라벨 출처다.
    최상위 골드가 없거나(C 계열) 글을 다 덮지 못하는 인물은 이력이 불완전해 뺀다.
    """
    gold: dict[str, dict] = {}
    skipped: Counter = Counter()
    for persona in sorted(personas):
        path = CORPUS / f"gold/{persona}_spans.jsonl"
        if not path.exists():
            skipped["persona_no_top_level_gold"] += 1
            continue
        corpus_ids = {r["post_id"] for r in read_jsonl(CORPUS / f"posts/{persona}.jsonl")}
        rows = {r["post_id"]: r for r in read_jsonl(path) if r.get("post_id")}
        if set(rows) != corpus_ids:
            skipped["persona_incomplete_gold"] += 1
            continue
        gold.update(rows)
        skipped["persona_included"] += 1
        skipped["posts_reviewed"] += sum(1 for r in rows.values() if r.get("reviewed") is True)
        skipped["posts_unreviewed"] += sum(1 for r in rows.values() if r.get("reviewed") is not True)
    return gold, skipped


def seed_geo_tags() -> tuple[dict[str, str | None], dict]:
    """seed_sns.py 를 임시 DB 에 그대로 돌린다 — 시연 SNS 가 보여주는 위치태그와 같은 값."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sns_seed.db"
        cmd = [
            sys.executable, str(ROOT / "scripts/seed_sns.py"),
            "--corpus", str(CORPUS / "posts"), "--personas", str(CORPUS / "personas"),
            "--db", str(db), "--reset",
        ]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env)
        if done.returncode != 0:
            raise SystemExit(f"seed_sns.py 실패:\n{done.stderr}")
        conn = sqlite3.connect(db)
        try:
            tags = {pid: tag for pid, tag in conn.execute("SELECT post_id, geo_tag FROM posts")}
        finally:
            conn.close()
    stats = {"posts": len(tags), "tagged": sum(1 for t in tags.values() if t)}
    return tags, stats


# ── 인물 단위 계산 ──────────────────────────────────────────────────────

def build_posts(eng: Engine, gold: dict[str, dict], tags: dict, meta: dict) -> tuple[dict[str, dict], Counter]:
    posts: dict[str, dict] = {}
    notes: Counter = Counter()
    for pid, row in gold.items():
        spans = [s for s in (row.get("spans") or []) if "level" in s and "subject" in s]
        notes["span_missing_level_or_subject"] += len(row.get("spans") or []) - len(spans)
        span_conds = []
        for span in spans:
            conds = eng.span_conditions(span, pid)
            if conds:
                span_conds.append((span, conds))
                notes[f"clue_span:{span['text_id'].split(':')[0]}"] += 1
        # 스팬별로 쪼갠 condition 합이 글 단위 build_conditions 와 같은 위험도인지 (관계 수식자 검산)
        whole = eng.risk_by_axis(eng.post_conditions(spans, pid))
        split = eng.risk_by_axis([c for _, cs in span_conds for c in cs])
        if whole != split:
            raise SystemExit(f"{pid}: 스팬별 condition 합이 글 단위와 다르다 {whole} ≠ {split}")
        tag = tags.get(pid)
        geo, status = eng.geo_condition(tag, pid) if tag else (None, None)
        if status:
            notes[f"geo_tag:{status}"] += 1
        posts[pid] = {
            "post_id": pid,
            "persona_id": row["persona_id"],
            "kind": meta.get(pid, {}).get("kind"),
            "label_source": meta.get(pid, {}).get("label_source"),
            "negative_control": bool((row.get("flags") or {}).get("negative_control")),
            "geo_tag": tag,
            "geo_cond": geo,
            "span_conds": span_conds,
        }
    return posts, notes


def conditions(posts: dict, visible, *, meta: bool = True, rewritten: dict | None = None) -> list[dict]:
    out: list[dict] = []
    for pid in visible:
        post = posts[pid]
        for span, conds in post["span_conds"]:
            key = (pid, span["span_id"])
            out.extend(rewritten[key] if rewritten is not None and key in rewritten else conds)
        if meta and post["geo_cond"] is not None:
            out.append(post["geo_cond"])
    return out


def unpublish_k(n: int) -> int:
    return min(max(1, math.floor(UNPUBLISH_FRACTION * n + 0.5)), n - 1)


def rewrite_plan(eng: Engine, posts: dict, visible, mode: str) -> tuple[dict, list[dict]]:
    plan: dict = {}
    rows: list[dict] = []
    for pid in visible:
        for span, conds in posts[pid]["span_conds"]:
            if mode == "explicit" and span["level"] != "explicit":
                continue
            after = [w for w in (eng.weaken(c) for c in conds) if w is not None] if mode == "weaken" else []
            plan[(pid, span["span_id"])] = after
            rows.append({
                "post_id": pid,
                "span_id": span["span_id"],
                "text_id": span["text_id"],
                "type": span["type"],
                "level": span["level"],
                "before": conds,
                "after": after,
            })
    return plan, rows


def pct_drop(before: float, after: float) -> float | None:
    return None if before <= 0 else round(100.0 * (before - after) / before, 2)


def run_persona(eng: Engine, persona: str, posts: dict, pids: list[str]) -> dict:
    ids = sorted(pids)
    ref = user_ref(persona)

    def risk_of(selected, **kw) -> float:
        return eng.risk_total(conditions(posts, selected, **kw))

    r0 = risk_of(ids)
    k = unpublish_k(len(ids))
    loo = eng.leave_one_out(user_ref=ref, post_ids=ids, risk_fn=lambda sel: risk_of(sel), max_greedy_remove=k)
    hidden = [step["remove"] for step in loo["output"]["greedy_path"]]
    public = [pid for pid in ids if pid not in set(hidden)]
    r1 = risk_of(public)
    r2 = risk_of(public, meta=False)
    meta_removed = [posts[pid]["geo_cond"] for pid in public if posts[pid]["geo_cond"] is not None]

    modes = {}
    for mode in REWRITE_MODES:
        plan, rows = rewrite_plan(eng, posts, public, mode)
        r3 = risk_of(public, meta=False, rewritten=plan)
        plan_all, _ = rewrite_plan(eng, posts, ids, mode)
        solo = risk_of(ids, rewritten=plan_all)
        modes[mode] = {"spans": rows, "risk_after": round(r3, 2), "solo_risk": round(solo, 2)}

    solo_unpublish = r1  # 비공개가 첫 단계라 단독 = 누적 1단계
    solo_meta = risk_of(ids, meta=False)
    return {
        "persona_id": persona,
        "user_ref": ref,
        "post_ids": ids,
        "posts": [
            {
                "post_id": pid,
                "kind": posts[pid]["kind"],
                "label_source": posts[pid]["label_source"],
                "negative_control": posts[pid]["negative_control"],
                "geo_tag": posts[pid]["geo_tag"],
            }
            for pid in ids
        ],
        "baseline": {
            "risk": round(r0, 2),
            "by_axis": eng.risk_by_axis(conditions(posts, ids)),
            "conditions": conditions(posts, ids),
        },
        "actions": [
            {
                "step": 1,
                "action_type": "unpublish",
                "post_ids": hidden,
                "k_max": k,
                "stalled": len(hidden) < k,
                "loo_contributions": [
                    {"post_id": r["post_id"], "delta": r["delta"], "rank": r["rank"]}
                    for r in loo["output"]["contributions"]
                ],
                "greedy_path": loo["output"]["greedy_path"],
            },
            {
                "step": 2,
                "action_type": "activity_meta",
                "meta_field": "geo_tag",
                "remove_conditions": meta_removed,
            },
            {
                "step": 3,
                "action_type": "rewrite",
                "modes": {m: {"spans": v["spans"]} for m, v in modes.items()},
            },
        ],
        "preview": {
            "cumulative": {
                "baseline": round(r0, 2),
                "after_unpublish": round(r1, 2),
                "after_meta": round(r2, 2),
                "after_rewrite": {m: v["risk_after"] for m, v in modes.items()},
            },
            "solo": {
                "unpublish": round(solo_unpublish, 2),
                "activity_meta": round(solo_meta, 2),
                "rewrite": {m: v["solo_risk"] for m, v in modes.items()},
            },
        },
    }


# ── 요약 ────────────────────────────────────────────────────────────────

def dist(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    q = statistics.quantiles(values, n=4, method="inclusive") if len(values) >= 2 else [values[0]] * 3
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 2),
        "median": round(statistics.median(values), 2),
        "p25": round(q[0], 2),
        "p75": round(q[2], 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }


def summarize(rows: list[dict]) -> dict:
    live = [r for r in rows if r["baseline"]["risk"] > 0]
    out: dict = {
        "personas": len(rows),
        "baseline_zero": len(rows) - len(live),
        "evaluated": len(live),
        "posts": sum(len(r["post_ids"]) for r in rows),
        "posts_per_persona": dist([len(r["post_ids"]) for r in rows]),
        "baseline_risk": dist([r["baseline"]["risk"] for r in live]),
        "unpublish": {
            "k_max": dict(sorted(Counter(r["actions"][0]["k_max"] for r in live).items())),
            "hidden": dict(sorted(Counter(len(r["actions"][0]["post_ids"]) for r in live).items())),
            "stalled": sum(r["actions"][0]["stalled"] for r in live),
            "hidden_share_of_posts": dist([
                100.0 * len(r["actions"][0]["post_ids"]) / len(r["post_ids"]) for r in live
            ]),
        },
        "geo": {
            "personas_with_tag": sum(any(p["geo_tag"] for p in r["posts"]) for r in live),
            "meta_step_changed_risk": sum(
                r["preview"]["cumulative"]["after_meta"] < r["preview"]["cumulative"]["after_unpublish"] for r in live
            ),
            "meta_solo_changed_risk": sum(
                r["preview"]["solo"]["activity_meta"] < r["baseline"]["risk"] for r in live
            ),
        },
    }
    for mode in REWRITE_MODES:
        cum: list[float] = []
        steps: dict[str, list[float]] = {"unpublish": [], "activity_meta": [], "rewrite": []}
        solo: dict[str, list[float]] = {"unpublish": [], "activity_meta": [], "rewrite": []}
        band: Counter = Counter()
        for r in live:
            c, s, b = r["preview"]["cumulative"], r["preview"]["solo"], r["baseline"]["risk"]
            final = c["after_rewrite"][mode]
            drop = pct_drop(b, final)
            cum.append(drop)
            band["below_54" if drop < POC_RANGE[0] else "within_54_61" if drop <= POC_RANGE[1] else "above_61"] += 1
            steps["unpublish"].append(100.0 * (b - c["after_unpublish"]) / b)
            steps["activity_meta"].append(100.0 * (c["after_unpublish"] - c["after_meta"]) / b)
            steps["rewrite"].append(100.0 * (c["after_meta"] - final) / b)
            solo["unpublish"].append(pct_drop(b, s["unpublish"]))
            solo["activity_meta"].append(pct_drop(b, s["activity_meta"]))
            solo["rewrite"].append(pct_drop(b, s["rewrite"][mode]))
        baseline_sum = sum(r["baseline"]["risk"] for r in live)
        final_sum = sum(r["preview"]["cumulative"]["after_rewrite"][mode] for r in live)
        out[f"rewrite={mode}"] = {
            "cumulative_drop_pct": dist(cum),
            "pooled_drop_pct": round(100.0 * (baseline_sum - final_sum) / baseline_sum, 2) if baseline_sum else None,
            "mean_risk_path": {
                "baseline": round(statistics.fmean(r["baseline"]["risk"] for r in live), 2),
                "after_unpublish": round(statistics.fmean(r["preview"]["cumulative"]["after_unpublish"] for r in live), 2),
                "after_meta": round(statistics.fmean(r["preview"]["cumulative"]["after_meta"] for r in live), 2),
                "after_rewrite": round(statistics.fmean(r["preview"]["cumulative"]["after_rewrite"][mode] for r in live), 2),
            },
            "step_share_of_baseline_pct": {k: dist(v) for k, v in steps.items()},
            "solo_drop_pct": {k: dist(v) for k, v in solo.items()},
            "vs_poc_54_61": dict(band),
        }
    return out


def validate_conditions(rows: list[dict]) -> str:
    """계약 condition 스키마 대조 (jsonschema 가 없으면 건너뛴다)."""
    try:
        import jsonschema
    except ImportError:
        return "skipped (jsonschema 없음)"
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    sub = {"$defs": schema["$defs"], "$ref": "#/$defs/condition"}
    if "$schema" in schema:
        sub["$schema"] = schema["$schema"]
    validator = jsonschema.validators.validator_for(schema)(sub)
    n = 0
    for r in rows:
        items = list(r["baseline"]["conditions"]) + list(r["actions"][1]["remove_conditions"])
        for mode in r["actions"][2]["modes"].values():
            for span in mode["spans"]:
                items += span["before"] + span["after"]
        for cond in items:
            errors = sorted(validator.iter_errors(cond), key=str)
            if errors:
                raise SystemExit(f"{r['persona_id']}: 계약 위반 condition {cond} — {errors[0].message}")
            n += 1
    return f"ok ({n} conditions)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-src", default=str(ROOT / "src"), help="kopl 이 있는 src")
    ap.add_argument("--out", default=str(HERE))
    ap.add_argument("--allow-split-mismatch", action="store_true",
                    help="test.jsonl 이 exp09 정본과 달라도 진행 (미리보기용 — 결과에 표시된다)")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "results").mkdir(parents=True, exist_ok=True)

    eng = Engine(Path(a.engine_src))
    selected, gold, source_of = select_sample()
    sample_check = check_against_exp09(selected, gold, allow_mismatch=a.allow_split_mismatch)
    tags, geo_stats = seed_geo_tags()

    personas = {r["persona_id"] for r in selected.values()}
    full_gold, full_skipped = full_history(personas)
    sample_meta = {pid: {"kind": selected[pid]["kind"], "label_source": source_of[pid]} for pid in selected}
    full_meta = {
        pid: {
            "kind": selected[pid]["kind"] if pid in selected else None,
            "label_source": "reviewed" if full_gold[pid].get("reviewed") is True else "teacher",
        }
        for pid in full_gold
    }

    scopes = {}
    for scope, scope_gold, meta in (("sample", gold, sample_meta), ("full", full_gold, full_meta)):
        posts, notes = build_posts(eng, scope_gold, tags, meta)
        by_persona: dict[str, list[str]] = {}
        for pid, post in posts.items():
            by_persona.setdefault(post["persona_id"], []).append(pid)
        rows = [run_persona(eng, p, posts, pids) for p, pids in sorted(by_persona.items())]
        with (out / "data" / f"inputs_{scope}.jsonl").open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        scopes[scope] = {"summary": summarize(rows), "notes": dict(sorted(notes.items())), "schema": validate_conditions(rows)}

    preview = {
        "sample_check_vs_exp09": sample_check,
        "geo_seed": geo_stats,
        "full_skipped": dict(full_skipped),
        "rules": {
            "order": ["unpublish", "activity_meta", "rewrite"],
            "unpublish": "LOO greedy_path 앞 k편 (위험도를 실제로 낮추는 글만) · k = min(max(1, round(n·3/19)), n−1)",
            "activity_meta": "공개로 남은 글의 위치태그 condition 전부 제거 (활동 시간대는 축이 없어 제외)",
            "rewrite_explicit": "공개로 남은 글의 명시(explicit) 단서 스팬만 교체 = condition 제거 · 암묵·추론 단서는 남는다",
            "rewrite_weaken": "공개로 남은 글의 단서 스팬마다 해상도 한 단계 낮춤 (나이 정확→5세 구간) · 0 이면 제거",
            "rewrite_remove": "공개로 남은 글의 단서 스팬 condition 전부 제거 — 누적 경로에서는 정의상 0 (상한)",
            "channels": "title · body · photo_caption 스팬 전부 (profile_bio 는 표본 밖)",
        },
        "main_rewrite_mode": MAIN_REWRITE_MODE,
        "engine_src": eng.src.relative_to(ROOT).as_posix() if eng.src.is_relative_to(ROOT) else "external",
        "scopes": scopes,
    }
    (out / "results" / "preview.json").write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
    brief = {
        s: {k: v["summary"][k] for k in ("personas", "baseline_zero", "evaluated", "posts")}
        | {m: v["summary"][f"rewrite={m}"]["cumulative_drop_pct"]["median"] for m in REWRITE_MODES}
        for s, v in scopes.items()
    }
    print(json.dumps(brief, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
