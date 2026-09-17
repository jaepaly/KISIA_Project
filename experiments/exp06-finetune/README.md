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
최종 v1 체크포인트 선정과 격리 test 평가, CPU 지연 측정은 별도로 진행한다.
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

- 현재 변환기는 학습 데이터만 만든다. blind·IAA 정답을 합친 최종 평가셋
  로더는 검수가 완료된 뒤 별도로 연결한다.
- `level`과 `subject`는 BIO 유형에 합치지 않고 원본 `spans` 메타데이터로
  보존한다. 등급별 평가는 예측 BIO를 문자 스팬으로 복원한 뒤 계산한다.
- 성능 수치는 아직 없다. 이 README의 결과 부분은 첫 학습 잡 뒤 실제
  측정일·데이터 버전·모델 버전·하드웨어와 함께 갱신한다.
