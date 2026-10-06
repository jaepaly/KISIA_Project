"""exp17 예측 — 1단 구성 하나로 평가셋 글의 스팬을 뽑아 score.py 형식으로 저장한다.

    # 체크포인트가 있는 곳(인스턴스 · B 데스크톱)에서
    PYTHONPATH="src;experiments/exp06-finetune" python experiments/exp17-planted-eval/predict.py \\
        --checkpoint <폴더> [--rules] --out preds_<이름>.jsonl
    # 체크포인트 없이 규칙만 (채점기 점검용)
    PYTHONPATH="src;experiments/exp06-finetune" python experiments/exp17-planted-eval/predict.py --rules-only --out preds_rules.jsonl

level·subject 는 kopl.c1_span.attributes 가 있으면 그것으로(#306), 없으면 임시값 implicit/self.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT / "src", ROOT / "experiments" / "exp06-finetune"):
    sys.path.insert(0, str(p))

try:
    from kopl.c1_span.attributes import resolve
except ImportError:  # #306 머지 전
    def resolve(texts, candidate):
        return {"level": "implicit", "subject": "self"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint")
    ap.add_argument("--rules", action="store_true", help="모델 후보에 명시 규칙 병합 (registry v1+규칙)")
    ap.add_argument("--rules-only", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.7)
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", default=str(HERE / "data" / "posts.jsonl"), help="평가셋 (exp17b 는 experiments/exp17b-heldout-eval/data/posts.jsonl)")
    a = ap.parse_args()

    import rules

    detector = None
    if not a.rules_only:
        import infer

        detector = infer.SpanDetector(Path(a.checkpoint), device="cpu", min_span_score=a.threshold)
    explicit = rules.ExplicitRules() if (a.rules or a.rules_only) else None

    with open(a.out, "w", encoding="utf-8") as f:
        for line in Path(a.data).open(encoding="utf-8"):
            post = json.loads(line)
            texts = post["texts"]
            if detector is not None:
                raw = detector.predict_raw({"post_id": post["post_id"], "body": texts["body"]})
                cands = raw["candidates"]
                if explicit is not None:
                    cands, _ = rules.merge_with_model(post["post_id"], raw["texts"], cands, explicit)
                texts = raw["texts"]
            else:
                cands = [{"text_id": "body", "start": s, "end": e, "text": texts["body"][s:e], "type": k,
                          "span_id": f"{post['post_id']}_r{i:02d}"}
                         for i, (s, e, k) in enumerate(sorted(explicit.predict_channel(texts["body"])))]
            spans = [{**c, **resolve(dict(texts), dict(c))} for c in cands]
            f.write(json.dumps({"post_id": post["post_id"], "spans": spans}, ensure_ascii=False) + "\n")
    print("saved", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
