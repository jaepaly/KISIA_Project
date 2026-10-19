"""러너 2단 단계 (D) — 1단 예측 파일을 사용자 단위로 묶어 **앱과 같은 경로**(``kopl.c4_stage2.infer.analyze``)로 판정한다.

    export PYTHONIOENCODING=utf-8 PYTHONPATH=src
    python experiments/bench/d_stage2.py --preds <file> --out <dir> --mode rules --limit-users 20
    python experiments/bench/d_stage2.py --preds <file> --out <dir> --mode model --limit-users 3   # GPU · v2 어댑터

- 입력: 1단 jsonl 한 줄 ``{"post_id", "spans": [{text_id, start, end, type, text, level, subject}]}``
- 원문은 코퍼스(``data/corpus/v0/posts``)에서 채운다 — 앱(apps/analyzer real.stage2)처럼 채널별 NFC 원문 · span_id ·
  geo_tag(코퍼스에는 없어 None)를 붙여 ``analyze`` 에 넘긴다. 가명화 · 입력 상한(16/4 · 빈 글 뺌) · 프롬프트 · 출력 검증 ·
  규칙 폴백은 전부 infer 가 한다 (여기서 다시 구현하지 않는다)
- mode=rules: 앱 ``STAGE2_MODE=rules`` 와 같다 (모델 없이 규칙 판정 — 앱의 CPU 폴백 함수 findings_from_spans)
- mode=model: 앱 기본(``auto``)과 같게 모델을 쓰고 출력이 깨지면 규칙으로 떨어진다 — 떨어진 이유를 센다.
  모델 로드 자체가 안 되면 조용히 규칙으로 돌지 않고 멈춘다 (측정이 규칙으로 바뀌어 섞이지 않게)
- test 글(splits/test_post_ids.json)이 섞이면 멈춘다. ``--allow-test``/``--final``(11/2 최종 측정)일 때만 통과
- 이 단독 CLI 는 exp09 를 **실행하지 않는다** (``--final`` = test 허용만). exp09 회귀는 ``d_downstream --final`` 에서만
  추적 산출물 보호 경로(세 파일 · 어댑터 SHA 확인)로 돈다 — 여기는 명령(``exp09_commands``)과 산출 목록만 둔다
- 두 실행(rules · model)의 ``stage2_preds.jsonl`` 을 ``compare_stage2`` 로 user_ref × 속성 조인해 verdict 일치율을 낸다
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "experiments" / "exp08-stage2-sft", Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from kopl.c4_stage2 import infer  # noqa: E402
from kopl.c4_stage2.rules import ATTRS  # noqa: E402
from make_sft_v1 import user_ref as _user_ref  # noqa: E402 — seed_sns · C 기여도 타깃과 같은 규칙 (조인 키)

CORPUS_POSTS = ROOT / "data" / "corpus" / "v0" / "posts"
SPLITS = ROOT / "data" / "corpus" / "v0" / "splits" / "test_post_ids.json"
EXP09 = ROOT / "experiments" / "exp09-external-agreement"
MODES = ("rules", "model")


# ── 공통 ────────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        return head + ("+dirty" if dirty else "")
    except Exception:  # noqa: BLE001
        return ""


def load_test_ids(path: Path | None = None) -> frozenset[str]:
    """test 255편. 파일은 dict 다 — 통째로 set() 하면 키 6개만 남는다 (10/13 사고)."""
    d = json.loads(Path(path or SPLITS).read_text(encoding="utf-8"))
    ids = d["post_ids"]
    assert len(ids) == 255, f"test_post_ids.json 에 {len(ids)}개 — 255 여야 한다"
    return frozenset(ids)


def check_no_test(post_ids: Iterable[str], *, allow_test: bool = False, splits: Path | None = None) -> int:
    """입력에 섞인 test 글 수. allow_test 가 아니면 하나라도 있을 때 멈춘다."""
    leaked = sorted(set(post_ids) & load_test_ids(splits))
    if leaked and not allow_test:
        raise ValueError(f"test 글 {len(leaked)}편이 입력에 섞였다 (예: {leaked[:3]}) — "
                         "최종 측정이면 --allow-test(또는 --final) 를 준다")
    return len(leaked)


def read_preds(path: Path) -> list[dict[str, Any]]:
    """spans 없음 · 리스트 아님 · 중복 post_id 는 멈춘다 (d_preds · #359 B 리뷰)."""
    from d_preds import read_pred_rows
    return read_pred_rows(path)


def load_corpus(posts_dir: Path = CORPUS_POSTS) -> dict[str, dict[str, Any]]:
    """post_id → 코퍼스 글 (persona_id · texts). 프로필 파일(*_profile.json)은 2단 입력에 안 쓴다 (앱도 profile None)."""
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(Path(posts_dir).glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["post_id"]] = r
    return out


# ── 사용자 묶기 ──────────────────────────────────────────────────────────

def _app_texts(texts: Mapping[str, Any]) -> dict[str, str]:
    """앱 real._texts 와 같게 — 채널 원문을 NFC 로 (스팬 offset 기준) · 빈 채널은 뺀다."""
    return {k: unicodedata.normalize("NFC", v) for k, v in texts.items() if isinstance(v, str) and v}


def _with_span_ids(post_id: str, spans: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """1단 출력에 span_id 가 없으면 탐지기(exp06 infer.predict_raw)와 같은 규칙 ``<post_id>_sNN`` 으로 붙인다."""
    return [{**s, "span_id": s.get("span_id") or f"{post_id}_s{i:02d}"} for i, s in enumerate(spans, 1)]


def group_users(preds: list[Mapping[str, Any]], corpus: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """1단 예측 → 사용자 목록 ``[{persona_id, user_ref, posts: [analyze 입력 글]}]``. 순서는 persona_id · 글은 입력 순서."""
    users: dict[str, list[dict[str, Any]]] = {}
    for r in preds:
        pid = r["post_id"]
        src = corpus.get(pid)
        if src is None:
            raise KeyError(f"코퍼스에 없는 글: {pid} — 원문이 없으면 앱 경로(가명화)를 탈 수 없다")
        users.setdefault(src["persona_id"], []).append({
            "post_id": pid,
            "texts": _app_texts(src.get("texts") or {}),
            "spans": _with_span_ids(pid, list(r.get("spans") or [])),
            "geo_tag": (src.get("activity_meta") or {}).get("geo_tag"),
        })
    return [{"persona_id": p, "user_ref": _user_ref(p), "posts": users[p]} for p in sorted(users)]


# ── 구성 지문 ────────────────────────────────────────────────────────────

def resolve_adapter(adapter: str | Path | None) -> Path:
    """앱 Stage2Model(infer.py:243)과 같은 식 — 인자 · STAGE2_ADAPTER_DIR · exp08 results/adapter_v2.

    빈 환경변수도 앱처럼 그 값(빈 경로)을 쓴다 — 기본값으로 바꾸지 않는다.
    """
    return Path(adapter or os.getenv("STAGE2_ADAPTER_DIR", infer._DEFAULT_ADAPTER))


def config_fingerprint(mode: str, adapter: Path | None) -> dict[str, Any]:
    fp: dict[str, Any] = {
        "mode": mode,
        "app_mode": "rules" if mode == "rules" else "auto",  # 앱 STAGE2_MODE 로 치면
        "schema_version": infer.SCHEMA_VERSION,
        "model_version": infer.MODEL_VERSION,
        "rules_version": infer.RULES_VERSION,
        "base_model": infer.BASE_MODEL,
        "system_v2_sha256": hashlib.sha256(infer.SYSTEM_V2.encode("utf-8")).hexdigest(),
        "model_max_spans": infer.MODEL_MAX_SPANS,
        "model_max_spans_per_type": infer.MODEL_MAX_SPANS_PER_TYPE,
        "dict_version": infer._dict_version(),
        "adapter": None,
        "adapter_sha256": None,
    }
    if mode == "model" and adapter is not None:
        fp["adapter"] = str(adapter)
        fp["adapter_sha256"] = infer._sha256(adapter / "adapter_model.safetensors")
    return fp


# ── 실행 ────────────────────────────────────────────────────────────────

_FALLBACK = re.compile(r"\(fallback: (.*)\)\s*$")
_PARSE_FAIL = {"model output truncated", "model output invalid"}


def _fallback_reason(version: str) -> str | None:
    m = _FALLBACK.search(version)
    return m.group(1) if m else None


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "p90": None, "max": None}
    s = sorted(values)
    return {"mean": round(statistics.fmean(s), 3), "median": round(statistics.median(s), 3),
            "p90": round(s[min(len(s) - 1, int(0.9 * len(s)))], 3), "max": round(s[-1], 3)}


def run_stage2(preds_path: str | Path, out_dir: str | Path, *, mode: str = "rules", adapter: str | Path | None = None,
               post_ids: Iterable[str] | None = None, limit_users: int | None = None,
               allow_test: bool = False, corpus: Mapping[str, Mapping[str, Any]] | None = None,
               model: Any = None, splits: Path | None = None) -> dict[str, Any]:
    """사용자별 2단 판정 → ``out_dir/stage2_preds.jsonl`` + 요약 dict (JSON 직렬화 가능).

    corpus · model · splits 는 테스트용 주입구 — 실제 실행은 기본값(코퍼스 · v2 어댑터 · splits)을 쓴다.
    """
    if mode not in MODES:
        raise ValueError(f"mode: {mode!r} — {MODES} 중 하나")
    preds_path, out_dir = Path(preds_path), Path(out_dir)
    preds = read_preds(preds_path)
    if post_ids is not None:
        keep = set(post_ids)
        preds = [r for r in preds if r["post_id"] in keep]
    n_test = check_no_test((r["post_id"] for r in preds), allow_test=allow_test, splits=splits)
    users = group_users(preds, corpus if corpus is not None else load_corpus())
    if limit_users is not None:
        users = users[:limit_users]

    adapter_dir = resolve_adapter(adapter) if mode == "model" else None
    if mode == "model" and model is None:
        model = infer.Stage2Model(adapter_dir)  # 로드 실패는 그대로 올린다 — 규칙으로 바꿔 재지 않는다

    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for u in users:
        t0 = time.perf_counter()
        out = (infer.analyze(u["user_ref"], u["posts"], mode="rules") if mode == "rules"
               else infer.analyze(u["user_ref"], u["posts"], mode="auto", model=model))
        sec = time.perf_counter() - t0
        _, all_entries = infer.build_user_prompt(u["user_ref"], u["posts"])
        _, capped = infer.build_user_prompt(u["user_ref"], u["posts"], cap=True)
        n_in = sum(len(p["spans"]) for p in u["posts"])
        n_pseudo = sum(len(e["spans"]) for e in all_entries)
        version = out["provenance"]["model_version"]
        rows.append({
            "user_ref": u["user_ref"],
            "persona_id": u["persona_id"],
            "post_ids": [p["post_id"] for p in u["posts"]],
            "n_spans": n_in,
            "n_spans_dropped": n_in - n_pseudo,  # 오프셋·원문 불일치 · 가명화 실패로 빠진 스팬 (infer.pseudonymize_spans)
            "n_spans_model_input": sum(len(e["spans"]) for e in capped),
            "n_posts_model_input": len(capped),
            "findings": out["findings"],
            "model_version": version,
            "fallback_reason": _fallback_reason(version),
            "seconds": round(sec, 4),
        })
    with open(out_dir / "stage2_preds.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    dist = {a: dict(Counter(r["findings"][a]["verdict"] for r in rows)) for a in ATTRS}
    overall = Counter(r["findings"][a]["verdict"] for r in rows for a in ATTRS)
    reasons = Counter(r["fallback_reason"] for r in rows if r["fallback_reason"])
    n = len(rows)
    parse_fail = sum(c for k, c in reasons.items() if k in _PARSE_FAIL)
    result: dict[str, Any] = {
        "meta": {
            "preds_path": str(preds_path),
            "preds_sha256": _sha256(preds_path),
            "n_users": n,
            "n_posts": sum(len(r["post_ids"]) for r in rows),
            "n_test_posts": n_test,
            "measured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "code_commit": _git_commit(),
            "limit_users": limit_users,
        },
        "config": config_fingerprint(mode, adapter_dir),
        "verdict_distribution": dist,
        "verdict_overall": dict(overall),
        # rules 모드는 규칙이 본 판정이라 폴백이 없다 — 모델 모드에서만 의미가 있다
        "parse_failure_rate": (parse_fail / n if n else None) if mode == "model" else None,
        "fallback_rate": (sum(reasons.values()) / n if n else None) if mode == "model" else None,
        "fallback_reasons": {k: {"count": c, "rate": c / n} for k, c in reasons.most_common()},
        "seconds_per_user": _summary([r["seconds"] for r in rows]),
        "spans": {"in": sum(r["n_spans"] for r in rows), "dropped": sum(r["n_spans_dropped"] for r in rows),
                  "model_input": sum(r["n_spans_model_input"] for r in rows)},
        "out_file": str(out_dir / "stage2_preds.jsonl"),
    }
    (out_dir / "stage2_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


# ── 두 실행 비교 (ablation ④ 규칙 vs 모델) ─────────────────────────────

def _read_verdicts(path: Path) -> dict[str, dict[str, str]]:
    """stage2_preds.jsonl → {user_ref: {속성: verdict}}."""
    out: dict[str, dict[str, str]] = {}
    # 2단 결과 파일(user_ref · findings)이라 1단 예측 검증(read_preds)을 거치지 않는다
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        out[r["user_ref"]] = {a: r["findings"][a]["verdict"] for a in ATTRS}
    return out


def compare_stage2(a_path: str | Path, b_path: str | Path) -> dict[str, Any]:
    """두 stage2_preds.jsonl 을 user_ref × 속성으로 조인해 verdict 일치율을 낸다.

    분모 = 두 파일에 모두 있는 사용자 수 × 속성 7개. 한쪽에만 있는 사용자는 분모에서 빼고 수만 센다.
    정답과의 적중률이 아니라 **두 경로끼리의 일치율**이다.
    """
    a, b = _read_verdicts(Path(a_path)), _read_verdicts(Path(b_path))
    both = sorted(set(a) & set(b))
    per_attr = {at: sum(a[u][at] == b[u][at] for u in both) for at in ATTRS}
    n_pairs = len(both) * len(ATTRS)
    n_agree = sum(per_attr.values())
    return {
        "a": str(a_path), "b": str(b_path),
        "a_sha256": _sha256(Path(a_path)), "b_sha256": _sha256(Path(b_path)),
        "n_users_a": len(a), "n_users_b": len(b), "n_users_joined": len(both),
        "only_in_a": len(set(a) - set(b)), "only_in_b": len(set(b) - set(a)),
        "denominator": "조인된 사용자 × 속성 7개",
        "n_pairs": n_pairs, "n_agree": n_agree,
        "verdict_agreement": round(n_agree / n_pairs, 4) if n_pairs else None,
        "per_attr_agreement": {at: (round(c / len(both), 4) if both else None) for at, c in per_attr.items()},
    }


# ── exp09 회귀 명령 (실행은 d_downstream --final 만) ─────────────────────

def exp09_commands(config: str = "v2", adapter: str | Path | None = None) -> list[list[str]]:
    """exp09 외부 LLM 일치율을 그 구성으로 다시 재는 명령 — run_config.py(생성) → score.py(채점).

    run_config.py 는 출력(data/qwen_cfg_<config>.jsonl)이 이미 있으면 멈춘다(한 번만). 환경변수는
    ``EXP09_ENV``(PYTHONIOENCODING · HF_HUB_OFFLINE · PYTHONPATH) 를 함께 준다.
    """
    if config not in ("v1", "v2"):
        raise ValueError(f"config: {config!r} — v1 · v2")
    gen = [sys.executable, str(EXP09 / "run_config.py"), "--config", config]
    if adapter is not None:
        gen += ["--adapter", str(Path(adapter))]
    score = [sys.executable, str(EXP09 / "score.py"), "--qwen-file", f"qwen_cfg_{config}.jsonl",
             "--out", f"metrics_cfg_{config}.json"]
    return [gen, score]


def exp09_outputs(config: str = "v2") -> list[Path]:
    """exp09_commands 가 만드는 파일 3종 — [생성 jsonl · 생성 meta · 채점 metrics].

    meta(run_config.py) 와 metrics(score.py)는 실험 폴더에 고정 경로로 쓰이고, v2 의 두 파일은 git 추적 파일(DEC-012 근거)이다.
    생성 jsonl 은 .gitignore(data/*.jsonl). meta 의 어댑터 지문 필드는 ``adapter_sha256``(adapter_model.safetensors).
    """
    return [EXP09 / "data" / f"qwen_cfg_{config}.jsonl", EXP09 / "data" / f"qwen_cfg_{config}_meta.json",
            EXP09 / "results" / f"metrics_cfg_{config}.json"]


def exp09_config_files() -> dict[str, Path]:
    """run_config.py 가 meta 에 해시로 남기는 구성 파일 — meta 키 → 경로 (inputs.jsonl · external.jsonl · 둘 다 .gitignore)."""
    return {"inputs_sha256": EXP09 / "data" / "inputs.jsonl", "external_sha256": EXP09 / "data" / "external.jsonl"}


EXP09_ENV = {"PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1",
             "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)])}


# ── CLI ─────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="러너 2단 단계 (D) — 앱 경로로 사용자별 판정")
    ap.add_argument("--preds", type=Path, required=True, help="1단 예측 jsonl")
    ap.add_argument("--out", type=Path, required=True, help="출력 폴더 (stage2_preds.jsonl · stage2_summary.json)")
    ap.add_argument("--mode", choices=MODES, default="rules")
    ap.add_argument("--adapter", type=Path, help="mode=model 어댑터 폴더 (기본: STAGE2_ADAPTER_DIR · exp08 results/adapter_v2)")
    ap.add_argument("--post-ids", type=Path, help="이 글만 (json 목록 또는 {'post_ids': [...]})")
    ap.add_argument("--limit-users", type=int)
    ap.add_argument("--allow-test", action="store_true", help="test 글을 허용 (11/2 최종 측정)")
    ap.add_argument("--final", action="store_true",
                    help="최종 측정 — test 허용만 (exp09 는 실행하지 않는다 · d_downstream --final 에서만 돈다)")
    a = ap.parse_args(argv)

    post_ids = None
    if a.post_ids:
        d = json.loads(a.post_ids.read_text(encoding="utf-8"))
        post_ids = d["post_ids"] if isinstance(d, dict) else d
    res = run_stage2(a.preds, a.out, mode=a.mode, adapter=a.adapter, post_ids=post_ids,
                     limit_users=a.limit_users, allow_test=a.allow_test or a.final)
    print(json.dumps({k: res[k] for k in ("meta", "verdict_overall", "fallback_rate", "fallback_reasons",
                                          "parse_failure_rate", "seconds_per_user", "spans")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
