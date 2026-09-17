#!/bin/bash
# 분석기가 SNS 내부를 건드리면 exit 1
result=$(grep -rn "sns\.db\|apps\.sns\|apps/sns" apps/analyzer/ 2>/dev/null)
if [ -n "$result" ]; then
  echo "⚠️ 계층 경계 위반:"
  echo "$result"
  exit 1
fi
echo "OK: 경계 유지"
