#!/usr/bin/env bash
# W3 코퍼스 생성 — D 몫(D · E · S) 을 3-way 로 돌린다.
#
#   bash scripts/generate_w03.sh              실제 생성
#   bash scripts/generate_w03.sh --dry-run    무엇이 돌지만 보고 끝낸다
#   bash scripts/generate_w03.sh --smoke      인물당 2편만 (배선 확인)
#
# ⚠️ 함정이 없는 인물은 자동으로 뒤로 뺀다. 이 스크립트가 하는 일의 절반이 그거다.
#    persona-design.md §8 이 「subject: other 함정은 인물마다 하나 이상」을 요구하는데
#    generate.py 는 post_plan.trap 을 읽지 않는다 — clue_plan 에 subject:other 가
#    없으면 함정 글이 0편 나오고 그 자리는 잡담이 된다. 그대로 돌리면 나중에 함정을
#    넣은 뒤 그 인물 글을 통째로 다시 뽑아야 한다. 2026-09-01 기준 E 5명이 그렇다.
#
#    목록을 여기 박아두지 않는다. 매번 인물 파일을 읽어서 판정한다 — 고쳐지면
#    다음 실행에서 자동으로 앞 무리에 들어간다.
#
# 중단해도 된다. generate.py 가 post_id 단위로 resume 한다 (이미 뽑은 글은 건너뛴다).
# 실패한 글도 저장되지 않으므로 그냥 다시 돌리면 그것만 다시 뽑는다.
set -uo pipefail
cd "$(dirname "$0")/.."

PERSONAS=data/corpus/v0/personas
OUT=${GEN_OUT:-data/corpus/v0/posts}      # 시험할 때만 다른 곳으로 돌린다
CARDS=data/realism/cards
MODEL=gpt-5.6-sol
PROVIDER=cli
MODELARG="--model ${MODEL}"
CLI="codex exec --sandbox read-only -m ${MODEL} -"
SHARDS=3            # 실측 최적 (#16). 6-way 는 포화라 오히려 느리다
LOG=".gen-w03"

DRY=0; SAMPLE=""
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --smoke)   SAMPLE="--sample 2" ;;
    --echo)    PROVIDER="echo"; CLI=""; MODELARG="" ;;   # 배선만 확인. LLM 호출 0건
    *) echo "모르는 인자: $a"; exit 2 ;;
  esac
done

export PYTHONPATH=src

# echo 모드는 더미 텍스트다. 진짜 코퍼스 경로로는 절대 돌리지 않는다.
if [ "$PROVIDER" = "echo" ] && [ "$OUT" = "data/corpus/v0/posts" ]; then
  echo "✗ --echo 는 진짜 코퍼스에 더미 글을 쓴다. GEN_OUT 을 따로 지정해라."
  echo "    GEN_OUT=/tmp/gen bash scripts/generate_w03.sh --echo --smoke"
  exit 2
fi

# ── 내 몫을 함정 유무로 가른다 ────────────────────────────────────────
# ⚠️ 경로 끝의 CR 을 반드시 벗긴다. Windows 의 python print 가 CRLF 를 쓰고
#    readarray -t 는 LF 만 벗긴다. 그러면 'D01.json' + CR 이 되어 파일을 못 열고,
#    --skip-invalid 와 겹쳐 「전원 검증 실패 → 건너뜀」으로 조용히 0편이 된다.
#    2026-09-01 시험에서 실제로 그렇게 뚚렸다. 〔 기록 안 하면 내일 또 뚚린다 〕
readarray -t READY < <(python -X utf8 scripts/gen_partition.py "$PERSONAS" ready | tr -d '\015')
readarray -t DEFER < <(python -X utf8 scripts/gen_partition.py "$PERSONAS" defer | tr -d '\015')

echo "── D 몫 ─────────────────────────────────────────────"
printf '  지금 돌린다   %3d명\n' "${#READY[@]}"
printf '  뒤로 뺀다     %3d명' "${#DEFER[@]}"
if [ "${#DEFER[@]}" -gt 0 ]; then
  printf '   %s' "$(basename -a "${DEFER[@]}" | sed 's/\.json//' | tr '\n' ' ')"
