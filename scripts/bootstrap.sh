#!/usr/bin/env bash
# 새 팀원이 clone 직후 한 번 실행한다.  bash scripts/bootstrap.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo ""
echo "── KISIA Project 초기 설정 ──────────────────────────"

git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true
echo "  ✓ git 훅 활성화 (core.hooksPath = .githooks)"

NAME=$(git config user.name || true)
MAIL=$(git config user.email || true)
if [ -z "$NAME" ] || [ -z "$MAIL" ]; then
  echo "  ✗ git 이름·메일이 설정되지 않았다"
  echo "      git config user.name  \"본인이름\""
  echo "      git config user.email \"본인메일\""
  echo "    설정 후 PM에게 알릴 것 — .mailmap 에 등록해야 기여 집계가 한 사람으로 잡힌다."
else
  echo "  ✓ 커밋 신원: $NAME <$MAIL>"
  grep -q "$MAIL" .mailmap 2>/dev/null \
    && echo "  ✓ .mailmap 등록됨" \
    || echo "  ! .mailmap 미등록 — PM에게 이름·메일을 전달할 것"
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "  ✓ .env 생성 (.env.example 복사) — 실제 키를 채울 것"
else
  echo "  ✓ .env 존재"
fi

echo ""
echo "  다음에 읽을 것"
echo "    README.md                  프로젝트 전체"
echo "    docs/roles/<내역할>.md      내 자리 작업 매뉴얼"
echo "    docs/RULES-DO-NOT.md       절대 하면 안 되는 것 ← 먼저 읽을 것"
echo "    CONTRIBUTING.md            브랜치·커밋·리뷰 규칙"
echo "─────────────────────────────────────────────────────"
echo ""
