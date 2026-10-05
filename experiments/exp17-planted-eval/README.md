# exp17-planted-eval: 코퍼스 밖 평가셋 — Gemini 가 쓰고, 정답은 「심은 단서」

## 1. 왜 (#310)

1단을 지금까지 잰 test · blind · 내부 eval 은 **모두 같은 생성기(`gpt-5.6-sol`)가 쓴 코퍼스**다. 인스턴스 비교(10/5)에서 재학습 모델은 코퍼스 글에서 v1+규칙보다 44% 앞섰지만 지어낸 글 12편에서는 4% 앞섰다 — 코퍼스 안 점수로는 실제 일반화를 알 수 없다. 그 12편도 Claude 가 지어 Claude 교사로 배운 재학습 모델에 유리할 수 있었다.

## 2. 무엇을 만들었나

| | |
|---|---|
| 글 | **80편** · SNS 말투 2~4문장 · 주제·말투 무작위 (`specs.py` seed 20261006) |
| 생성기 | **Gemini** — 생성기 GPT · 교사 Claude · 2단 Qwen 어느 쪽과도 다른 계열. 무료 등급 한도(모델당 하루 20회)로 `gemini-flash-lite-latest` 67 · `gemini-3.6-flash` 12 · `gemini-3.8-flash` 1편 |
| 정답 | 글마다 「이 표현을 **그대로** 넣어라」로 지정한 단서의 위치 (문자열 일치) — **사람·Claude 라벨 없음** |
| 단서 | 145개 — 본인 119 · 타인 함정 26 (형·누나·친구·조카·이웃 아들) |
| 숫자 함정 | 15편 — 「서른 해 동안」 「쉰 날」 「스무 권」 「마흔 군데」 (나이로 잡으면 오탐) |
| 변이 | 숫자 나이(「나이 48에」 「37세」) · 반말 어미(「스물셋임」 「쉰다섯이야」) · 금액(「월급 삼백이십만 원」 「연봉 4,200만」) · 시·구(「수원 영통구」) · 동 · 역 · 공원 · 시장 · 직업명 · 가족 · 노선·버스 |

지정 표현이 그대로 안 들어간 글은 최대 3번 다시 시켰다(버린 글 0). 프롬프트는 단서마다 「글쓴이 **자신의** 정보로」 / 「**다른 사람의** 정보로」를 명시한다 — 첫 시험에서 「손님 머리 자르다」를 형을 묘사하는 비유로 써서 넣은 지시다.

**80편 전수 검토 (2026-10-05, D)**: 심은 단서가 모두 의도한 뜻(본인·타인·수량)으로 쓰였다. 어색한 문장 몇 개(068 어르신 말투 + 「23살」 · 080 「쉰다섯이야 되다 보니」)는 탐지 평가에 지장이 없어 그대로 둔다. 심지 않은 단서가 일부 섞였다(049 「우리 집 양반」 · 010 「늙은이」 · 053 「엄마」).

## 3. 지표 — `score.py`

| 지표 | 뜻 |
|---|---|
| **재현율 (본인)** | 심은 본인 단서 중 type 일치 + IoU ≥ 0.5 로 잡힌 비율 (label-schema §2 partial) · 유형별 · 변이별 |
| **타인 함정** | 타인 단서를 잡았을 때 subject=other 로 판정했나 — self 면 남의 정보로 내 k 를 좁힌다 |
| 숫자 함정 오탐 | 「서른 해」 등을 AGE 로 잡은 수 |
| 심지 않은 곳 (참고치) | 심은 단서·함정과 겹치지 않는 예측 수 — Gemini 가 의도치 않게 넣은 단서일 수 있어 **정밀도가 아니다** |

## 4. 한계

- **사람 글이 아니다.** 코퍼스 밖이지만 LLM(Gemini) 글이다. 사람이 쓸 시간이 없어서 택한 차선
- 정답은 심은 단서뿐이라 **정밀도는 정확히 못 잰다**
- 정답 스팬은 심은 표현의 핵심 부분(「동탄 사는 친구가」 → 「동탄」)이다. 1단이 「용인 기흥구」를 한 스팬으로 잡으면 맞고, 「용인시 기흥구 상갈동」처럼 더 길게 잡으면 IoU 가 0.5 아래로 떨어질 수 있다
- 80편 · 145단서 — 유형별 칸은 작다 (SEX 2 · COMMUTE 6)

## 5. 재현 · 예측 만들기

```bash
export PYTHONIOENCODING=utf-8
# (생성 — 이미 data/posts.jsonl 에 있음. 다시 만들 때만)
PYTHONPATH=src python experiments/exp17-planted-eval/generate.py --env <KISIA .env>

# 1단 구성별 예측 — 체크포인트가 있는 곳(인스턴스 · B)에서
PYTHONPATH="src;experiments/exp06-finetune" python experiments/exp17-planted-eval/predict.py --checkpoint <v1 폴더> --out preds_v1.jsonl
PYTHONPATH="src;experiments/exp06-finetune" python experiments/exp17-planted-eval/predict.py --checkpoint <v1 폴더> --rules --out preds_v1_rules.jsonl
PYTHONPATH="src;experiments/exp06-finetune" python experiments/exp17-planted-eval/predict.py --checkpoint <재학습 폴더> --out preds_teacher.jsonl
PYTHONPATH="src;experiments/exp06-finetune" python experiments/exp17-planted-eval/predict.py --checkpoint <재학습 폴더> --rules --out preds_teacher_rules.jsonl

python experiments/exp17-planted-eval/score.py preds_*.jsonl
```

리눅스(인스턴스)에서는 `PYTHONPATH` 구분자가 `:` 이다.