fi
echo; echo

if [ "${#DEFER[@]}" -gt 0 ]; then
  echo "  ⚠️ 위 인물은 subject:other 함정이 없다 (§4-4-1 · §8)."
  echo "     함정이 들어온 뒤 이 스크립트를 다시 돌리면 그때 생성된다."
  echo
fi

if [ "${#READY[@]}" -eq 0 ]; then echo "돌릴 인물이 없다"; exit 0; fi

# ── 3-way 로 쪼갠다 ──────────────────────────────────────────────────
mkdir -p "$LOG"
for i in $(seq 0 $((SHARDS-1))); do : > "$LOG/shard$i.txt"; done
n=0
for p in "${READY[@]}"; do
  echo "$p" >> "$LOG/shard$((n % SHARDS)).txt"
  n=$((n+1))
done

for i in $(seq 0 $((SHARDS-1))); do
  c=$(wc -l < "$LOG/shard$i.txt")
  printf '  shard%d  %2d명\n' "$i" "$c"
done
echo

if [ "$DRY" -eq 1 ]; then echo "(--dry-run — 여기서 끝낸다)"; exit 0; fi

# ── 돈다 ─────────────────────────────────────────────────────────────
START=$(date +%s)
for i in $(seq 0 $((SHARDS-1))); do
  ( xargs -a "$LOG/shard$i.txt" -d '\n' \
      python -X utf8 -m kopl.c5_corpus.generate \
        --out "$OUT" --cards "$CARDS" \
        --provider "$PROVIDER" $MODELARG --cli-cmd "$CLI" \
        --skip-invalid $SAMPLE --persona \
      > "$LOG/shard$i.log" 2>&1 ) &
done
wait
ELAPSED=$(( $(date +%s) - START ))

# ── 결과 ─────────────────────────────────────────────────────────────
echo "── 결과 ─────────────────────────────────────────────"
FAIL=$(grep -h "  ✗ " "$LOG"/shard*.log | wc -l)
if [ "$FAIL" -gt 0 ]; then
  echo "  실패 사유:"
  grep -h "  ✗ " "$LOG"/shard*.log | sed 's/.*실패: //;s/.*잘림.*/잘림 — --max-tokens 를 올려라/' \
    | sort | uniq -c | sort -rn | head -10 | sed 's/^/    /'
fi
POSTS=$(cat "$OUT"/*.jsonl 2>/dev/null | wc -l)
printf '  글 %d편 · 실패 %d건 · %d분 %d초\n\n' "$POSTS" "$FAIL" $((ELAPSED/60)) $((ELAPSED%60))
if [ "$FAIL" -gt 0 ]; then
  echo "  ⚠️ 실패한 글은 저장되지 않았다. 이 스크립트를 다시 돌리면 그것만 다시 뽑는다."
  echo
fi

# 쓴 글을 읽어 실측 노이즈를 낸다.
# ⚠️ generate.py 를 --provider echo 로 다시 돌려서 합산을 내면 안 된다 —
#    아직 안 돌린 인물(남의 몫 · 뒤로 앉 것)에 더미 글이 그대로 쌓린다.
#    실측 2026-09-01: 그렇게 했다가 189개 파일이 더미로 채워졌다.
echo "── 코퍼스 합산 (쓴 글만 읽는다) ─────────────────"
python -X utf8 - "$OUT" <<'PYEOF'
import json, sys, collections
from pathlib import Path
out = Path(sys.argv[1])
kinds = collections.Counter(); per = collections.Counter()
for f in sorted(out.glob("*.jsonl")):
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            kinds[r["kind"]] += 1; per[r["persona_id"]] += 1
n = sum(kinds.values())
if not n:
    print("  쓴 글이 없다"); raise SystemExit(0)
noise = (kinds["noise"] + kinds["ambient"]) / n
flag = "OK" if 0.70 <= noise <= 0.80 else "⚠ 70~80% 범위밖"
print(f"  인물 {len(per)}명 · 글 {n}편")
print(f"  단서 {kinds['clue']} · 지역 {kinds['ambient']} · 잡담 {kinds['noise']}")
print(f"  노이즈 {noise:.0%} {flag}")
PYEOF
