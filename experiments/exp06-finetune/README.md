# exp06: KoELECTRA 1단 파인튜닝

## infer.py — BIO 추론과 계약 출력의 경계

`infer.py`의 `SpanDetector`는 로컬 체크포인트를 한 번 로드해 재사용한다.
CPU 기본, NFC 채널별 offset, 256토큰·stride 64 슬라이딩 윈도우,
긴 스팬 우선 겹침 해소, 동일 스팬의 창별 평균 점수 필터를 적용한다.
임계값 0.7은 #255 후속 결정에 따른 잠정값이며 옵션으로 변경 가능하다.

- `predict_raw(record)`: 경계·유형·점수와 정규화된 `texts`를 반환한다.
  `output_kind=raw_bio_candidates_not_contract`이며 계약 출력으로 전달하면 안 된다.
- `detect(record, resolver=...)`: JSON Schema 및 의미 검증을 거쳐 계약 출력을 반환한다.
  판정 함수를 생략하면 W2 승인된 기존 detector의 `implicit/self` 고정값을 잠정 유지하고 경고한다.
- 판정 함수의 형태: `resolver(texts, candidate) -> {"level": ..., "subject": ...}`.
  외부 판정 함수를 전달하면 기존 고정값을 대체할 수 있다.
- 모델은 21-label BIO로 등급·주체를 학습하지 않았다. 고정값은 **모델 판정도 계약이 지정한 값도 아니다**.
  타인 단서까지 `self`, 명시·추론 단서까지 `implicit`로 출력될 수 있다.
  후속 소비자는 이 값을 실제 귀속·등급 판정으로 신뢰하면 안 된다. 골드를 조회하지 않는다.
  미수행 플래그도 거짓 음성으로 채우지 않고 생략한다.
- 프로필은 `record_type=profile`, `persona_id`, `profile_bio`로 별도 입력한다.
  글의 `texts`에는 title/body/photo_caption:N만 넣는다. 사진 색인의 빈자리는 유지한다.

실행 예시(PowerShell):

```powershell
python experiments/exp06-finetune/infer.py --checkpoint-dir experiments/exp06-finetune/runs/v1_lr5e-5/checkpoint-epoch-10 --post '{"post_id":"demo_b01","body":"집 근처 신갈저수지 다녀왔어요"}'
python experiments/exp06-finetune/test_infer.py
```

PR에서 확인할 설계 판단: W2 기존 동작과의 호환을 위해 등급·주체 고정값을 잠정 유지했다.
이 고정값을 유지할지, 별도 판정 로직을 연결할지 리뷰 요청한다.
**계약 출력 구조는 지원하지만 등급·주체의 실제 판정은 미구현**이다.
격리 test 평가와 합성 예문 CPU 예비 측정은 아래에 기록했다.
최종 v1 체크포인트 선정·registry 등록은 별도로 진행한다.
test를 반복적인 임계값 튜닝에 사용하지 않는다. 계약 파일·기존 src 탐지기는 변경하지 않았다.

### 내부 eval 추론 일치 검증 (2026-09-17)

```powershell
python experiments/exp06-finetune/check_infer_parity.py --checkpoint-dir experiments/exp06-finetune/runs/v1_lr5e-5/checkpoint-epoch-10
```

corpus-v0 p2.3 · KoELECTRA 기존 LR 5e-5 epoch 10 체크포인트 · CPU 4스레드 ·
임계값 0.7로 내부 eval 95개 창/84채널(복수 창 11채널)을 비교했다.
저장 BIO와 재토큰화 불일치 0채널, 예측 스팬 불일치 0채널.
점수 최대 절대 차이는 0.00000201로 허용 오차 0.00001 이내다
(배치 패딩 구성 차이에 따른 미세 부동소수점 차이까지 동일하다고 주장하지 않는다).
두 경로 모두 TP 30 / FP 32 / FN 32, partial F1 0.4839를 재현했다.
실제 모델로 긴 본문·제목·사진 캡션(색인 2·10)·별도 프로필도 실행하고 offset 일치를 확인했다.
프로필 fixture에서는 후보가 0건이었다. 검증 중 격리 test는 열지 않았다.
이는 BIO 추론 경로의 일치 검증이며 등급·주체 판정 정확성을 검증한 것이 아니다.

