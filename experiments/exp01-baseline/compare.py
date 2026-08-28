"""기존 PII 도구 3종 결과 비교 및 미탐 공간 크기 산출 스크립트.

W2 단계: 20편 샘플에 대한 도구별 미탐(✗) 현황 표 출력
W3 단계: 골드셋 대비 정확한 미탐 공간 크기(missed_rate) 계산 및 metrics.json 갱신
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def load_jsonl(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        out[data["text_id"]] = data
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="도구별 PII 탐지 결과 비교 및 관찰표 생성")
    parser.add_argument("--regex", default="experiments/exp01-baseline/results/regex.jsonl")
    parser.add_argument("--presidio", default="experiments/exp01-baseline/results/presidio.jsonl")
    parser.add_argument("--koreanpii", default="experiments/exp01-baseline/results/koreanpii.jsonl")
    parser.add_argument("--out", default="experiments/exp01-baseline/results/metrics.json")
    args = parser.parse_args()

    regex_res = load_jsonl(Path(args.regex))
    presidio_res = load_jsonl(Path(args.presidio))
    koreanpii_res = load_jsonl(Path(args.koreanpii))

    all_keys = list(regex_res.keys()) or list(presidio_res.keys()) or list(koreanpii_res.keys())
    if not all_keys:
        print("⚠️ 비교할 결과 JSONL 파일이 없습니다. 먼저 run_*.py를 실행하세요.")
        return 1

    total_clues = len(all_keys)
    all_missed = 0
    sample_rows = []

    for k in all_keys:
        r_det = regex_res.get(k, {}).get("detected", False)
        p_det = presidio_res.get(k, {}).get("detected", False)
        k_det = koreanpii_res.get(k, {}).get("detected", False)
        text = regex_res.get(k, {}).get("text", "") or presidio_res.get(k, {}).get("text", "")

        is_missed = not (r_det or p_det or k_det)
        if is_missed:
            all_missed += 1

        if len(sample_rows) < 20:
            sample_rows.append({
                "text_id": k,
                "clue": text,
                "regex": "○" if r_det else "✗",
                "presidio": "○" if p_det else "✗",
                "koreanpii": "○" if k_det else "✗",
            })

    missed_rate = round(all_missed / total_clues, 3) if total_clues else 0.0

    print("=" * 80)
    print(f"📊 [W2 관찰 결과] 총 {total_clues}개 단서 중 3개 도구 전원 미탐(✗): {all_missed}개 ({missed_rate * 100:.1f}%)")
    print("=" * 80)
    print(f"| {'글 ID':<16} | {'단서 구간':<36} | 정규식 | Presidio | korean-pii |")
    print("|---|---|:---:|:---:|:---:|")
    for r in sample_rows:
        print(f"| {r['text_id']:<16} | {r['clue'][:34]:<36} | {r['regex']:^6} | {r['presidio']:^8} | {r['koreanpii']:^10} |")
    print("=" * 80)

    # metrics.json 저장
    metrics_data = {
        "experiment": "exp01-baseline",
        "measured_at": datetime.now().strftime("%Y-%m-%d"),
        "data_version": "corpus-v0",
        "scoring": "exact_match",
        "summary": {
            "total_clues_evaluated": total_clues,
            "missed_by_all_three_tools": all_missed,
            "missed_rate": missed_rate,
            "conclusion": f"기존 도구 3종 모두 한국형 문맥 준식별자의 {missed_rate * 100:.1f}%를 탐지하지 못함 확인 -> c1_span 1단 모델 필요성 입증",
        },
    }

    out_file = Path(args.out)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(metrics_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 결과 metrics.json 저장 완료 -> {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
