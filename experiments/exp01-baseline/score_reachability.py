import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def main():
    labeled_file = BASE_DIR / "results" / "gemini_labeled.jsonl"
    clues_file = BASE_DIR / "clues.jsonl"
    blind_file = BASE_DIR / "reachability_inputs.jsonl"
    
    # 1. Load files
    try:
        with open(blind_file, 'r', encoding='utf-8') as f:
            blind_inputs = [json.loads(line) for line in f if line.strip()]
        
        with open(labeled_file, 'r', encoding='utf-8') as f:
            labeled_inputs = [json.loads(line) for line in f if line.strip()]
            
        with open(clues_file, 'r', encoding='utf-8') as f:
            clues_inputs = [json.loads(line) for line in f if line.strip()]
    except Exception as e:
        print(f"Error loading files: {e}")
        sys.exit(1)
        
    clues_dict = {c['id']: c for c in clues_inputs}
    blind_dict = {b['id']: b for b in blind_inputs}
    
    # 2. Validation
    # 98건 검증
    if len(labeled_inputs) != 98:
        print(f"Validation failed: expected 98 labeled inputs, got {len(labeled_inputs)}")
        sys.exit(1)
        
    # ID 중복/누락 검증
    labeled_ids = [x['id'] for x in labeled_inputs]
    if len(set(labeled_ids)) != 98:
        print("Validation failed: ID duplication found in labeled inputs.")
        sys.exit(1)
        
    blind_ids = set([x['id'] for x in blind_inputs])
    if set(labeled_ids) != blind_ids:
        print("Validation failed: Labeled IDs do not match blind input IDs.")
        sys.exit(1)

    if len(blind_inputs) != 98 or len(blind_ids) != 98:
        print("Validation failed: blind inputs must contain 98 unique IDs.")
        sys.exit(1)

    missing_gold_ids = set(labeled_ids) - set(clues_dict)
    if missing_gold_ids:
        print(f"Validation failed: gold IDs missing: {sorted(missing_gold_ids)}")
        sys.exit(1)
        
    allowed_attrs = {"age", "sex", "location", "occupation", "family", "commute", "income"}
    allowed_subjects = {"self", "other", "unknown"}
    
    for item in labeled_inputs:
        item_id = item['id']
        # 원문 동일성 검증
        if item['text'] != blind_dict[item_id]['text']:
            print(f"Validation failed: Text mismatch for id {item_id}")
            sys.exit(1)
            
        text = item['text']
        spans = item.get('spans', [])
        
        # detected-spans 일관성 검증
        if item.get('detected') != (len(spans) > 0):
            print(f"Validation failed: 'detected' field inconsistency for id {item_id}")
            sys.exit(1)
            
        for span in spans:
            # attr/subject 허용값 검증
            if span['attr'] not in allowed_attrs:
                print(f"Validation failed: Invalid attr '{span['attr']}' in id {item_id}")
                sys.exit(1)
            if span['subject'] not in allowed_subjects:
                print(f"Validation failed: Invalid subject '{span['subject']}' in id {item_id}")
                sys.exit(1)
                
            # offset 검증
            start = span['start']
            end = span['end']
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or start >= end or end > len(text):
                print(f"Validation failed: Invalid offset range in id {item_id}")
                sys.exit(1)
            if text[start:end] != span['text']:
                print(f"Validation failed: Offset mismatch in id {item_id}. Expected '{span['text']}', got '{text[start:end]}'")
                sys.exit(1)
                
    # 3. Scoring
    levels = ["explicit", "implicit", "inferential"]
    stats = {lvl: {"total": 0, "scorable": 0, "auto_match": 0, "unscorable": 0} for lvl in levels}
    
    total_detected = 0
    total_auto_match = 0
    
    null_subject_cases = []
    
    for item in labeled_inputs:
        item_id = item['id']
        gold = clues_dict.get(item_id)
        if not gold:
            # blind input id가 clues.jsonl에 없는 경우는 정상적으로 없어야 함.
            continue
            
        if item.get('detected'):
            total_detected += 1
            
        lvl = gold.get('level')
        if lvl not in stats:
            stats[lvl] = {"total": 0, "scorable": 0, "auto_match": 0, "unscorable": 0}
            
        stats[lvl]["total"] += 1
        
        gold_subject = gold.get('subject')
        if not gold_subject or gold_subject not in allowed_subjects:
            stats[lvl]["unscorable"] += 1
            if item_id in ["S01_b12_03", "S01_b17_04"]:
                null_subject_cases.append(item_id)
        else:
            stats[lvl]["scorable"] += 1
            
            # Check auto_match
            # prediction.attr == gold.attr AND prediction.subject == gold.subject
            match_found = False
            for span in item.get('spans', []):
                if span['attr'] == gold.get('attr') and span['subject'] == gold_subject:
                    match_found = True
                    break
                    
            if match_found:
                stats[lvl]["auto_match"] += 1
                total_auto_match += 1

    # 4. Reporting
    print("=== 명시적 보고 대상 (subject 없음) ===")
    for c in ["S01_b12_03", "S01_b17_04"]:
        if c in null_subject_cases:
            print(f"- {c} : 확인됨 (unscorable 처리)")
        else:
            print(f"- {c} : 목록에 없거나 처리되지 않음")
    print()
    
    print("=== 등급별 채점 결과 ===")
    for lvl in levels:
        s = stats[lvl]
        reachability = (s["auto_match"] / s["scorable"] * 100) if s["scorable"] > 0 else 0.0
        print(f"[{lvl.upper()}]")
        print(f"  - 전체 골드 수: {s['total']}")
        print(f"  - 채점 가능 수(scorable): {s['scorable']}")
        print(f"  - auto_match 수: {s['auto_match']}")
        print(f"  - unscorable 수: {s['unscorable']}")
        print(f"  - 임시 도달 가능성: {reachability:.1f}%")
        print()
        
    print("=== 종합 요약 ===")
    print(f"전체 detected 수: {total_detected}")
    print(f"엄격한 auto_match 수: {total_auto_match}")
    print()
    
    print("=== 모델 메타데이터 ===")
    print("- model: Gemini 3.1 Pro")
    print("- reasoning mode: High")
    print("- via: Gemini CLI via Antigravity")
    print("- measured_at: 2026-09-08")
    print("- fallback: false")

if __name__ == "__main__":
    main()
