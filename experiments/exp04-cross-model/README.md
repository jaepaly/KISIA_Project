# exp-004: R1~R6 교차모델 재실행

## 무엇을 왜 재는가

정본 문서에 남은 R1~R6 조건을 Claude와 GPT-5.5에 동일하게 제시하고, 두 모델이 독립적으로 추론한 준식별자 속성이 의미상 일치하는지 확인한다. 이는 특정 모델에서만 나타난 결과가 아니라는 [`docs/plan.md` §6의 외적 타당성 방어 ⑤](../../docs/plan.md)를 복구하기 위한 실험이다.

이 실험은 학습된 Qwen3와 외부 LLM을 비교하는 목표 지표와 다르다. 따라서 exp04에는 임계값이나 PASS/FAIL 판정이 없으며, 일치율 수치만 기록한다.

## 설정

| 항목 | 값 |
|---|---|
| 측정일 | 2026-09-07 |
| 입력 데이터 버전 | `reconstructed_summary` — `docs/plan.md`와 루트 `README.md`에 남은 R1~R6 요약 |
| 모델 A | `claude-sonnet-4-6` · Claude CLI |
| 모델 B | `gpt-5.5` · ChatGPT web UI |
| 검토 단위 | 인물 6명 × 속성 7개 = 42칸 |
| 검토 규칙 | 두 값이 의미상 같은 범위를 가리키면 `true`, 다르거나 한쪽만 기권하면 `false` |
| 하드웨어 | 외부 호스팅 모델 사용 · 로컬 GPU 미사용 |
| 환경 | Python 3 러너 · Claude CLI · ChatGPT web UI |
| 시드 | 미고정 — 외부 모델 실행 경로에서 시드를 제공하지 않음 |

원출력과 사람 검토 결과는 각각 [`results/model_a.json`](results/model_a.json), [`results/model_b.json`](results/model_b.json), [`results/review.json`](results/review.json)에 보존한다. 집계 결과는 [`metrics.json`](metrics.json)에 기록한다.

## 실행

```bash
# R1~R6 요약 입력과 7개 속성 구조 확인
python experiments/exp04-cross-model/run.py --validate

# 두 모델에 동일하게 입력할 프롬프트 출력
python experiments/exp04-cross-model/run.py --print-prompt

# 각 실행 경로에서 받은 JSON으로 검토 파일 생성
python experiments/exp04-cross-model/run.py \
  --output-a /path/to/claude.json \
  --output-b /path/to/gpt-5.5.json \
  --name-a claude-sonnet-4-6 \
  --name-b gpt-5.5 \
  --via-a "claude CLI" \
  --via-b "ChatGPT web UI"

# results/review.json의 agree 42개를 사람이 검토한 뒤 집계
python experiments/exp04-cross-model/run.py --score
```

## 결과

| 응답 형태 | 검토 칸 | 일치 | 일치율 |
|---|---:|---:|---:|
| 두 모델 모두 값 있음 | 20 | 19 | **0.9500** |
| 두 모델 모두 빈칸 | 22 | 22 | 1.0000 |
| 한쪽만 값 있음 | 0 | 0 | 해당 없음 |
| 전체 | 42 | 41 | 0.9762 |

유일한 불일치는 `R1.location`이다. Claude는 `경기도 용인시 기흥구 인근`, GPT-5.5는 `신갈저수지·기흥호수 관련 지역`으로 답해 의미상 같은 범위로 판정하지 않았다.

## 해석

교차모델 근거로 사용할 핵심 수치는 **두 모델 모두 값을 제시한 칸의 일치율 0.95(19/20)**이다. 전체 일치율 0.9762(41/42)는 두 모델이 함께 기권한 22칸을 포함하므로 참고치로 구분한다.

두 모델의 추론 결과가 대부분 같은 의미 범위에 있었지만, 이 수치만으로 모델의 정확도나 선행 PoC 재현 성공을 주장하지 않는다. exp04의 목적은 특정 모델의 아티팩트가 아니라는 방어 근거를 남기는 것이다.

## 한계

- 선행 PoC의 R1~R6 원문 게시글과 원 조건은 저장소에 없다.
- 정본 문서에 남은 요약만 사용하므로 선행 PoC 수치의 직접 재현은 아니다.
- 문서에 없는 거주지·직업·가족·통근·소득 값은 추가하지 않았다.
