# exp12-contribution-approx: 근사기 기여도 평가

## 목적

D의 근사기가 한 번의 추론으로 낸 글별 기여도 순위를 C3 LOO 정답과 비교한다.

- 주 지표: 인물별 Spearman 순위상관의 매크로 평균 (목표 0.8 이상)
- 보조 지표: 인물별 상위 3개 글 일치율의 매크로 평균
- 제외: LOO `baseline_risk == 0`인 인물

## 입력

`--gold`는 `data/corpus/v0/gold/contribution/<persona_id>.json` 디렉터리다.
`--predictions`에도 같은 파일명으로 근사기 결과를 둔다. 파일 내용은
`approximator_targets()`와 같은 목록이다.

```json
[
  {"post_id": "A01_b09", "delta": -7.1, "rank": 1},
  {"post_id": "A01_b11", "delta": -4.2, "rank": 2}
]
```

`post_id` 집합은 정답과 정확히 같아야 한다. `rank`는 1부터 글 수까지 중복 없이
이어져야 한다. `delta`는 출력 계약 호환을 위해 받으며, 평가는 명시된 `rank`로 한다.

## 실행

```bash
python experiments/exp12-contribution-approx/score.py \
  --gold data/corpus/v0/gold/contribution \
  --predictions <D의-근사기-출력-디렉터리> \
  --out experiments/exp12-contribution-approx/results/metrics.json

python -m pytest -q experiments/exp12-contribution-approx/test_score.py
```

실제 근사기 출력 평가는 D 산출물이 나오는 W9에 실행한다. 현재 테스트는 LOO 순위를
조금 뒤섞은 가짜 출력을 사용해 지표 계산, 기준선 0 제외, 입력 불일치 실패를 고정한다.