## 무엇을 왜 재는가

### 공식 test 평가 — 기존 IAA 제외 (2026-09-17 팀 승인)

`evaluate_test.py`는 공식 `splits/test.jsonl`을 변경하지 않고 기존
`gold/iaa/_assignment.json`에 배정된 test ID만 제외한다.
현재 255편 중 IAA 16편을 제외한 **239편·358스팬**이다.
IAA 배정 ID 중복·16편 개수 불일치·공식 test 내 배정 ID 누락은
즉시 오류로 중단한다. 교집합만 취해 일부 제외하는 동작은 허용하지 않는다.
단서 159편은 `gold/blind/`의 reviewed 정답, 잡담 80편은 최상위
`gold/`의 reviewed 정답을 사용한다. 중복 일반 검수본보다 blind를 우선한다.
잡담 80편 중 빈 정답은 8편뿐이며, 나머지 72편의 실제 단서는 유지한다.
교사 원본 및 기존 IAA A·C 정답은 평가 입력으로 사용하지 않는다.

```powershell
python experiments/exp06-finetune/evaluate_test.py --audit-only
python experiments/exp06-finetune/test_evaluate_test.py
python experiments/exp06-finetune/evaluate_test.py --checkpoint-dir experiments/exp06-finetune/runs/v1_lr5e-5/checkpoint-epoch-10 --device cuda --min-span-score 0.7 --output-dir experiments/exp06-finetune/runs/test_v1_lr5e-5_t07
```

원문·NFC·offset·정답 누락과 공식 split 및 실제 BIO 입력의 글 ID 누수를
먼저 검사한다. 누락 정답을 빈 정답으로 취급하지 않는다.
2026-09-17 audit에서 학습 글 ID 누수 0건이었으나 인물은 66명 겹친다.
기존 체크포인트는 당시 학습 데이터 해시를 저장하지 않았으므로 현재 BIO
누수 검사만으로 과거 학습 입력의 동일성까지 보장하지 않는다.

주 지표는 type 일치 + partial IoU ≥ 0.5 스팬 F1이며 유형별·글 kind별로
함께 출력한다. `level`·`subject`는 모델 예측이 아니므로 평가하지 않는다.
내부 eval에서 선정한 체크포인트와 잠정 임계값 0.7을 고정해 평가하고,
test에서 임계값 탐색을 반복하지 않는다. 출력은 gitignore된 `runs/`에
`metrics.json` 및 비계약 raw `predictions.jsonl`로 저장하며 기존 폴더가
있으면 덮어쓰지 않는다. 모델 로딩을 제외한 평가 실행 시간은 CPU 지연
벤치마크가 아니다. audit-only는 데이터 검증이며 모델 test 성능 측정은 아니다.

실행 결과(2026-09-17 · corpus-v0 p2.3 · KoELECTRA
`v1_lr5e-5/checkpoint-epoch-10` · CUDA · 임계값 0.7):
239편·358스팬에서 TP 111 / FP 286 / FN 247,
precision 0.2796 / recall 0.3101 / partial F1 **0.2940**.
참고 exact 1:1 채점은 TP 61 / FP 336 / FN 297,
precision 0.1537 / recall 0.1704 / exact F1 **0.1616**이다.
exact 지표는 저장된 동일 예측에서 재채점했으며 모델 추론을 반복하지 않았다.
원래 출력은 보존하고 보완 지표를 `runs/test_v1_lr5e-5_t07_exact/metrics.json`에 기록했다.

```powershell
python experiments/exp06-finetune/evaluate_test.py --rescore-from experiments/exp06-finetune/runs/test_v1_lr5e-5_t07 --output-dir experiments/exp06-finetune/runs/test_v1_lr5e-5_t07_exact
```

