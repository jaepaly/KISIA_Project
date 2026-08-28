"""한국어 개체명 인식기(spaCy ko_core_news_sm) 기반 PII 탐지기 베이스라인.

기존 공개 한국어 NER 모델이 일반 지명/인명 외의 문맥 결합형 준식별자(신갈저수지, 마흔여덟, 일산 작업실 등)를 놓치는 양상을 측정한다.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

try:
    import spacy
    _NLP = spacy.load("ko_core_news_sm")
except Exception:
    _NLP = None


def detect_korean_ner(text: str) -> list[dict]:
    """spaCy ko_core_news_sm 개체명 인식기를 돌려 문자 offset 스팬을 추출한다."""
    if _NLP is None:
        return []
    doc = _NLP(text)
    out = []
    for ent in doc.ents:
        out.append({
            "start": ent.start_char,
            "end": ent.end_char,
            "text": ent.text,
            "type": ent.label_,
            "score": 0.85,
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="한국어 spaCy NER 기반 PII 탐지기")
    parser.add_argument("--in", dest="input_path", default="data/corpus/v0/personas", help="입력 디렉터리 또는 파일")
    parser.add_argument("--out", dest="output_file", default="experiments/exp01-baseline/results/koreanpii.jsonl", help="출력 JSONL 경로")
    args = parser.parse_args()

    in_path = Path(args.input_path)
    out_path = Path(args.output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    engine_name = "spaCy ko_core_news_sm (Real NER)" if _NLP is not None else "spaCy ko_core_news_sm (Not Loaded)"

    files = sorted(glob.glob(str(in_path / "*.json"))) or sorted(glob.glob(str(in_path / "*.jsonl")))
    if in_path.is_file():
        files = [str(in_path)]

    records = []
    for f in files:
        pf = Path(f)
        try:
            data = json.loads(pf.read_text(encoding="utf-8-sig"))
        except Exception:
            continue

        pid = data.get("id", pf.stem)
        clue_plan = data.get("clue_plan", [])
        for c in clue_plan:
            text = c.get("clue", "")
            post = c.get("post", "")
            text_id = f"{pid}_{post}:{c.get('text_id', 'body')}"
            spans = detect_korean_ner(text)
            records.append({
                "persona_id": pid,
                "post_id": post,
                "text_id": text_id,
                "text": text,
                "spans": spans,
                "detected": len(spans) > 0,
            })

    with open(out_path, "w", encoding="utf-8") as fp:
        for r in records:
            fp.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"✅ [{engine_name}] {len(records)}건 검사 완료 -> {out_path} (개체 검출 {sum(1 for r in records if r['detected'])}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
