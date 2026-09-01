"""기존 PII 도구 3종 결과 비교, 등급별 미탐 공간 및 LLM 도달 가능성 산출 스크립트.

W2 단계: 20편 샘플에 대한 도구별 미탐(✗) 현황 표 출력
W3 단계: 골드셋 대비 등급별(explicit/implicit/inferential) 미탐 공간(missed_rate) 및
        LLM 상한 도달 가능성(reachability) 산출, W3 중단 기준(Gate) 판정 및 metrics.json 갱신

스팬 매칭 규칙 (README 정본 · label-schema §2):
  - 주 지표: partial match (유형 일치 + IoU >= 0.5)
  - 부 지표: exact match (시작/끝 인덱스 완전 일치)
  - 3종 합집합: 3개 도구(regex, presidio, koreanpii) 중 하나라도 탐지하면 탐지 성공
  - W3 게이트:
      미탐 공간:   implicit >= 45% AND inferential >= 45%
      도달 가능성: implicit >= 60% AND inferential >= 60%
      판정: 둘 다 충족시 PASS · 하나만 충족시 PENDING · 둘 다 미달시 STOP
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime
from pathlib import Path

# Windows 콘솔 출력 UTF-8 안전 처리
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def compute_iou(s1: int, e1: int, s2: int, e2: int) -> float:
    """두 문자 오프셋 스팬 구간의 IoU(Intersection over Union)를 계산한다."""
    inter = max(0, min(e1, e2) - max(s1, s2))
    union = (e1 - s1) + (e2 - s2) - inter
    return inter / union if union > 0 else 0.0


def load_jsonl(path: Path) -> dict[str, dict]:
    """JSONL 파일을 읽어 text_id, id, text를 키로 하는 매핑 딕셔너리를 반환한다."""
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if "text_id" in data:
            out[str(data["text_id"])] = data
        if "id" in data:
            out[str(data["id"])] = data
        if "text" in data:
            out[str(data["text"])] = data
    return out


def load_clues(path: Path) -> list[dict]:
    """골드셋 clues.jsonl 또는 spans.jsonl 파일을 로드한다."""
    if not path.is_file():
        return []
    clues = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        clues.append(json.loads(line))
    return clues


def is_detected_span(gold: dict, tool_record: dict, mode: str = "partial") -> bool:
    """골드 단서가 도구의 탐지 결과에 매칭되는지 판정한다.
    
    - partial match: IoU >= 0.5 (주 지표)
    - exact match: start == start and end == end (부 지표)
    - 스팬 정보가 없을 경우: tool_record['detected'] boolean 폴백
    """
    if not tool_record:
        return False

    tool_spans = tool_record.get("spans", [])
    if not tool_spans:
        return bool(tool_record.get("detected", False))

    gold_start = gold.get("start")
    gold_end = gold.get("end")

    # 골드셋에 start/end가 있는 경우 정밀 IoU 매칭
    if gold_start is not None and gold_end is not None:
        for ts in tool_spans:
            t_start = ts.get("start", 0)
            t_end = ts.get("end", 0)
            if mode == "exact":
                if gold_start == t_start and gold_end == t_end:
                    return True
            else:  # partial (IoU >= 0.5)
                iou = compute_iou(gold_start, gold_end, t_start, t_end)
                if iou >= 0.5:
                    return True
        return False

    # 골드셋이 문장 단위(clues.jsonl)인 경우: 도구가 스팬을 1개 이상 탐지했으면 True
    return len(tool_spans) > 0 or bool(tool_record.get("detected", False))


def main() -> int:
    parser = argparse.ArgumentParser(description="PII 도구 3종 베이스라인 미탐 공간 및 LLM 도달 가능성 비교 산출")
    parser.add_argument("--clues", default="experiments/exp01-baseline/clues.jsonl", help="골드 단서 파일 (clues.jsonl 또는 gold spans)")
    parser.add_argument("--regex", default="experiments/exp01-baseline/results/regex.jsonl", help="Regex 결과 JSONL")
    parser.add_argument("--presidio", default="experiments/exp01-baseline/results/presidio.jsonl", help="Presidio 결과 JSONL")
    parser.add_argument("--koreanpii", default="experiments/exp01-baseline/results/koreanpii.jsonl", help="Korean PII 결과 JSONL")
    parser.add_argument("--llm", default="experiments/exp01-baseline/results/gemini.jsonl", help="LLM 상한선 결과 JSONL (선택사항)")
    parser.add_argument("--out", default="experiments/exp01-baseline/results/metrics.json", help="출력 metrics.json 경로")
    parser.add_argument("--scoring", default="partial_match", choices=["partial_match", "exact_match"], help="주 채점 방식")
    args = parser.parse_args()

    clues_list = load_clues(Path(args.clues))
    regex_res = load_jsonl(Path(args.regex))
    presidio_res = load_jsonl(Path(args.presidio))
    koreanpii_res = load_jsonl(Path(args.koreanpii))
    llm_res = load_jsonl(Path(args.llm))

    # 1. 합집합 키 수집 (버그 수정: or 단축평가 제거, set union 적용)
    all_keys = set(regex_res.keys()) | set(presidio_res.keys()) | set(koreanpii_res.keys())
    if clues_list:
        for c in clues_list:
            key = c.get("text_id") or c.get("id") or c.get("text", "")
            all_keys.add(key)

    if not all_keys:
        print("⚠️ 비교할 결과 JSONL 또는 단서 파일이 없습니다.")
        return 1

    # 골드셋 리스트 구성 (clues_list가 없으면 결과 파일의 텍스트 기반으로 생성)
    items = []
    if clues_list:
        items = clues_list
    else:
        for k in sorted(all_keys):
            text = (
                regex_res.get(k, {}).get("text", "")
                or presidio_res.get(k, {}).get("text", "")
                or koreanpii_res.get(k, {}).get("text", "")
            )
            items.append({"id": k, "text_id": k, "text": text, "level": "implicit"})

    # 2. 등급별 집계 카운터 초기화
    levels = ["explicit", "implicit", "inferential"]
    gold_counts = collections.Counter()
    missed_counts_partial = collections.Counter()
    missed_counts_exact = collections.Counter()
    llm_recovers_counts = collections.Counter()

    sample_rows = []

    for item in items:
        key = item.get("text_id") or item.get("id") or item.get("text", "")
        level = item.get("level", "implicit")
        if level not in levels:
            level = "implicit"
        gold_counts[level] += 1

        r_rec = regex_res.get(key) or regex_res.get(item.get("text", ""))
        p_rec = presidio_res.get(key) or presidio_res.get(item.get("text", ""))
        k_rec = koreanpii_res.get(key) or koreanpii_res.get(item.get("text", ""))
        l_rec = llm_res.get(key) or llm_res.get(item.get("text", ""))

        # Partial Match (IoU >= 0.5) 판정
        r_det_p = is_detected_span(item, r_rec, mode="partial")
        p_det_p = is_detected_span(item, p_rec, mode="partial")
        k_det_p = is_detected_span(item, k_rec, mode="partial")
        missed_partial = not (r_det_p or p_det_p or k_det_p)

        # Exact Match 판정
        r_det_e = is_detected_span(item, r_rec, mode="exact")
        p_det_e = is_detected_span(item, p_rec, mode="exact")
        k_det_e = is_detected_span(item, k_rec, mode="exact")
        missed_exact = not (r_det_e or p_det_e or k_det_e)

        if missed_partial:
            missed_counts_partial[level] += 1
            # LLM이 미탐된 단서를 복구(탐지)했는지 확인
            if l_rec and is_detected_span(item, l_rec, mode="partial"):
                llm_recovers_counts[level] += 1

        if missed_exact:
            missed_counts_exact[level] += 1

        # 관찰표용 샘플 (20건)
        if len(sample_rows) < 20:
            sample_rows.append({
                "id": item.get("id") or key,
                "clue": item.get("text", "") or item.get("clue", ""),
                "level": level,
                "regex": "○" if r_det_p else "✗",
                "presidio": "○" if p_det_p else "✗",
                "koreanpii": "○" if k_det_p else "✗",
                "llm": ("○" if is_detected_span(item, l_rec, mode="partial") else "✗") if l_rec else "-",
            })

    total_gold = sum(gold_counts.values())
    total_missed_partial = sum(missed_counts_partial.values())
    total_missed_exact = sum(missed_counts_exact.values())
    total_llm_recovers = sum(llm_recovers_counts.values())

    # 3. 등급별 지표 계산
    by_level = {}
    for lv in levels:
        g = gold_counts[lv]
        m_p = missed_counts_partial[lv]
        m_e = missed_counts_exact[lv]
        rec = llm_recovers_counts[lv]
        m_rate_p = round(m_p / g, 4) if g > 0 else 0.0
        m_rate_e = round(m_e / g, 4) if g > 0 else 0.0
        reach = round(rec / m_p, 4) if m_p > 0 else (0.0 if not llm_res else 1.0)

        by_level[lv] = {
            "gold": g,
            "missed_by_tools_partial": m_p,
            "missed_rate_partial": m_rate_p,
            "missed_by_tools_exact": m_e,
            "missed_rate_exact": m_rate_e,
            "llm_recovers": rec,
            "reachability": reach,
        }

    total_missed_rate = round(total_missed_partial / total_gold, 4) if total_gold > 0 else 0.0

    # 4. W3 중단 기준(Gate) 판정
    # 게이트: implicit >= 45% AND inferential >= 45% (미탐 공간)
    #        implicit >= 60% AND inferential >= 60% (도달 가능성)
    imp_miss_ok = by_level["implicit"]["missed_rate_partial"] >= 0.45
    inf_miss_ok = by_level["inferential"]["missed_rate_partial"] >= 0.45
    missed_space_pass = imp_miss_ok and inf_miss_ok

    has_llm = bool(llm_res)
    imp_reach_ok = by_level["implicit"]["reachability"] >= 0.60 if has_llm else True
    inf_reach_ok = by_level["inferential"]["reachability"] >= 0.60 if has_llm else True
    reachability_pass = imp_reach_ok and inf_reach_ok

    if has_llm:
        if missed_space_pass and reachability_pass:
            gate_decision = "PASS"
        elif missed_space_pass or reachability_pass:
            gate_decision = "PENDING"
        else:
            gate_decision = "STOP"
    else:
        gate_decision = "PASS (미탐 공간 충족 · LLM 대기)" if missed_space_pass else "PENDING"

    # 5. 콘솔 출력
    print("=" * 84)
    print("📊 [W3 베이스라인 3종 미탐 공간 및 LLM 도달 가능성 측정 결과]")
    print(f"   - 주 채점 기준: partial match (IoU >= 0.5)  /  부 지표: exact match")
    print(f"   - 3종 도구 합집합 미탐률: {total_missed_rate * 100:.1f}% ({total_missed_partial}/{total_gold})")
    print("=" * 84)
    print(f"{'등급':<14} | {'골드':>6} | {'3종 미탐(partial)':>16} | {'미탐율(주)':>10} | {'미탐율(exact)':>12} | {'도달가능성':>10}")
    print("-" * 84)
    for lv in levels:
        info = by_level[lv]
        reach_str = f"{info['reachability'] * 100:.1f}%" if has_llm else "-"
        print(f"{lv:<14} | {info['gold']:>6} | {info['missed_by_tools_partial']:>16} | {info['missed_rate_partial'] * 100:>9.1f}% | {info['missed_rate_exact'] * 100:>11.1f}% | {reach_str:>10}")
    print("-" * 84)
    tot_reach_str = f"{total_llm_recovers / total_missed_partial * 100:.1f}%" if (has_llm and total_missed_partial > 0) else "-"
    print(f"{'합계':<14} | {total_gold:>6} | {total_missed_partial:>16} | {total_missed_rate * 100:>9.1f}% | {total_missed_exact / total_gold * 100:>11.1f}% | {tot_reach_str:>10}")
    print("=" * 84)
    print(f"🚩 [W3 게이트 판정]: {gate_decision}")
    print(f"   - 미탐 공간 게이트 (implicit >= 45% AND inferential >= 45%): {'✅ 충족' if missed_space_pass else '❌ 미달'}")
    if has_llm:
        print(f"   - 도달 가능성 게이트 (implicit >= 60% AND inferential >= 60%): {'✅ 충족' if reachability_pass else '❌ 미달'}")
    print("=" * 84)

    print("\n🔍 [샘플 20건 관찰표]")
    print(f"| {'글 ID':<18} | {'등급':<11} | {'단서 구간':<32} | 정규식 | Presidio | korean-pii | LLM |")
    print("|---|---|---|:---:|:---:|:---:|:---:|")
    for r in sample_rows:
        print(f"| {r['id']:<18} | {r['level']:<11} | {r['clue'][:30]:<32} | {r['regex']:^6} | {r['presidio']:^8} | {r['koreanpii']:^10} | {r['llm']:^5} |")

    # 6. metrics.json 저장 (b-baselines.md §7.2 W3 공식 규격)
    metrics_data = {
        "experiment": "exp01-baseline",
        "measured_at": datetime.now().strftime("%Y-%m-%d"),
        "data_version": "corpus-v0",
        "scoring": {
            "primary": "partial_match (IoU >= 0.5)",
            "secondary": "exact_match",
        },
        "gate_thresholds": {
            "missed_rate": {"implicit": 0.45, "inferential": 0.45},
            "reachability": {"implicit": 0.60, "inferential": 0.60},
        },
        "gate_decision": gate_decision,
        "summary": {
            "total_gold_evaluated": total_gold,
            "missed_by_all_three_tools_partial": total_missed_partial,
            "missed_rate_partial": total_missed_rate,
            "missed_by_all_three_tools_exact": total_missed_exact,
            "missed_rate_exact": round(total_missed_exact / total_gold, 4) if total_gold > 0 else 0.0,
            "conclusion": f"기존 도구 3종 모두 한국형 문맥 준식별자의 {total_missed_rate * 100:.1f}%(partial)를 탐지하지 못함 -> 1단 스팬 모델 필요성 입증 및 W3 게이트 판정: {gate_decision}",
        },
        "by_level": {
            lv: {
                "gold": by_level[lv]["gold"],
                "missed_by_tools": by_level[lv]["missed_by_tools_partial"],
                "missed_rate": by_level[lv]["missed_rate_partial"],
                "missed_rate_exact": by_level[lv]["missed_rate_exact"],
                "llm_recovers": by_level[lv]["llm_recovers"],
                "reachability": by_level[lv]["reachability"],
            }
            for lv in levels
        },
        "environment": {
            "presidio": "presidio-analyzer + spacy ko_core_news_sm-3.8.0",
            "korean_ner": "spaCy ko_core_news_sm-3.8.0",
            "regex": "8-pattern baseline",
            "llm": "gemini" if has_llm else "pending",
        },
    }

    out_file = Path(args.out)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(metrics_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n💾 결과 metrics.json 저장 완료 -> {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
