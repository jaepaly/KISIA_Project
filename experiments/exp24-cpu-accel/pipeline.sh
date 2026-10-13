#!/usr/bin/env bash
# exp24 전체 — 예측 2구성 → 지연 4구성 (순서대로 · 다른 무거운 작업과 겹치지 않게)
set -euo pipefail
CK="${1:?v2 체크포인트 폴더}"
cd "$(dirname "$0")/../.."
export PYTHONIOENCODING=utf-8
for m in fp32 int8; do python experiments/exp24-cpu-accel/run.py preds --checkpoint "$CK" --mode $m --threads 4; done
for t in 4 2; do for m in fp32 int8; do python experiments/exp24-cpu-accel/run.py latency --checkpoint "$CK" --mode $m --threads $t; done; done
