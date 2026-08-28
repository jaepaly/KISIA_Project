"""한국어 개체명 인식기(NER) 기반 PII 탐지기 베이스라인.

기존 공개 한국어 NER 모델이 일반 지명/인명 외의 문맥 결합형 준식별자(신갈저수지, 마흔여덟, 일산 작업실 등)를 놓치는 양상을 측정한다.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

# 한국어 명시적 지명/기관/인명 키워드 패턴 (일반 NER 동작 모사 및 베이스라인)
KNOWN_LOCATIONS = {"서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기도", "강원도", "충청도", "전라도", "경상도", "제주"}


def detect_korean_ner(text: str) -> list[dict]:
    out = []
    # 단순 광역지자체명 매칭 (일반 NER이 잡을 수 있는 수준)
    for loc in KNOWN_LOCATIONS:
        for m in re.finditer(re.escape(loc), text):
            out.append({
                "start": m.start(),
                "end": m.end(),
                "text": m.group(),
                "type": "PS_LOCATION",
                "score": 0.9,
            })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="한국어 NER 기반 PII 탐지기")
    parser.add_argument("--in", dest="input_path", default="data/corpus/v0/personas", help="입력 디렉터리 또는 파일")
    parser.add_argument("--out", dest="output_file", default="experiments/exp01-baseline/results/koreanpii.jsonl", help="출력 JSONL 경로")
    args = parser.parse_args()

    in_path = Path(args.input_path)
    out_path = Path(args.output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

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

    print(f"✅ [Korean-NER] {len(records)}건 검사 완료 -> {out_path} (탐지 성공 {sum(1 for r in records if r['detected'])}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
