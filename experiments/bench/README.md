# 벤치마크 러너 — 1단 (W9 · 10/29 최종 측정용)

현재 범위는 1단만이다. 2단·위험도·조치는 D가 `metrics.json`의 `extensions`에
추가한다. 모델·규칙·임계값을 고르는 도구가 아니며 재학습·자동 탐색을 하지 않는다.
최종 test는 10/29 확정 구성으로 한 번만 실행한다. 지금은 **train 일부로 동작만 확인**한다.

## 입력·출력

- 체크포인트, `--rules on/off`, `--threshold`(기본 0.7), CPU 스레드 수를 받는다.
  기본 데이터는 train 검수 20편이다. `--limit`은 train 검증에서만 허용한다.
- test는 `--split test --final-test-confirm`으로 명시적으로 확인해야 한다.
  고정 ID 255개와 `test.jsonl` SHA-256 `9662a167…`을 검사하고,
  기존 평가기의 IAA 제외·blind 우선/clue·검수/noise 정책을 그대로 써서 239편을 평가한다.
- 출력은 **새로운 `experiments/**/runs/` 폴더**에 `metrics.json`과 `predictions.jsonl`이다.
  기존 폴더는 덮어쓰지 않는다. 예측 파일에는 post_id·candidates를 쓰며 탐지 없는 글도 남긴다.
- 체크포인트 SHA-256, 학습 BIO 지문(체크포인트에 저장된 경우), 실제 골드 파일 지문,
  규칙·속성 판정·앱 병합·평가 코드 커밋과 파일 해시, 측정일·환경을 기록한다.
  예전 결과와 골드 level 관례가 달라도 구분할 수 있다.

## 지표의 뜻

| metrics.json 항목 | 의미 |
|---|---|
| `c1.boundary_type.partial` / `exact` | 기존 공식 경계·유형 채점. partial은 type 일치 + IoU ≥ 0.5 탐욕 1:1, exact는 참고치 |
| `c1.proxy.partial_by_level` / `exact_by_level` | 명시·암묵·추론의 **골드 등급**별 TP·FN·R, 전체 정밀도 공유 P와 proxy F1. partial에는 #276 보수적 참고 F1도 포함 |
| `c1.resolved_level.partial` / `exact` | 경계·유형에 더해 **resolve()가 판정한 level도 일치**해야 TP인 end-to-end P/R/F1, 전체와 등급별. 독립 level 분류 정확도가 아니며 subject는 매칭 조건이 아님 |
| `c1.implicit_iaa` | 2차 IAA의 공개 반올림값 44.4% 대비 proxy·등급 판정 포함 F1의 참고 비율/백분율. 다른 표본·정의라 사람 대비 성능 확증이 아님 |
| `additional_detection` | exp01 세 도구 합집합의 미탐 중 현재 모델+선택 규칙이 회수한 수/비율. 기존 도구는 type 불문·1:1 제한 없음, 모델은 공식 type 일치·탐욕 1:1 |
| `cpu_latency.model_only` / `app_full` | #301 모델 detect(계약 검증·임시 속성 포함)와 앱 detect(선택 규칙 병합·resolve 포함)를 **같은 표본**으로 별도 측정 |

해당 등급의 골드가 없으면 R/F1은 null이며, 표본이 있는 등급의 TP가 0이면 F1은 0이다.
지연은 #301의 길이순 구간 중앙 표본 알고리즘을 재사용한다. 최종 test에서는 같은 20편,
글마다 워밍업 5회·측정 50회, 1편씩 호출한다. 분포는 **글별 중앙값의 중앙값·p95(nearest-rank)·최대**다.
모델 로딩은 제외하고 창 배치 수를 따로 적는다. train smoke에서 줄인 반복값은 최종 지연이 아니다.

## 오늘 실행할 검증 — test 아님

저장소 루트의 PowerShell에서 실행한다. torch·transformers와 로컬 체크포인트,
Presidio·spaCy·`ko_core_news_sm`이 필요하다. 기존 도구가 없거나 Presidio가
대체 엔진으로 폴백하면 중단한다. 가중치 다운로드·LLM 호출은 하지 않는다.

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="src;experiments/exp06-finetune"; python experiments/bench/run.py --checkpoint-dir experiments/exp06-finetune/runs/variant_base_20261008/checkpoint-epoch-10 --split train --limit 4 --rules on --threshold 0.7 --threads 4 --latency-samples 2 --warmup 1 --repeats 2 --output-dir experiments/bench/runs/smoke_v2_rules_20261014
```

규칙 끔 ablation은 위 명령의 `--rules off`와 **다른 출력 경로**를 사용한다.
개발 환경에 기존 도구가 없으면 `--skip-baselines`, 측정 없이 채점 조립만 보면
`--skip-latency`를 쓸 수 있지만 `status: not_measured`로 남는다. test에서는 skip을 금지한다.
train 검수 부분집합 점수는 학습과 겹치므로 일반화 성능으로 보고하지 않는다.

모델 없는 단위 테스트:

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="src;experiments/exp06-finetune"; python -m unittest discover -s experiments/bench -p test_run.py -v
```

## 10/29에만 실행할 최종 명령

아래는 1단 전체 지표를 한 번에 모으는 명령이다. D의 다른 단계 연결 후에도
고정 입력·같은 1단 옵션·새 결과 경로를 유지한다. 지금은 실행하지 않는다.

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="src;experiments/exp06-finetune"; python experiments/bench/run.py --checkpoint-dir experiments/exp06-finetune/runs/variant_base_20261008/checkpoint-epoch-10 --bio-data experiments/exp06-finetune/runs/bio_variant_base_20261008/train.jsonl --split test --final-test-confirm --rules on --threshold 0.7 --threads 4 --output-dir experiments/bench/runs/final_v2_20261029
```

기존 `measure_additional_rate.py` CLI는 W7 v1 저장 결과 재현용으로 유지한다.
새 러너는 그 모듈의 `run_baselines`와 모델 버전 제한 없는 `score_additional_rate` 경로를
사용하므로 v2·규칙 결합 예측도 같은 미탐 정의로 평가한다.

관련: [README B 2번](../../README.md), [#276](../../../../issues/276),
[#301](../../../../pull/301), [#322](../../../../issues/322).
