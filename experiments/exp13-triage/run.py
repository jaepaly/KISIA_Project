"""exp13 triage — 2단에 보낼 글을 줄여도 판정이 유지되는가.

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp13-triage/run.py --n 30          # GPU (Qwen3-4B + v1 어댑터)
    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp13-triage/run.py --rules-only    # 규칙·토큰만 (GPU 없이)

- 표본: 최상위 골드가 인물의 모든 글을 덮는 인물(전체 이력) — 글이 많아야 triage 가 의미 있다
- 스팬: 골드 본인(self) 스팬 (1단 오차가 빠진 조건 — 한계)
- 정책
  all  : 모든 글
  span : 본인 스팬이 1개 이상인 글 (계약 triage_reason span_density)
  anchor: 속성마다 판정을 정하는 글만 — 가장 높은 수준의 본인 스팬이 있는 글 1편,
          그 수준이 inferential 이면 서로 다른 글 2편 (#279 판정 기준상 규칙 판정이 그대로 남는 최소 집합)
- 비용: 2단 system + user prompt 내용의 Qwen 토큰 수 (chat template 의 역할 토큰은 빼고 센다 — 정책 간 비교용) (+ 참고: 같은 글의 원문 토큰 수 — LLM 이 원문을 읽는 방식이었다면)
- 놓침: all 의 판정 대비 — 비기권 속성 중 같은 verdict 로 남은 비율(재현율) · 기권이 아니게 된 칸(새로 생긴 판정)
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from kopl.c4_stage2.infer import (SYSTEM_V1, Stage2Model, build_user_prompt, parse_findings,
                                  validate_findings)
from kopl.c4_stage2.rules import ATTRS, TYPE_TO_ATTR, findings_from_spans

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GOLD = ROOT / "data/corpus/v0/gold"
POSTS = ROOT / "data/corpus/v0/posts"
RANK = {"explicit": 3, "implicit": 2, "inferential": 1}
POLICIES = ("all", "span", "anchor")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8-sig").splitlines() if l.strip()]


def load_personas() -> dict[str, list[dict]]:
    """인물 → [{post_id, texts, spans(self)}] — 골드가 모든 글을 덮는 인물만."""
    out = {}
    for g in sorted(GOLD.glob("[A-E]*_spans.jsonl")):
        pid = g.stem.replace("_spans", "")
        path = POSTS / f"{pid}.jsonl"
        if not path.exists():
            continue
        gold = {r["post_id"]: r for r in read_jsonl(g) if r.get("post_id")}
        posts = {r["post_id"]: r for r in read_jsonl(path)}
        if set(gold) != set(posts):
            continue
        out[pid] = [{
            "post_id": k,
            "texts": {t: v for t, v in (posts[k].get("texts") or {}).items() if isinstance(v, str) and v},
            "spans": [s for s in gold[k].get("spans") or []
                      if s.get("subject") == "self" and s.get("level") in RANK],
        } for k in sorted(posts)]
    return out


def select(posts: list[dict], policy: str) -> list[dict]:
    if policy == "all":
        return posts
    if policy == "span":
        return [p for p in posts if p["spans"]]
    keep: set[str] = set()
    for attr in ATTRS:
        cands = [(RANK[s["level"]], p["post_id"]) for p in posts for s in p["spans"]
                 if TYPE_TO_ATTR.get(s["type"]) == attr]
        if not cands:
            continue
        top = max(r for r, _ in cands)
        ids = sorted({k for r, k in cands if r == top})
        keep.update(ids[:2] if top == RANK["inferential"] else ids[:1])
    return [p for p in posts if p["post_id"] in keep]


def compare(full: dict, tri: dict) -> dict:
    pos = [a for a in ATTRS if full[a]["verdict"] != "abstain"]
    return {
        "nonabstain": len(pos),
        "kept_same": sum(tri[a]["verdict"] == full[a]["verdict"] for a in pos),
        "lost_to_abstain": sum(tri[a]["verdict"] == "abstain" for a in pos),
        "agree_all": sum(tri[a]["verdict"] == full[a]["verdict"] for a in ATTRS),
        "new_nonabstain": sum(full[a]["verdict"] == "abstain" and tri[a]["verdict"] != "abstain" for a in ATTRS),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30, help="GPU 로 돌릴 인물 수 (무작위)")
    ap.add_argument("--seed", type=int, default=20261004)
    ap.add_argument("--rules-only", action="store_true")
    ap.add_argument("--max-new", type=int, default=1600,
                    help="생성 한도 — 전체 이력은 답(근거 목록)이 700 토큰을 넘어 잘린다 (10/4 첫 실행: all 6/12 파싱 실패)")
    ap.add_argument("--batch", type=int, default=5, help="한 번 실행에 새로 돌릴 인물 수 — 메모리 부족 중단 대비")
    a = ap.parse_args()

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-4B", local_files_only=True)
    ntok = lambda s: len(tok(s)["input_ids"])  # noqa: E731
    personas = load_personas()
    rows = []
    for pid, posts in personas.items():
        ref = "u_" + pid.lower().encode().hex()[:8].ljust(8, "0")
        row = {"persona_id": pid, "posts": len(posts)}
        for pol in POLICIES:
            sub = select(posts, pol)
            prompt, entries = build_user_prompt(ref, sub)
            row[pol] = {
                "posts": len(sub),
                "prompt_tokens": ntok(SYSTEM_V1) + ntok(prompt),
                "text_tokens": sum(ntok(" ".join(p["texts"].values())) for p in sub),
                "rules": findings_from_spans(entries),
                "prompt": prompt,
                "entries": entries,
            }
        rows.append(row)

    model_ids = set()
    if not a.rules_only:
        model_ids = set(random.Random(a.seed).sample(sorted(personas), min(a.n, len(personas))))
        # 인물 하나가 끝날 때마다 저장한다 — 중간에 멈춰도 다시 실행하면 끝난 인물은 건너뛴다
        runs_path = HERE / f"results/model_runs_mx{a.max_new}.jsonl"
        runs_path.parent.mkdir(exist_ok=True)
        done = {}
        if runs_path.exists():
            for rec in read_jsonl(runs_path):
                done[rec["persona_id"]] = rec
        todo = [r for r in rows if r["persona_id"] in model_ids and r["persona_id"] not in done][:a.batch]
        model = Stage2Model(max_new_tokens=a.max_new) if todo else None
        with runs_path.open("a", encoding="utf-8") as f:
            for row in todo:
                rec = {"persona_id": row["persona_id"]}
                for pol in POLICIES:
                    t0 = time.time()
                    raw = model.generate(row[pol]["prompt"])
                    rec[pol] = {"model": validate_findings(parse_findings(raw), row[pol]["entries"]),
                                "sec": round(time.time() - t0, 1)}
                    print(row["persona_id"], pol, "ok" if rec[pol]["model"] else "INVALID", rec[pol]["sec"], flush=True)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                done[row["persona_id"]] = rec
        # 지금 표본(seed · n)에 든 인물만 집계한다 — 다른 설정으로 돌린 결과가 같은 파일에 있어도 섞이지 않게
        done = {k: v for k, v in done.items() if k in model_ids}
        for row in rows:
            if row["persona_id"] in done:
                for pol in POLICIES:
                    row[pol].update(done[row["persona_id"]][pol])

    def agg(key: str, ids: set[str] | None = None) -> dict:
        sel = [r for r in rows if ids is None or r["persona_id"] in ids]
        res = {}
        for pol in POLICIES:
            res[pol] = {
                "posts": sum(r[pol]["posts"] for r in sel),
                "prompt_tokens": sum(r[pol]["prompt_tokens"] for r in sel),
                "text_tokens": sum(r[pol]["text_tokens"] for r in sel),
            }
        for pol in ("span", "anchor"):
            res[pol]["prompt_token_cut_pct"] = round(100 * (1 - res[pol]["prompt_tokens"] / res["all"]["prompt_tokens"]), 1)
            res[pol]["text_token_cut_pct"] = round(100 * (1 - res[pol]["text_tokens"] / res["all"]["text_tokens"]), 1)
            if key:
                valid = [r for r in sel if r["all"].get(key) and r[pol].get(key)]
                c = [compare(r["all"][key], r[pol][key]) for r in valid]
                tot = {k: sum(x[k] for x in c) for k in ("nonabstain", "kept_same", "lost_to_abstain", "agree_all", "new_nonabstain")}
                tot["personas_valid"] = len(valid)
                tot["recall"] = round(tot["kept_same"] / tot["nonabstain"], 4) if tot["nonabstain"] else None
                tot["agreement_7attr"] = round(tot["agree_all"] / (7 * len(valid)), 4) if valid else None
                res[pol][key] = tot
        return res

    out = {
        "personas": len(rows),
        "spans": "gold self spans (1단 오차 제외)",
        "rules_all_personas": agg("rules"),
    }
    if model_ids:
        out["model_subset"] = {"personas": sorted(model_ids), "seed": a.seed, "max_new_tokens": a.max_new,
                               "personas_done": len(done),
                               "rules": agg("rules", set(done)), "model": agg("model", set(done))}
        out["model_subset"]["invalid"] = sum(1 for r in rows if r["persona_id"] in done
                                             for pol in POLICIES if r[pol].get("model") is None)
        out["model_subset"]["sec_mean"] = {pol: round(sum(r[pol]["sec"] for r in rows if r["persona_id"] in done)
                                                      / max(1, len(done)), 1) for pol in POLICIES}
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results/metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "model_subset"}, ensure_ascii=False)[:1500])
    if model_ids:
        print(json.dumps(out["model_subset"]["model"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
