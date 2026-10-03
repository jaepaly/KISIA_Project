"""exp12 입력 — 조치를 적용한 글 묶음을 교사 LLM 이 다시 읽을 수 있게 4조건으로 만든다.

    PYTHONIOENCODING=utf-8 python experiments/exp12-action-llm/build_inputs.py

- 표본: exp11 인물 10명 × w19 (created_at 순 앞 19편) — exp11 과 같은 글 묶음
- 조치: exp10 `run_persona` 를 **그 w19 안에서** 다시 돌린다 (exp10 의 전체 이력 결과를 쓰지 않는다)
  · 위험도 = C2 risk_total · 스팬 = 최상위 골드(검수 + 교사 라벨, exp11 과 같다) · 위치태그 = seed_sns.py
- 4조건 (누적)
  c0 기준 — 19편 전부 · 위치태그 포함
  c1 비공개 — LOO greedy 앞 k편을 뺀다 (k = exp10 unpublish_k)
  c2 + 활동 메타 — 남은 글의 위치태그를 뗀다
  c3 + 리라이트 — 남은 글의 명시 단서 스팬을 그 채널(text_id) 텍스트에서 지운다 (리라이터가 없어 삭제로 모사)
- 교사 입력은 exp11 과 같은 형식(post_id · created_at · texts)에 `geo_tag` 하나를 더한다.
  exp11 입력에는 위치태그가 없었으므로 c0 도 exp11 w19 와 같은 입력이 아니다 — 그래서 c0 부터 다시 부른다
- 모델 호출 없음. 결정적이다.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "src"
DATA = HERE / "data"
CONDITIONS = ("c0_baseline", "c1_unpublish", "c2_meta", "c3_rewrite")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"불러올 수 없다: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


exp10 = _load("exp10_build_inputs", ROOT / "experiments/exp10-action-repro/build_inputs.py")
exp11 = _load("exp11_run", ROOT / "experiments/exp11-risk-correlation/run.py")

WINDOW = max(exp11.WINDOWS)


def delete_spans(texts: dict[str, str], spans: list[dict]) -> tuple[dict[str, str], int]:
    """스팬을 채널별로 뒤에서부터 지운다. 오프셋이 원문과 안 맞으면 멈춘다."""
    out = dict(texts)
    by_channel: dict[str, list[dict]] = {}
    for span in spans:
        by_channel.setdefault(span["text_id"], []).append(span)
    removed = 0
    for text_id, items in by_channel.items():
        text = out.get(text_id)
        if text is None:
            raise SystemExit(f"채널 없음: {text_id}")
        for span in sorted(items, key=lambda s: s["start"], reverse=True):
            if text[span["start"]:span["end"]] != span["text"]:
                raise SystemExit(f"오프셋 불일치: {span['span_id']} {text_id}")
            before, after = text[:span["start"]], text[span["end"]:]
            # 지운 자리에 공백이 겹치면 하나로 — 이중 공백은 「여기서 뭔가 지웠다」는 흔적이 된다 (Codex 검토)
            if before.endswith(" ") and after.startswith(" "):
                after = after[1:]
            text = before + after
            removed += 1
        out[text_id] = text
    return out, removed


def teacher_posts(posts: dict, ids: list[str], *, tags: dict, keep_tags: bool,
                  rewrite: dict[str, list[dict]] | None = None) -> list[dict]:
    rows = []
    for pid in ids:  # created_at 순 그대로
        post = posts[pid]
        texts = {k: v for k, v in (post.get("texts") or {}).items() if isinstance(v, str) and v.strip()}
        if rewrite and pid in rewrite:
            texts, _ = delete_spans(texts, rewrite[pid])
            texts = {k: v for k, v in texts.items() if v.strip()}
        row = {"post_id": pid, "created_at": post.get("created_at"), "texts": texts}
        if keep_tags and tags.get(pid):
            row["geo_tag"] = tags[pid]
        rows.append(row)
    return rows


def main() -> int:
    eng = exp10.Engine(SRC)
    tags, geo_stats = exp10.seed_geo_tags()
    out_rows: list[dict] = []
    summary: list[dict] = []
    for persona in exp11.select_personas():
        ordered = exp11.load_posts(persona)[:WINDOW]
        ids = [p["post_id"] for p in ordered]
        by_id = {p["post_id"]: p for p in ordered}
        gold_rows = {}
        for row in exp11.read_jsonl(exp11.GOLD / f"{persona}_spans.jsonl"):
            if row.get("post_id") in by_id:
                gold_rows[row["post_id"]] = {**row, "persona_id": persona}
        built, _ = exp10.build_posts(eng, gold_rows, tags, {})
        ref = exp10.run_persona(eng, persona, built, ids)
        hidden = set(ref["actions"][0]["post_ids"])
        public = [pid for pid in ids if pid not in hidden]
        rewrite_rows = ref["actions"][2]["modes"][exp10.MAIN_REWRITE_MODE]["spans"]
        spans_by_key = {(pid, s["span_id"]): s for pid, g in gold_rows.items() for s in g.get("spans") or []}
        rewrite: dict[str, list[dict]] = {}
        for r in rewrite_rows:
            rewrite.setdefault(r["post_id"], []).append(spans_by_key[(r["post_id"], r["span_id"])])
        cum = ref["preview"]["cumulative"]
        risks = {
            "c0_baseline": cum["baseline"],
            "c1_unpublish": cum["after_unpublish"],
            "c2_meta": cum["after_meta"],
            "c3_rewrite": cum["after_rewrite"][exp10.MAIN_REWRITE_MODE],
        }
        inputs = {
            "c0_baseline": teacher_posts(by_id, ids, tags=tags, keep_tags=True),
            "c1_unpublish": teacher_posts(by_id, public, tags=tags, keep_tags=True),
            "c2_meta": teacher_posts(by_id, public, tags=tags, keep_tags=False),
            "c3_rewrite": teacher_posts(by_id, public, tags=tags, keep_tags=False, rewrite=rewrite),
        }
        for cond in CONDITIONS:
            out_rows.append({
                "persona_id": persona,
                "condition": cond,
                # exp11 run_teacher.build_user_prompt 의 window_id 가 이 값을 쓴다 — 4조건 모두 같게 둬 조건을 모델에 드러내지 않는다
                "window_size": WINDOW,
                "our_risk": risks[cond],
                "posts": inputs[cond],
            })
        summary.append({
            "persona_id": persona,
            "posts": len(ids),
            "hidden": sorted(hidden),
            "tagged_public": sum(1 for pid in public if tags.get(pid)),
            "rewrite_spans": len(rewrite_rows),
            "risk": risks,
        })
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / "inputs.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    manifest = {
        "rows": len(out_rows),
        "personas": len(summary),
        "window": WINDOW,
        "conditions": list(CONDITIONS),
        "rewrite_mode": exp10.MAIN_REWRITE_MODE,
        "unpublish_fraction": exp10.UNPUBLISH_FRACTION,
        "geo_tags": geo_stats,
        "repo_commit": commit,
        "inputs_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "per_persona": summary,
    }
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results/inputs_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for s in summary:
        r = s["risk"]
        print(f"{s['persona_id']} hide {len(s['hidden'])} · tags {s['tagged_public']} · rewrite {s['rewrite_spans']} · "
              f"risk {r['c0_baseline']} → {r['c1_unpublish']} → {r['c2_meta']} → {r['c3_rewrite']}")
    print(f"{len(out_rows)} rows → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
