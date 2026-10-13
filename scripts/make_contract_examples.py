"""계약 4종의 예시 JSON 을 앱 엔진으로 실제로 만들고 스키마와 대조한다 (README W9 D 11번 ② · E 성공 기준).

    PYTHONIOENCODING=utf-8 python scripts/make_contract_examples.py --checkpoint <1단 v2 폴더>

- 입력: 합성 코퍼스 v0 인물 E01 의 글 3편 (test 가 아닌 글 · 1단 출력이 골드와 같은 글 · 합성 데이터)
- 엔진: 앱과 같은 길 — ``apps/analyzer/engines/real.py`` (1단 v2 + 명시 규칙 · C2 k · C3 LOO · 2단 규칙 모드)
- 출력: ``docs/contracts/examples/{span,specificity,contribution,stage2-io}.example.json``
- 2단 입력(Stage2Input) 전체는 앱이 아직 만들지 않는다(real.stage2 는 요약만 넘긴다). 여기서는 같은 스팬을
  ``kopl.c4_stage2.anonymize`` 로 가명화해 계약 모양 그대로 조립한다. ``restore_key`` 는 비워 둔다 —
  지명 코드 · 시설 슬롯을 채우는 가명화기 출력 절이 아직 없다 (필드-대조표 §8 ①)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "docs" / "contracts"
OUT = CONTRACTS / "examples"
# test 가 아닌 짧은 글 중 1단 출력이 골드와 정확히 같은 글 — 예시가 오탐 스팬으로 계약을 잘못 보여 주지 않게
PERSONA = "E01"
POST_IDS = ["E01_b11", "E01_b19", "E01_b12"]


def load_posts() -> list[dict]:
    test = set(json.loads((ROOT / "data/corpus/v0/splits/test_post_ids.json").read_text(encoding="utf-8")))
    if test & set(POST_IDS):
        raise SystemExit("예시 글에 test 글이 섞였다")
    rows = {}
    for line in open(ROOT / f"data/corpus/v0/posts/{PERSONA}.jsonl", encoding="utf-8"):
        if line.strip():
            row = json.loads(line)
            rows[row["post_id"]] = row
    posts = []
    for pid in POST_IDS:
        texts = rows[pid]["texts"]
        post = {"post_id": pid, "title": texts.get("title"), "body": texts["body"]}
        caps = [texts[k] for k in sorted((k for k in texts if k.startswith("photo_caption:")),
                                         key=lambda k: int(k.split(":")[1]))]
        if caps:
            post["photo_captions"] = caps
        posts.append(post)
    return posts


def pseudonymize(record: dict, spans: list[dict], anonymize) -> tuple[list[dict], list[dict]]:
    """text_id 마다 가명화 → (TextSegment 목록, PseudonymEntry 목록)."""
    from engines.real import _texts

    segments, entries = [], []
    for tid, text in _texts(record).items():
        mine = sorted((s for s in spans if s["text_id"] == tid), key=lambda s: s["start"])
        anon, key = anonymize(text, mine)
        segments.append({"text_id": tid, "pseudonymized": anon})
        shift = 0
        for s in mine:
            pos = s["start"] + shift
            label = next(p for p, o in key.items() if o == s["text"] and anon.startswith(p, pos))
            entries.append({"span_id": s["span_id"], "text_id": tid, "label": label,
                            "original": {"start": s["start"], "end": s["end"]},
                            "pseudo": {"start": pos, "end": pos + len(label)}, "restore_key": {}})
            shift += len(label) - (s["end"] - s["start"])
    return segments, entries


def validate(doc: dict, schema_name: str, ref: str | None = None) -> None:
    import jsonschema

    schema = json.loads((CONTRACTS / schema_name).read_text(encoding="utf-8"))
    if ref:
        schema = {"$defs": schema["$defs"], "$ref": ref}
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(doc)


def check_links(span_docs: dict, contr_doc: dict, stage2_doc: dict) -> None:
    """스키마가 못 잡는 값끼리의 맞물림 — 계약 $comment 의 불변식과 문서 사이 참조."""
    out = contr_doc["output"]
    for c in out["contributions"]:  # contribution 불변식 (3)
        if abs(c["risk_without"] - (out["baseline_risk"] + c["delta"])) > 1e-9:
            raise SystemExit(f"risk_without ≠ baseline_risk + delta: {c}")
    span_ids = {s["span_id"] for d in span_docs.values() for s in d["spans"]}
    for post in stage2_doc["input"]["posts"]:
        texts = {t["text_id"]: t["pseudonymized"] for t in post["texts"]}
        for e in post["pseudonym_map"]:
            if texts[e["text_id"]][e["pseudo"]["start"]:e["pseudo"]["end"]] != e["label"]:
                raise SystemExit(f"pseudo offset 이 가명 텍스트와 안 맞는다: {e}")
    for f in stage2_doc["output"]["findings"].values():
        for ev in f["evidence"]:
            if ev["span_id"] not in span_ids:
                raise SystemExit(f"evidence 가 없는 span_id 를 가리킨다: {ev}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True, help="1단 v2 체크포인트 폴더")
    a = ap.parse_args()
    os.environ["C1_CHECKPOINT_DIR"] = a.checkpoint
    os.environ["STAGE2_MODE"] = "rules"  # 예시는 GPU 없이도 같은 값이 나오게
    sys.path.insert(0, str(ROOT / "apps" / "analyzer"))
    sys.path.insert(0, str(ROOT / "src"))
    from engines import real
    from kopl.c4_stage2.anonymize import anonymize

    posts = load_posts()
    user_ref = "u_" + hashlib.sha256(PERSONA.encode()).hexdigest()[:12]

    spans_by_post = {p["post_id"]: real.detect_spans(p) for p in posts}
    span_doc = spans_by_post[POST_IDS[0]]

    conds = real.conditions(posts, spans_by_post)
    spec_doc = real.specificity({"user_ref": user_ref, "conditions": conds})
    contr_doc = real.contribution(user_ref, posts, spans_by_post=spans_by_post)

    records = {p["post_id"]: {k: p[k] for k in ("post_id", "title", "body", "photo_captions") if p.get(k)}
               for p in posts}
    s2 = real.stage2(user_ref, posts)
    delta = {c["post_id"]: c["delta"] for c in contr_doc["output"]["contributions"]}
    in_posts = []
    for p in posts:
        pid = p["post_id"]
        spans = spans_by_post[pid]["spans"]
        segments, pmap = pseudonymize(records[pid], spans, anonymize)
        item = {"post_id": pid, "texts": segments, "spans": spans, "pseudonym_map": pmap,
                "contribution": min(0.0, delta.get(pid, 0.0))}
        in_posts.append(item)
    output = s2["output"]
    stage2_doc = {
        "input": {"schema_version": "0.1.0", "user_ref": user_ref, "posts": in_posts,
                  "risk": {"current": output["recommendation"]["projected"]["current_risk"],
                           "target": s2["input"]["risk"]["target"]},
                  "provenance": {"measured_at": output["provenance"]["measured_at"],
                                 "model_version": span_doc["model_version"],
                                 "dict_version": spec_doc["dict_version"], "data_version": "corpus-v0"}},
        "output": output,
    }

    docs = {"span": (span_doc, "span.schema.json", None),
            "specificity": (spec_doc, "specificity.schema.json", None),
            "contribution": (contr_doc, "contribution.schema.json", None),
            "stage2-io": (stage2_doc, "stage2-io.schema.json", None)}
    check_links(spans_by_post, contr_doc, stage2_doc)
    OUT.mkdir(exist_ok=True)
    for name, (doc, schema, ref) in docs.items():
        validate(doc, schema, ref)
        path = OUT / f"{name}.example.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"통과 {schema} ← {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
