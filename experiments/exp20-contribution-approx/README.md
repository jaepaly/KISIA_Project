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

## 실행

```bash
python experiments/exp20-contribution-approx/score.py \
  --gold data/corpus/v0/gold/contribution \
  --predictions <D의-근사기-출력-디렉터리> \
  --out experiments/exp20-contribution-approx/results/metrics.json

python -m pytest -q experiments/exp20-contribution-approx/test_score.py
```

실제 근사기 출력 평가는 D 산출물이 나오는 W9에 실행한다. 현재 테스트는 0·동률·상수,
잘못된 타입, rank/delta 불일치와 부호 오류를 포함한 가짜 출력으로 평가 계약을 고정한다.
