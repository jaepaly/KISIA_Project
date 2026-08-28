"""Microsoft Presidio Analyzer 기반 PII 탐지기 베이스라인.

글로벌 PII 탐지 표준 도구가 한국어 문맥형 준식별자에서 보이는 한계를 측정한다.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

# Presidio 라이브러리 가용성 확인
try:
    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    HAS_PRESIDIO = True
except ImportError:
    HAS_PRESIDIO = False


def build_analyzer():
    if not HAS_PRESIDIO:
        return None
    try:
        nlp_config = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "ko", "model_name": "ko_core_news_sm"}],
        }
        provider = NlpEngineProvider(nlp_configuration=nlp_config)
        nlp_engine = provider.create_engine()
        analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["ko"])
        # 한국어 모바일 번호 패턴 추가
        kr_phone = PatternRecognizer(
            supported_entity="PHONE_NUMBER",
            supported_language="ko",
            patterns=[Pattern(name="kr_mobile", regex=r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}", score=0.8)],
        )
        analyzer.registry.add_recognizer(kr_phone)
        return analyzer
    except Exception:
        try:
            return AnalyzerEngine(supported_languages=["ko", "en"])
        except Exception:
            return None


def detect_presidio_fallback(text: str) -> list[dict]:
    """Presidio 미설치 환경 또는 규칙 기반 폴백 탐지기."""
    out = []
    # Presidio 기본 제공 표준 엔티티 (Email, IP, Phone 등)
    patterns = {
        "EMAIL_ADDRESS": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "PHONE_NUMBER": r"\b01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}\b",
        "IP_ADDRESS": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "CREDIT_CARD": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    }
    for typ, pat in patterns.items():
        for m in re.finditer(pat, text):
            out.append({
                "start": m.start(),
                "end": m.end(),
                "text": m.group(),
                "type": typ,
                "score": 0.85,
            })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Microsoft Presidio PII 탐지기")
    parser.add_argument("--in", dest="input_path", default="data/corpus/v0/personas", help="입력 디렉터리 또는 파일")
    parser.add_argument("--out", dest="output_file", default="experiments/exp01-baseline/results/presidio.jsonl", help="출력 JSONL 경로")
    args = parser.parse_args()

    in_path = Path(args.input_path)
    out_path = Path(args.output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    analyzer = build_analyzer()
    engine_name = "Presidio Analyzer (Engine)" if analyzer else "Presidio Regex Recognizer Fallback"

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
            
            if analyzer:
                try:
                    res = analyzer.analyze(text=text, language="ko")
                    spans = [{"start": r.start, "end": r.end, "text": text[r.start:r.end], "type": r.entity_type, "score": r.score} for r in res]
                except Exception:
                    spans = detect_presidio_fallback(text)
            else:
                spans = detect_presidio_fallback(text)

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

    print(f"✅ [{engine_name}] {len(records)}건 검사 완료 -> {out_path} (탐지 성공 {sum(1 for r in records if r['detected'])}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
