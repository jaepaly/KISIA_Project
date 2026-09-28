"""exp09 입력 — test 239편을 인물별 v1 SFT 추론 입력으로 묶고, 규칙 타깃·층·해시를 함께 쓴다.

    python experiments/exp09-external-agreement/build_inputs.py [--pilot 5]

- 글 선정은 exp06 evaluate_test.py 와 같다: test split − 옛 IAA 16편, clue 는 blind 검수본 · noise 는 최상위 검수본
- 입력 형태는 Qwen v1 이 학습한 그대로 ({user_ref, profile: null, posts: [{post_id, spans}]}) — 계약 Stage2Input 이 아니다
- body 스팬만 쓴다 (v1 은 body 만 학습). 빠진 title·photo_caption 스팬 수는 manifest 에 남긴다
- system 프롬프트는 v1_train.jsonl 첫 예시의 것 (소스의 현재 SYSTEM 이 아니라 실제 학습본)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP06 = ROOT / "experiments/exp06-finetune"
EXP08 = ROOT / "experiments/exp08-stage2-sft"
sys.path[:0] = [str(ROOT / "src"), str(EXP06), str(EXP08)]

import evaluate_test as ev  # noqa: E402
import make_sft_v1 as sft  # noqa: E402

CORPUS = ROOT / "data/corpus/v0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_posts() -> tuple[dict[str, dict], dict[str, dict]]:
    """evaluate_test.prepare() 의 선정·골드 규칙 (BIO 누수 검사는 1단 몫이라 뺀다)."""
    tests = ev.index_posts(ev.records(CORPUS / "splits/test.jsonl"))
    assignment = json.loads((CORPUS / "gold/iaa/_assignment.json").read_text(encoding="utf-8-sig"))
    excluded = ev.legacy_iaa_ids(assignment, tests)
    selected = {pid: row for pid, row in tests.items() if pid not in excluded}
    gold: dict[str, dict] = {}
    for source, pattern in (("blind", "gold/blind/*_spans.jsonl"), ("reviewed", "gold/*_spans.jsonl")):
        for path in sorted(CORPUS.glob(pattern)):
            for row in ev.records(path):
                pid = row.get("post_id")
                if pid not in selected or row.get("reviewed") is not True or pid in gold:
                    continue
                kind = selected[pid]["kind"]
                if (kind == "clue" and source == "blind") or (kind == "noise" and source == "reviewed"):
                    gold[pid] = row
    missing = set(selected) - set(gold)
    if missing:
        raise SystemExit(f"골드 없는 글: {sorted(missing)[:5]} …")
    return selected, gold


def train_refs() -> set[str]:
    """v1_train 에 나온 인물 (학습 당시 user_ref 자릿수 그대로 비교)."""
    refs = set()
    for line in (EXP08 / "data/v1_train.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            refs.add(json.loads(json.loads(line)["messages"][1]["content"])["user_ref"])
    return refs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "data"))
    ap.add_argument("--pilot", type=int, default=5, help="파일럿 인물 수 (인물 id 순 앞에서)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    first = json.loads((EXP08 / "data/v1_train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    system = first["messages"][0]["content"]
    seen_refs = train_refs()
    ref_len = len(next(iter(seen_refs)))

    selected, gold = select_posts()
    by_persona: dict[str, list[str]] = {}
    for pid in sorted(selected):
        by_persona.setdefault(selected[pid]["persona_id"], []).append(pid)

    dropped = Counter()
    rows = []
    for persona, post_ids in sorted(by_persona.items()):
        posts, pairs = [], []
        for pid in post_ids:
            g = gold[pid]
            for s in g["spans"]:
                if s["text_id"] != "body":
                    dropped[s["text_id"].split(":")[0]] += 1
            body_spans = [s for s in g["spans"] if s["text_id"] == "body"]
            _, _, tokenized = sft.anonymize_post(g["texts"].get("body", ""), body_spans)
            if len(tokenized) != len(body_spans):
                raise SystemExit(f"{pid}: 가명화 후 스팬 수가 달라짐 {len(body_spans)} → {len(tokenized)}")
            posts.append({"post_id": pid, "spans": tokenized})
            pairs.append((pid, tokenized))
        user_ref = sft.user_ref(persona)
        rows.append({
            "persona_id": persona,
            "seen_in_sft": ("u_" + hashlib.sha256(persona.encode()).hexdigest()[: ref_len - 2]) in seen_refs,
            "kinds": dict(Counter(selected[p]["kind"] for p in post_ids)),
            "system": system,
            "user": json.dumps({"user_ref": user_ref, "profile": None, "posts": posts}, ensure_ascii=False),
            "rule_target": sft.findings_from_spans(pairs),
        })

    with (out / "inputs.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "pilot_ids.json").write_text(json.dumps([r["persona_id"] for r in rows[: a.pilot]]), encoding="utf-8")

    adapter = EXP08 / "results/adapter"
    manifest = {
        "posts": len(selected),
        "kinds": dict(Counter(r["kind"] for r in selected.values())),
        "personas": len(rows),
        "seen_in_sft": sum(r["seen_in_sft"] for r in rows),
        "cells": len(rows) * len(sft.ATTRS),
        "body_spans": sum(len(json.loads(r["user"])["posts"][i]["spans"]) for r in rows for i in range(len(json.loads(r["user"])["posts"]))),
        "dropped_non_body_spans": dict(dropped),
        "system_prompt_sha256": hashlib.sha256(system.encode()).hexdigest(),
        "sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in [
            CORPUS / "splits/test.jsonl", CORPUS / "gold/iaa/_assignment.json",
            EXP08 / "data/v1_train.jsonl", EXP08 / "data/v1_dev.jsonl",
            *sorted(adapter.glob("adapter_*")),
        ]},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("posts", "kinds", "personas", "seen_in_sft", "cells", "body_spans", "dropped_non_body_spans")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
