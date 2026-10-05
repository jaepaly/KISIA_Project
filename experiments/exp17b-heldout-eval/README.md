# exp17b-heldout-eval: 최종 판정용 평가셋 — **한 번만 채점**

## 1. 왜

exp17(#311)은 1단 오답을 들여다봤고(#312 숫자 함정 거름을 그 결과로 만듦), 학습 변이 글 exp19(#313)와 **같은 설계**에서 나왔다. exp17 로 변이 글 재학습을 재면 오르는 게 당연해 일반화를 과대평가한다. 그래서 **변이 글 재학습의 효과는 exp17b 로만 주장한다.**

## 2. 규칙 (프로토콜)

1. 데이터는 아래 해시로 **고정**한다. 바꾸지 않는다
   `data/posts.jsonl` SHA-256 = `7aa1b05e433b444b819bd27342101fcb3938b3bb809ba24a5647e4b970d83b10`
2. 채점은 #313 재학습 결과가 나온 뒤 **한 번만** — 비교할 구성(기존 재학습+규칙 · 변이 글 재학습+규칙)을 같은 날 함께
3. 오답을 열어 규칙·모델을 고치지 않는다. 고치면 그 뒤의 수치는 exp17b 로 주장하지 않는다
4. 결과는 **묶음별**로 따로 본다 — 노리지 않은 변이에서도 오르면 일반화, 노린 변이에서만 오르면 설계에 맞춰진 효과

## 3. 무엇을 만들었나

| | |
|---|---|
| 글 | 80편 · Gemini (`gemini-flash-lite-latest` 78 · `3.6-flash` 1 · `3.7-flash` 1) — exp17 생성기 그대로 |
| 정답 | 심은 표현의 위치 (문자열 일치) — 사람·Claude 라벨 없음 |
| 단서 145 | **노린 변이 · 새 값 52** (숫자 나이 · 반말 어미 · 한글 수사 · 시·구 · 동 · 금액 · 역 · 상가 · 직업명 · 노선 · 버스) · **노리지 않은 변이 65** (출생 연도 「93년생」 · 연령대 「40대 초반」 · 「환갑을 앞두고」 · 생활권 별칭 「분당 · 잠실」 · 시도 정식 「경상남도」 · 랜드마크 · 지점명 「이마트 연수점」 · 직업 묘사 · 시가·처가 호칭 · 배우자 별칭 「집사람 · 바깥양반」 · 광역버스 · 자차 · 실수령 · 구어 금액) · **타인 함정 28** |
| 숫자 함정 | 22편 — 「열두 시」 「마흔 페이지」 「스물두 걸음」 「서른 개」 「쉰 번」 |
| 겹침 | exp17(개발 평가셋) · exp19(학습 변이 글)의 표현·정답 스팬과 겹침 0 — 「일산」 「송도」가 걸려 「잠실」로 바꿈 |

`score.py --data experiments/exp17b-heldout-eval/data/posts.jsonl` 은 `recall_by_group`(targeted · untargeted · trap)을 함께 낸다.

## 4. 전수 검토 (2026-10-06, D) — 정답이 틀어진 단서 4개 제외

1단 오답이 아니라 **Gemini 가 지정 표현을 의도와 다르게 쓴 것**만 봤다. 글은 그대로 두고 그 단서에 `excluded`(이유)를 달아 채점에서 뺀다 — 채점 대상 141개.

| 글 | 단서 | 이유 |
|---|---|---|
| P17B_013 | 납품 트럭 (본인 직업) | 비유로 씀 — 「마치 … 납품 트럭처럼」 |
| P17B_040 | 롯데월드타워 (본인 시설) | 물건을 보낸 곳 — 글쓴이가 간 곳이 아님 |
| P17B_043 | 봉급 350만 원 (본인 소득) | 「받는 날이 오면 좋겠다」 — 실제 소득이 아닌 바람 |
| P17B_044 | 처제랑 (본인 가족) | 「친구가 처제랑 찍은 사진」 — 친구의 처제로 읽힘 |

## 5. 한계

- 사람 글이 아니다(LLM). 정밀도는 참고치(심지 않은 단서가 섞임)
- 141단서 — 묶음별 칸은 52 · 61 · 28 로 작다. 묶음 간 차이가 몇 %p 이하면 우연 범위로 본다

## 6. 채점 (#313 뒤에 한 번)

```bash
export PYTHONIOENCODING=utf-8 PYTHONPATH="src:experiments/exp06-finetune"   # 리눅스
D=experiments/exp17b-heldout-eval/data/posts.jsonl
python experiments/exp17-planted-eval/predict.py --data $D --checkpoint <기존 재학습> --rules --out preds_base.jsonl
python experiments/exp17-planted-eval/predict.py --data $D --checkpoint <변이 글 재학습> --rules --out preds_aug.jsonl
python experiments/exp17-planted-eval/score.py --data $D preds_base.jsonl preds_aug.jsonl
```