내부 eval F1 0.4839와 별개로 기록하며 최종 목표 성능 달성으로 해석하지 않는다.

### v1 확정 보류 — epoch 1~10 내부 eval 비교

`checkpoint-epoch-10`은 현재 평가한 후보이며 최종 v1 확정은 보류한다.
기존 LR 5e-5 epoch 1~10을 동일한 내부 persona eval·겹침 해소·임계값 0.7로
비교하는 `compare_internal_epochs.py`를 추가했다. 재학습 없이 저장 모델을
로드해 평가하며 격리 test·blind·IAA 정답은 열지 않는다.
2026-09-17 · corpus-v0 p2.3 · 동일 KoELECTRA LR 5e-5 실행의 저장 모델을
CUDA에서 내부 eval 95개 창·84채널·62골드 스팬으로 비교했다.
seed 20260911, 동일 persona holdout 0.100, 겹침 해소와 임계값 0.7을 고정했다.

| epoch | partial F1 | exact F1 | P | R | TP / FP / FN |
|---|---|---|---|---|---|
| 1 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 / 0 / 62 |
| 2 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 / 0 / 62 |
| 3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 / 0 / 62 |
| 4 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 / 0 / 62 |
| 5 | 0.2326 | 0.1860 | 0.4167 | 0.1613 | 10 / 14 / 52 |
| 6 | 0.3434 | 0.2222 | 0.4595 | 0.2742 | 17 / 20 / 45 |
| 7 | 0.3789 | 0.2947 | 0.5455 | 0.2903 | 18 / 15 / 44 |
| 8 | 0.3111 | 0.1926 | 0.2877 | 0.3387 | 21 / 52 / 41 |
| 9 | 0.4274 | 0.3248 | 0.4545 | 0.4032 | 25 / 30 / 37 |
| 10 | **0.4839** | **0.4194** | 0.4839 | 0.4839 | 30 / 32 / 32 |

이 실행의 epoch 1~10 중 주 지표와 참고 exact 모두 epoch 10이 최고다.
따라서 기존 epoch 10 후보를 유지하며 최종 v1 확정은 리뷰 승인 대기다.

```powershell
python experiments/exp06-finetune/compare_internal_epochs.py --run-dir experiments/exp06-finetune/runs/v1_lr5e-5 --device cuda --output-dir experiments/exp06-finetune/runs/internal_epoch_compare_t07
```

결과는 `metrics.json`과 `comparison.md`로 새 폴더에 저장한다.
test를 연 뒤 수행하는 내부 eval 비교라는 시점을 명시한다.
다른 epoch가 최선이어도 이미 공개한 test를 사용해 재비교하지 않는다.
epoch 10 test·CPU 결과를 다른 모델의 측정 결과로 옮겨 쓰지 않는다.

### CPU 예비 지연 측정 (2026-09-17)

corpus-v0 p2.3로 학습한 동일 KoELECTRA 체크포인트
`v1_lr5e-5/checkpoint-epoch-10`, 임계값 0.7,
AMD Ryzen 5 9600X 6-Core Processor, CPU 4스레드.
모델 로딩 2.81초는 지연 통계에서 제외했다.
입력별 워밍업 5회 후 30회 측정했고, p95는 nearest-rank(정렬 후 29번째)다.

| 합성 입력 | 문자 수 | 창 수 | 평균 ms | 중앙값 ms | p95 ms |
|---|---|---|---|---|---|
| 짧은 글 | 39 | 1 | 21.49 | 20.97 | 24.07 |
| 중간 글 | 195 | 1 | 61.80 | 60.46 | 67.60 |
| 긴 글 | 780 | 2 | 256.40 | 254.35 | 276.31 |

