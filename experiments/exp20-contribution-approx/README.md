# exp20-contribution-approx: 근사기 기여도 평가

## 목적

D의 근사기가 한 번의 추론으로 낸 글별 기여도를 C3 LOO 정답과 비교한다.

- 주 지표: 인물별 `abs(delta)` Spearman의 매크로 평균 (목표 0.8 이상)
- 보조 지표: 계약 rank 기준 top-3 일치율, 동률 허용 top-3 재현율, 부호 정확도, signed delta MAE
- 제외: LOO `baseline_risk == 0`인 인물

`abs(delta)` 값을 쓰면 기여도 0인 글끼리 `post_id`로 갈린 계약 순서를 품질로 오인하지 않는다.
정답 delta가 모두 같은 인물은 ρ 산정 불가로 따로 집계한다. 정답은 비상수인데 예측만
상수이면 근사기가 순위를 만들지 못한 것이므로 ρ=0 실패로 포함한다.

## 입력과 검증

`--gold`는 `data/corpus/v0/gold/contribution/<persona_id>.json` 디렉터리다.
`--predictions`에도 같은 파일명으로 근사기 결과를 둔다. 파일 내용은
`approximator_targets()`와 같은 목록이다.

```json
[
  {"post_id": "A01_b09", "delta": -7.1, "rank": 1},
  {"post_id": "A01_b11", "delta": -4.2, "rank": 2}
]
```

- `post_id` 집합은 정답과 정확히 같아야 한다.
- `delta`는 bool이 아닌 유한한 숫자, `rank`는 bool이 아닌 정수여야 한다.
- `rank`는 `abs(delta)` 내림차순, 동률은 `post_id` 오름차순으로 1부터 이어져야 한다.
- 골드는 `input.method == "loo"`이고 `input.post_ids`가 contributions와 일치해야 한다.

계약 rank 기준 top-3는 정확히 세 ID를 비교한다. 동률 허용 지표는 골드 3위와 같은
`abs(delta)`인 글을 모두 정답 후보로 인정한 뒤 예측 top-3 중 몇 개가 후보에 드는지 잰다.

top-3 두 지표는 **글이 4편 이상인 인물만** 잰다 — 3편 이하면 「상위 3편」이 곧 전체라 어떤 예측도 만점이다.
동률 허용 후보에서는 **기여 0인 글을 뺀다** — 실제 LOO 정답은 평가 대상 66명 중 63명이 「0 아닌 글」 3편 미만이라,
0끼리 동률로 묶으면 3위 경계값이 0이 되어 글 전체가 정답 후보가 된다. 분모는 후보 수(최대 3)다.
수정 전에는 순서를 완전히 뒤집은 예측도 동률 허용 0.97·rank 0.80 이 나왔다 (ρ 는 −0.78 로 정상).

## 실행

```bash
python experiments/exp20-contribution-approx/score.py \
  --gold data/corpus/v0/gold/contribution \
  --predictions <D의-근사기-출력-디렉터리> \
  --out experiments/exp20-contribution-approx/results/metrics.json

python -m pytest -q experiments/exp20-contribution-approx/test_score.py
```

## 실제 산출물 평가 (2026-10-13~14)

D는 학습 근사기 대신 현재 위험도 함수의 축별 최댓값 구조를 이용한 닫힌 식을 제출했다
([exp25](../exp25-contribution-closed-form/README.md) · #352). 학습하는 값이 없으므로
인물 단위 교차검증은 적용하지 않는다.

| 기준 | 결과 |
|---|---|
| #352 제출 스냅샷 | baseline 0인 13명을 제외한 66명 · 331편의 delta와 rank가 LOO 정답과 모두 일치 |
| 순위 지표 | 정의 가능한 인물의 `abs(delta)` Spearman ρ = **1.0** |
| 보조 지표 | 값과 순서가 모두 같으므로 부호 정확도 1.0 · signed delta MAE 0 |
| 최신 main 재생성 | **미확정** — `382718a`에서 `E20_b28` 1편 불일치로 생성기가 종료 코드 1 |

최신 main의 불일치는 #351의 C3 반올림 변경 뒤 확인됐다. 커밋된 LOO 정답과 #352 예측은
`E20_b28 = -4.29`로 같지만, 현 `build_conditions`로 닫힌 식을 다시 계산하면
`-7.86`이다. 따라서 **#352 제출 스냅샷에 대한 평가는 ρ=1이지만, 현행 엔진 기준 최종
근사기 평가는 확정하지 않는다.** contribution 골드를 현행 조건 변환 기준으로 재생성할지,
해당 FAM 스팬의 의도된 resolution을 고정한 뒤 다시 생성·채점해야 한다.

평가 계약 테스트는 0·동률·상수, 잘못된 타입, rank/delta 불일치와 부호 오류를 포함한다.
