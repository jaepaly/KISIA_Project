#!/usr/bin/env bash
# 주간 기여 증빙 생성.  bash scripts/weekly_report.sh 2026-08-31 2026-09-07 W03
# 출력: docs/evidence/W-03/git-summary.md  (주간활동보고서 「활동 내용」의 원자료)
set -euo pipefail
cd "$(dirname "$0")/.."

SINCE="${1:?시작일 필요 (예: 2026-08-31)}"
UNTIL="${2:?종료일 필요 (예: 2026-09-07)}"
WEEK="${3:?주차 필요 (예: W03)}"
NUM="${WEEK#W}"
OUT="docs/evidence/W-${NUM}"

# git 은 시각 없는 날짜를 «그날 00:00» 이 아니라 «그날 현재 시각» 으로
# 해석한다. 금요일 저녁에 돌리면 월요일 낮 커밋이 통째로 빠진다.
SINCE_TS="${SINCE} 00:00:00"
UNTIL_TS="${UNTIL} 23:59:59"
mkdir -p "$OUT"

{
  echo "# ${WEEK} 기여 요약"
  echo ""
  echo "기간: ${SINCE} ~ ${UNTIL} · 생성: $(git log -1 --format=%cd --date=short 2>/dev/null || echo '-')"
  echo ""
  echo "## 사람별 커밋 수"
  echo ""
  echo '```'
  git shortlog -sn --no-merges HEAD --since="$SINCE_TS" --until="$UNTIL_TS" || true
  echo '```'
  echo ""
  echo "## 커밋 목록"
  echo ""
  git log --no-merges --use-mailmap --since="$SINCE_TS" --until="$UNTIL_TS" \
    --pretty='- `%h` **%aN** — %s' || true
  echo ""
  echo "## 실험 (type=exp) — 8주차 「학습·테스트 진행 내용」의 원자료"
  echo ""
  git log --no-merges --use-mailmap --since="$SINCE_TS" --until="$UNTIL_TS" \
    --grep='^exp' --pretty='- `%h` **%aN** — %s' || true
  echo ""
  echo "## 데이터 변경 (type=data)"
  echo ""
  git log --no-merges --use-mailmap --since="$SINCE_TS" --until="$UNTIL_TS" \
    --grep='^data' --pretty='- `%h` **%aN** — %s' || true
  echo ""
  echo "## 멘토 피드백 반영 (MF 태그)"
  echo ""
  git log --no-merges --use-mailmap --since="$SINCE_TS" --until="$UNTIL_TS" \
    --grep='MF-' --pretty='- `%h` **%aN** — %s' || true
  echo ""
  echo "## 변경된 파일"
  echo ""
  echo '```'
  git log --no-merges --since="$SINCE_TS" --until="$UNTIL_TS" --name-only --pretty=format: \
    | sort -u | grep -v '^$' || true
  echo '```'
} > "$OUT/git-summary.md"

echo "생성: $OUT/git-summary.md"
echo ""
echo "함께 남길 증빙 2종 (파일명 규칙: W03_B_학습로그_20260904.png)"
echo "  · Contributors 그래프 캡처 — 기간 지정, 날짜가 보이게"
echo "  · Projects 「이번주」 뷰 캡처 — Group by Role"