합성 본문 `집 근처 신갈저수지에 다녀왔어요. 퇴근길에 가족과 저녁을 먹었습니다. `
(끝 공백 포함)를 각각 1·5·20회 반복했다.
`SpanDetector.detect({'post_id': 'timing_b01', 'body': text})` 호출 전체를
`time.perf_counter()`로 측정했다. 토큰화·모델·후처리·계약 검증을 포함하고
모델 로딩·파일 저장은 제외한다. 세 fixture의 p95는 모두 300ms 미만이다.
실제 코퍼스 전체의 지연 달성을 보장하는 대표 벤치마크가 아닌 예비 측정이다.
등급·주체는 기존 고정값이고 실제 판정 로직의 실행 비용은 포함하지 않는다.
임시 측정 스크립트는 사용자 요청대로 측정 후 삭제했다.

검수 골드의 문자 offset 스팬을 KoELECTRA 토큰 분류용 BIO 라벨로 바꾸고,
100건 과적합 테스트와 첫 1 epoch 학습이 끝까지 실행되는지 확인한다.
이번 구현은 그중 **BIO 변환·토큰 정렬·역변환 검증**을 담당한다.

## 데이터 경계

- 학습 라벨 정본: `data/corpus/v0/gold/*_spans.jsonl`의 `reviewed: true` 레코드만
- 사용 금지: `gold/detect/` 교사 원본
- 최종 평가 전용: `gold/blind/`, `gold/iaa/`
- `scripts/split_train_test.py`가 만든 `splits/train.jsonl`·`test.jsonl`을 읽어
  blind·IAA 배정 글을 학습에서 제외한다.
- title, body, photo_caption 채널은 서로 offset 기준이 다르므로 각각 하나의
  학습 예제로 만든다.

## 실행

먼저 글 분할을 만든다. 두 JSONL은 생성물이어서 gitignore 대상이다.

```bash
python scripts/split_train_test.py
```

맥북 등 토크나이저가 없는 환경에서는 정본·분할·offset까지만 검사한다.

```bash
python experiments/exp06-finetune/prepare_bio.py --validate-only
```

학습 환경에서는 KoELECTRA fast tokenizer로 변환한다. 긴 본문은 64토큰이
겹치는 슬라이딩 윈도우로 잘라 스팬 손실을 막는다.

```bash
python experiments/exp06-finetune/prepare_bio.py
```

기본 출력은 gitignore된 `experiments/exp06-finetune/runs/bio/`에 생긴다.

| 파일 | 내용 |
|---|---|
| `train.jsonl` | 토큰화된 창, BIO `labels`, 원문 offset과 골드 스팬 |
| `labels.json` | 고정된 21개 라벨과 id 매핑 |
| `metrics.json` | 입력·격리 수, 왕복 exact/near/bad, 손실 스팬 |

단위 테스트:

```bash
python experiments/exp06-finetune/test_prepare_bio.py
```

## 판정

- 특수 토큰은 `-100`, 일반 비스팬 토큰은 `O`여야 한다.
- 토큰과 문자 스팬이 조금이라도 겹치면 해당 스팬의 BIO 라벨을 붙인다.
- 문자 스팬 → BIO → 문자 스팬 왕복의 `bad`가 10% 이상이면 학습을 중단한다.
- 토큰 경계 때문에 조사까지 붙는 `near`는 정상이며 `metrics.json`에 남긴다.

## 다음 단계

GPU 데스크탑에서 생성된 `train.jsonl`로 먼저 100건 과적합 테스트(F1 ≥ 0.9)를
한 뒤 전체 1 epoch를 실행한다. 체크포인트 재개까지 확인해야 첫 학습 잡 완료다.

## 한계

- 변환기는 학습 데이터만 만든다. 격리 test 평가는 `evaluate_test.py`로
  별도 연결하며 위 팀 승인대로 기존 IAA 배정 글을 제외한다.
- `level`과 `subject`는 BIO 유형에 합치지 않고 원본 `spans` 메타데이터로
  보존한다. 등급별 평가는 예측 BIO를 문자 스팬으로 복원한 뒤 계산한다.
- 성능 수치는 아직 없다. 이 README의 결과 부분은 첫 학습 잡 뒤 실제
  측정일·데이터 버전·모델 버전·하드웨어와 함께 갱신한다.
