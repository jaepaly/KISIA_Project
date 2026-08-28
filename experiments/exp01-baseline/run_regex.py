"""규칙 기반(정규식 8종) PII 탐지기 베이스라인.

형식이 고정된 표준 개인정보(전화번호, 주민번호, 이메일, 계좌번호 등)만 잡는 성능 하한선.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

PATTERNS = {
    "RRN": r"\b\d{6}[-\s]?[1-8]\d{6}\b",  # 주민등록번호
    "PHONE_MOB": r"\b01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}\b",  # 휴대전화
    "PHONE_TEL": r"\b0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4])[-\s.]?\d{3,4}[-\s.]?\d{4}\b",
    "EMAIL": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "CARD": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "BIZNO": r"\b\d{3}-\d{2}-\d{5}\b",  # 사업자등록번호
    "IP": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "ACCOUNT": r"\b\d{2,6}-\d{2,6}-\d{2,6}\b",  # ⚠️ 계좌번호(날짜 오탐 유발)
}


def detect(text: str) -> list[dict]:
    """문자열에서 정규식 패턴을 매칭하여 문자 offset 스팬을 반환한다."""
    out = []
    for typ, pat in PATTERNS.items():
        for m in re.finditer(pat, text):
            out.append(
                {
                    "start": m.start(),
                    "end": m.end(),
                    "text": m.group(),
                    "type": typ,
                    "score": 1.0,
                }
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="정규식 8종 PII 탐지기")
    parser.add_argument("--in", dest="input_path", default="data/corpus/v0/personas", help="입력 디렉터리 또는 파일")
    parser.add_argument("--out", dest="output_file", default="experiments/exp01-baseline/results/regex.jsonl", help="출력 JSONL 경로")
    args = parser.parse_args()

    in_path = Path(args.input_path)
    out_path = Path(args.output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # persona JSON 파일들 또는 jsonl 파일들 탐색
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
            spans = detect(text)
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

    print(f"✅ [Regex] {len(records)}건 검사 완료 -> {out_path} (탐지 성공 {sum(1 for r in records if r['detected'])}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
