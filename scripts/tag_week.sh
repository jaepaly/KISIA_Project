#!/usr/bin/env bash
# 주차 태그 + compare 링크.  bash scripts/tag_week.sh w03
# 제출 직후 실행한다. compare URL 한 줄이면 심사자가 클릭 한 번으로
# 그 주에 바뀐 전부와 커밋한 사람을 본다 — 캡처보다 강한 증빙이고 3초 걸린다.
set -euo pipefail
cd "$(dirname "$0")/.."

TAG="${1:?주차 태그 필요 (예: w03)}"
git tag "$TAG"
git push origin "$TAG"

PREV=$(git tag --sort=-creatordate | grep -E '^w[0-9]+$' | sed -n '2p' || true)
REMOTE=$(git remote get-url origin | sed 's|git@github.com:|https://github.com/|; s|\.git$||')

echo ""
echo "태그 생성: $TAG"
if [ -n "$PREV" ]; then
  echo "compare: ${REMOTE}/compare/${PREV}...${TAG}"
  echo "  ↑ 주간활동보고서 「활동 내용」에 이 링크를 넣는다"
else
  echo "compare: (이전 주차 태그 없음 — 다음 주부터 링크가 생긴다)"
fi
echo ""
