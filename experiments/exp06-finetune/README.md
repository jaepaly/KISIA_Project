# exp06: KoELECTRA 1단 파인튜닝

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
