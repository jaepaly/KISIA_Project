#!/usr/bin/env bash
# exp22b 판정 → (기준 1~5 통과 시) exp09 재비교까지 한 번에. 검토 · 해시 고정(run_stage1.py FROZEN) 뒤에 돌린다.
#   bash experiments/exp22b-stage2-judge/pipeline.sh <v1 어댑터 보관본> <1단 v2 체크포인트>
set -u
V1=$1; C1=$2
D=experiments/exp22b-stage2-judge; E=experiments/exp09-external-agreement
export PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 PYTHONPATH="src;."
mkdir -p $D/results
step() { echo "== $(date +%H:%M) $1"; }

step "1단 예측 고정"
ENGINE_MODE=real C1_CHECKPOINT_DIR=$C1 python $D/run_stage1.py > $D/results/stage1.log 2>&1 || { echo "1단 실패"; exit 1; }
step "2단 v1"
python $D/run_stage2.py --config v1 --adapter $V1 > $D/results/run_v1.log 2>&1 || { echo "v1 실패"; exit 1; }
step "2단 v2"
python $D/run_stage2.py --config v2 > $D/results/run_v2.log 2>&1 || { echo "v2 실패"; exit 1; }
step "채점"
python $D/score.py > $D/results/score.log 2>&1 || { echo "채점 실패"; exit 1; }

PASS=$(python -c "
import json;c=json.load(open('$D/results/metrics.json',encoding='utf-8'))['criteria']
print('yes' if all(v is True for k,v in c.items() if not k.startswith('6')) else 'no')")
step "기준 1~5 통과: $PASS"
if [ "$PASS" != yes ]; then echo "exp09 재비교는 하지 않는다 (기준 미달 · README §2)"; exit 0; fi

step "exp09 v1"
python $E/run_config.py --config v1 --adapter $V1 > $D/results/exp09_v1.log 2>&1 || { echo "exp09 v1 실패"; exit 1; }
step "exp09 v2"
python $E/run_config.py --config v2 > $D/results/exp09_v2.log 2>&1 || { echo "exp09 v2 실패"; exit 1; }
step "exp09 채점"
python $E/score.py --qwen-file qwen_cfg_v1.jsonl --out metrics_cfg_v1.json > $D/results/exp09_score_v1.log 2>&1
python $E/score.py --qwen-file qwen_cfg_v2.jsonl --out metrics_cfg_v2.json > $D/results/exp09_score_v2.log 2>&1
python - <<'PY' | tee $D/results/criterion6.txt
import importlib.util, json
spec = importlib.util.spec_from_file_location("s9", "experiments/exp09-external-agreement/score.py"); s9 = importlib.util.module_from_spec(spec); spec.loader.exec_module(s9)
from pathlib import Path; d = Path("experiments/exp09-external-agreement/data")
ext, inp = s9.load(d / "external.jsonl"), s9.load(d / "inputs.jsonl")
res = {}
for c in ("v1", "v2"):
    q = s9.load(d / f"qwen_cfg_{c}.jsonl")
    cells = [(s9.verdicts(q.get(p))[a], s9.verdicts(ext.get(p))[a]) for p in sorted(inp) for a in s9.ATTRS]
    nab = [x for x in cells if x[1] != "abstain"]
    res[c] = (sum(x == y for x, y in cells) / len(cells), sum(x == y for x, y in nab) / len(nab), len(nab))
print("exp09 전체 일치 v1 %.4f v2 %.4f · 외부 비기권 칸(%d) v1 %.4f v2 %.4f" % (res["v1"][0], res["v2"][0], res["v1"][2], res["v1"][1], res["v2"][1]))
ok = res["v2"][0] >= res["v1"][0] - 0.03 and res["v2"][1] >= res["v1"][1] - 0.03
print("기준 6 통과" if ok else "기준 6 미달")
PY

step "끝"
