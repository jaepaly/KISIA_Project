"""#293 민감도 분석 입력 — C 가 고정한 190편(post_ids_293.txt)에 1단 v1 예측 2종을 만든다.

    PYTHONPATH="src;experiments/exp06-finetune" python experiments/exp11-risk-correlation/inputs/predict_293.py \\
        --checkpoint <v1_lr5e-5/checkpoint-epoch-10 폴더>

- v1 단독: 등록 v1 · 임계값 0.7 · 채널 title · body · photo_caption:N
- v1 + 규칙: 같은 v1 후보에 rules.merge_with_model(ExplicitRules) — 실행 시점 main 의 규칙(#290 + #309 · #312)
- 출력: 줄마다 {"post_id", "candidates": [{text_id, start, end, type}]} · 190편 전부(탐지 없으면 빈 목록)
- level · subject 는 넣지 않는다 — C 가 #306 resolve() 로 붙인다 (#293 (나))
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for p in (ROOT / "src", ROOT / "experiments" / "exp06-finetune"):
    sys.path.insert(0, str(p))

import infer  # noqa: E402
import rules  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--out-dir", type=Path, default=HERE)
    a = ap.parse_args()

    ids = [line.strip() for line in (HERE / "post_ids_293.txt").open(encoding="utf-8") if line.strip()]
    assert len(ids) == 190 == len(set(ids)), len(ids)
    posts = {}
    for pers in sorted({i.split("_")[0] for i in ids}):
        for line in (ROOT / "data" / "corpus" / "v0" / "posts" / f"{pers}.jsonl").open(encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                posts[r["post_id"]] = r
    missing = [i for i in ids if i not in posts]
    assert not missing, missing

    detector = infer.SpanDetector(a.checkpoint, device="cpu", min_span_score=0.7)
    explicit = rules.ExplicitRules()
    with open(a.out_dir / "pred293_v1.jsonl", "w", encoding="utf-8", newline="\n") as f1, \
            open(a.out_dir / "pred293_v1_rules.jsonl", "w", encoding="utf-8", newline="\n") as f2:
        for pid in ids:
            t = posts[pid]["texts"]
            caps = [t[k] for k in sorted((k for k in t if k.startswith("photo_caption:")),
                                         key=lambda k: int(k.split(":")[1]))]
            raw = detector.predict_raw({"post_id": pid, "title": t.get("title") or "", "body": t["body"],
                                        "photo_captions": caps})
            merged, _ = rules.merge_with_model(pid, raw["texts"], raw["candidates"], explicit)
            for f, cs in ((f1, raw["candidates"]), (f2, merged)):
                f.write(json.dumps({"post_id": pid, "candidates": [
                    {"text_id": x["text_id"], "start": x["start"], "end": x["end"], "type": x["type"]} for x in cs]},
                    ensure_ascii=False) + "\n")
    print("saved", a.out_dir / "pred293_v1.jsonl", a.out_dir / "pred293_v1_rules.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
