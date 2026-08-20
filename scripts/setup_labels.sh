#!/usr/bin/env bash
# GitHub 라벨 일괄 생성. gh CLI 로그인 필요.  bash scripts/setup_labels.sh
set -euo pipefail
command -v gh >/dev/null || { echo "gh CLI가 필요하다: https://cli.github.com"; exit 1; }

mk() { gh label create "$1" --color "$2" --description "$3" --force >/dev/null && echo "  ✓ $1"; }

echo "── 역할 ──"
for r in A B C D E; do mk "role/$r" "1D76DB" "역할 $r"; done

echo "── 컴포넌트 ──"
mk comp/c1 "5319E7" "① 준식별자 탐지"
mk comp/c2 "5319E7" "② 특정성 엔진"
mk comp/c3 "5319E7" "③ 누적·기여도"
mk comp/c4 "5319E7" "④ 가명화·2단·조치"
mk comp/c5 "5319E7" "⑤ 데이터셋·벤치마크"
mk comp/c6 "5319E7" "⑥ 시스템·데모·평가"
mk comp/c7 "5319E7" "⑦ 가상 SNS 플랫폼"

echo "── 주차 ──"
for i in 01 02 03 04 05 06 07 08 09 10 11 12; do mk "week/W$i" "C5DEF5" "W$i"; done

echo "── 유형 ──"
mk type/exp         "0E8A16" "실험 — 8주차 보고서 원자료"
mk type/data        "0E8A16" "코퍼스·라벨·사전"
mk type/deliverable "B60205" "KISIA 제출물"

echo "── 운영 ──"
mk mentor/feedback  "FBCA04" "멘토 피드백 — 반영 PR에서 Closes # 로 닫으면 그 자체가 증빙"
mk blocked          "D93F0B" "막힘 — 지원 필요"
mk contract         "E99695" "모듈 인터페이스 계약 변경 (2명 승인)"

echo ""
echo "완료."
