# exp18-teacher-design: 교사 라벨을 더 좋게 만들면 1단이 나아지나 — 결론: 교사는 병목이 아니다 (#310 1번)

## 1. 질문

1단 재학습(검수 331 + 교사 2,281편)의 명시 재현율이 코퍼스 밖에서 기대만큼 안 나온다. 교사(Claude Opus 4.8) 라벨이 단서를 놓쳐서인가?

## 2. 시험 세 가지 (2026-10-05)

### ① 검수 골드 대비 교사 누락 — 착시가 섞인다

사람이 검수한 397편에서 교사 원본(`gold/detect`, 탐지본)과 사람 검수본을 대조:

| 검수 글 종류 | 사람 스팬 | 교사가 놓침 |
|---|---|---|
| clue (단서 심은 글) | 109 | **48%** |
| noise (잡담) | 436 | 4% |

명시 단서 누락은 10%, 놓친 것 대부분은 「점심 건너뛴 날」 「첫차는」 같은 판단이 갈리는 추론 단서다. #310 본문의 근거로 쓴 「단서 토큰 0.65% vs 1.33%」는 검수 대상 글 구성 차이(검수 쪽에 단서 많은 잡담 글이 몰림)가 섞인 숫자라 철회한다.

### ② 설계본(심은 단서를 힌트로) · Opus 5.5 로 다시 붙이기 — 검수 골드로는 판정 불가

clue 검수 글 69편 · 사람 스팬 109 (type 일치 + IoU ≥ 0.5):

| 교사 | 재현율 | 정밀도 | 사람 스팬과 겹치기만 (유형 같음) | 스팬 수 · 평균 길이 |
|---|---|---|---|---|
| Opus 4.8 탐지본 (기존) | 52% | **0.95** | 52% | 60 · 3.7자 |
| Opus 4.8 설계본 | 51% | 0.49 | 71% | 114 · 7.7자 |
| Opus 5.5 탐지본 | 47% | 0.49 | 65% | 105 · 5.0자 |

새 교사는 더 많이 찾지만(겹침 52% → 65~71%) 엄격 기준에서 나빠진다. **검수 골드는 Opus 4.8 출력을 사람이 고쳐 만든 것**이라 경계·유형이 4.8 쪽으로 기운다 — 다른 교사를 이 골드로 재면 불리하고, 4.8 의 정밀도 0.95 도 그 덕이다. 그래서 ③ 으로 다시 쟀다.

### ③ 독립 정답(exp17 「심은 단서」 평가셋 80편 · 145단서)으로 교사 비교 — **결론**

| | Opus 4.8 (기존 교사) | Opus 5.5 |
|---|---|---|
| **본인 단서 재현율** | **92.4%** | 91.6% |
| 숫자 나이 · 반말 어미 · 금액 | 11/11 · 8/8 · 9/12 | 11/11 · 8/8 · 10/12 |
| 타인 단서를 표시 | 11/26 | **21/26** (전부 other 로) |
| 숫자 함정 오탐 | 2/15 | 4/15 |
| 심지 않은 곳 (글당, 참고치) | 0.75 | 0.96 |

- **교사는 본인 단서를 이미 92% 찾는다.** Opus 5.5 로 바꿔도 같다
- 5.5 가 나은 건 타인 단서 표시뿐 — 1단의 subject 는 규칙(#306)이 맡아 학습 라벨 효과가 작다. 숫자 함정 오탐은 늘었다
- **병목은 교사 → 학생(1단) 사이다.** 같은 계열 글에서 교사 92% · 1단 재학습 약 70%(인스턴스 지어낸 글 12편, 표본 작음). 교사 라벨의 질이 아니라 **학습 데이터의 폭**(코퍼스에 없는 표현)이 모자라다

## 3. 결정 (#310)

- **1번(교사 라벨 보강 · 교사 교체) 접는다** — 486편 재라벨은 하지 않는다
- **2번(변이 글 보강)에 집중** — 변이 글 라벨은 지금 교사(Opus 4.8)로 충분하다

## 4. 재현

```bash
export PYTHONIOENCODING=utf-8
P="src;experiments/exp18-teacher-design"
# ② 검수 clue 69편
PYTHONPATH=$P python experiments/exp18-teacher-design/pilot.py --env <KISIA .env>                                  # 설계본 (Opus 4.8)
PYTHONPATH=$P python experiments/exp18-teacher-design/pilot.py --env <KISIA .env> --model claude-opus-5-5 --no-hint --tag opus55_detect
# ③ 평가셋 80편
PYTHONPATH=$P python experiments/exp18-teacher-design/teacher_on_planted.py --env <KISIA .env> --model claude-opus-4-8 --out results/planted_opus48.jsonl
PYTHONPATH=$P python experiments/exp18-teacher-design/teacher_on_planted.py --env <KISIA .env> --model claude-opus-5-5 --out results/planted_opus55.jsonl
python experiments/exp17-planted-eval/score.py experiments/exp18-teacher-design/results/planted_*.jsonl
```

교사 호출은 KISIA 팀 게이트웨이 키. `kisia_env.py` 는 `.env` 에 같은 키가 여러 줄이면 비어 있지 않은 마지막 값을 쓴다 (`c5_corpus.llm.load_dotenv` 는 앞의 빈 값을 잡는다 — 팀 `.env` 가 그런 상태). 결과 파일의 스팬은 교사가 가상 글에 붙인 라벨이다.
