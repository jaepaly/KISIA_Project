# exp25-contribution-closed-form: 기여도 근사기 대신 닫힌 식

README W9 D 8번 「기여도 근사기 학습」의 결과다. **근사기를 학습하지 않는다** (PM 결정 10/13 (가)). 지금 위험도 함수에서는 LOO 기여도가 학습 없이 한 번의 계산으로 **정확히** 나오기 때문이다.

## 1. 왜 학습할 것이 없나

근사기의 목적은 「LOO(글을 하나씩 빼고 위험도를 다시 계산) 없이 한 번에 글별 기여도 순위를 낸다」였다 (D 매뉴얼 · #124 ①).
그런데 C2 위험도 `risk_total`(`src/kopl/c2_specificity/engine.py`)은 이렇게 계산된다.

- 7축(location · age · sex · occupation · family · commute · income) 각각에서 **가장 구체적인 조건 하나**의 점수만 쓴다 (`risk_by_axis` — 같은 축의 조건을 곱하거나 더하지 않는다)
- 7축 점수를 **같은 가중치로 평균**한다 (`WEIGHTS` 전부 1.0)

그래서 글 p 를 뺐을 때의 변화는 축마다 독립이다.

```
delta(p) = risk(p 를 뺀 나머지) − risk(전체)
         = −(1/7) × Σ축 [ 전체 글의 그 축 최고점 − p 를 뺀 나머지 글의 그 축 최고점 ]
```

글마다 축 점수 7개를 한 번씩 구하면, 모든 글의 delta 가 위 식으로 바로 나온다. p 가 어떤 축의 최고점을 **혼자** 갖고 있을 때만 그 축이 delta 에 들어간다 — 같은 단서가 다른 글에도 있으면 그 글을 내려도 위험도가 그대로인 이유가 이것이다.

## 2. 확인

입력은 LOO 정답을 만든 것과 같다 — 골드 스팬(`scripts/gen_contribution_targets.load_spans`) · test 255편 제외.

| 확인 | 결과 |
|---|---|
| 정답 파일(`data/corpus/v0/gold/contribution/` · 79명 · 331편)과 글마다 delta 비교 | **331/331 일치** |
| 지금 엔진으로 LOO 를 그 자리에서 다시 돌린 값과 비교 (`test_closed_form.py`) | **331/331 일치** (0.01 이내) |
| 79명 전체 계산 시간 (이 PC · 5회 평균) | LOO 207.8ms · 닫힌 식 15.1ms |

학습하지 않으므로 고를 것(특징 · 모델 · 하이퍼파라미터)이 없다. 그래서 위 대조는 「모델을 정답에 맞춰 본 것」이 아니라 「식이 LOO 와 같은 계산인지」의 확인이다.

**LOO 자체가 이미 싸다** — 인물 한 명에 평균 2.6ms 다. 글 n 편이면 위험도 계산이 n+1 번인데, 한 번이 축 7개의 최댓값을 고르는 일이라 근사할 만큼 무겁지 않다.

## 3. C 에게 넘기는 것 (exp20)

`predictions/<persona_id>.json` 79개 — exp20 이 읽는 모양(`approximator_targets` 와 같음 · `rank` 는 abs(delta) 내림차순 · 동률 post_id 오름차순).
인물 단위 교차검증은 필요 없다 — 학습하는 값이 없어서, 어느 인물의 예측도 다른 인물의 정답을 보지 않는다. 학습/평가 인물 목록 대신 「79명 전부 평가」다.

```bash
# 예측 다시 만들기 (정답과 다른 글이 있으면 종료 코드 1)
PYTHONIOENCODING=utf-8 PYTHONPATH="src;scripts" python experiments/exp25-contribution-closed-form/closed_form.py
# exp20 채점 (C)
python experiments/exp20-contribution-approx/score.py --gold data/corpus/v0/gold/contribution \
  --predictions experiments/exp25-contribution-closed-form/predictions \
  --out experiments/exp20-contribution-approx/results/metrics.json
```

> Linux · macOS 에서는 `PYTHONPATH="src:scripts"` (콜론).

## 4. 한계 · 범위

- **이 식은 지금 `risk_total` 의 모양에 기대고 있다.** 축끼리 곱하거나, 같은 축의 조건을 여러 개 합치거나, k 값(인구 교차표)으로 위험도를 바꾸면 축별로 나뉘지 않아 식이 성립하지 않는다. 그때는 LOO 를 그대로 쓰거나 근사기를 다시 검토한다
- 확인한 것은 **골드 스팬 경로**(정답을 만든 길 — 글마다 `build_conditions`)다. 앱 경로(`apps/analyzer/engines/c23.py` · `conditions_from_posts` + `leave_one_out`)는 따로 대조하지 않았다. 앱은 LOO 를 그대로 쓰고, LOO 가 이미 빠르므로 바꿀 이유도 없다
- 정답 파일은 지금 main 의 `loo.py` 반올림을 따른다. [#351](../../../../pull/351) 이 머지되면 `delta` 반올림 방식이 바뀌어 0.01 차이가 생길 수 있다(순위 지표에는 영향 없음 · 테스트는 0.01 허용)

## 5. 결론

- D 성공 기준 「기여도 근사기」는 **「필요 없음 — 닫힌 식이 LOO 와 같고, LOO 도 충분히 빠르다」**로 닫는다. 앱은 LOO 그대로
- 정리서에는 「학습된 근사기」가 아니라 「위험도 함수가 축별로 분해되어 기여도를 한 번에 정확히 계산할 수 있음을 확인했다」로 쓴다
