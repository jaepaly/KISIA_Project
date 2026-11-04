# B 인계 — 수정 라벨로 XLM-R-large 학습·비교

담당 **B · @philotti**. 지금 모델보다 큰 인코더가 탐지를 개선하는지 확인하는 **별도 실험**이다. 이 PR은 실행 코드·합성 라벨·고정 평가 기준을 넘긴다. **XLM-R-large 본 학습은 B가 실행한다.** 공식 앱·계약·공식 골드·제출 수치는 변경하지 않는다.

## B가 할 일

1. PR 브랜치를 받고 아래 `doctor → prepare → train → evaluate`를 순서대로 실행한다.
2. 학습 중 OOM이 나면 원인을 남기고 **새 출력 폴더**에서 다시 시작한다. 실패한 실행을 성공한 실행처럼 이어 붙이지 않는다.
3. 평가 결과·선택 정보를 반환하고, 선택된 체크포인트는 기존 팀 비공개 전달 경로로 D에게 전달한다. D가 로컬에서 실제 블로그를 비교한다.

실제 블로그 원문·예측·로컬 체크포인트는 이 PR에 없다. **합성 글 원문도 중복 복사하지 않는다.** 기존 `data/corpus/v0/posts/`에서 복원하고 2,583개 글의 텍스트 해시를 대조한다. 패키지 파일과 원문이 달라지면 실행이 중단된다.

## 왜 이 실험인가

KoELECTRA 학습풀 2,281편 중 238편의 누락·유형·경계를 제한적으로 수리했다. 라벨은 **2,483 → 2,706스팬**이다. 원문을 늘리거나 test 글을 학습에 넣은 실험은 아니다. 워커 3명이 도메인별로 제안하고 교차검수·최종 검토를 거쳤다. 전체 코퍼스를 새로 완전 재라벨했다고 주장하지 않는다.

큰 모델은 `FacebookAI/xlm-roberta-large`(약 5.6억 파라미터)로 고정한다. [공개 모델](https://huggingface.co/FacebookAI/xlm-roberta-large)은 MIT 라이선스이며 다운로드·추가 학습에 모델 사용료나 API 호출료가 없다. PC/GPU·클라우드 자원 비용은 별개다. 공개 다운로드에 HF 토큰은 필수가 아니다.

모델 revision은 [`manifest.json`](manifest.json)의 **`c23d21b0620b635a76227c604d44e43a9f0ee389`**로 고정했다. 모델 크기뿐 아니라 사전학습 언어·토크나이저·구조도 바뀐다. 따라서 결과를 **파라미터 수만의 인과 효과**라고 해석하지 않는다.

## 환경과 메모리

- Python **3.11**, CUDA가 되는 PyTorch. 프로젝트 [requirements](../../requirements.txt)·[설치 안내](../../docs/setup-python.md)를 따른다. 기존 측정 환경을 바꾸지 않도록 별도 환경을 권장한다.
- 저장소 기록상 B의 RTX 5070은 Blackwell이므로 **CUDA 12.8 이상을 지원하는 PyTorch 빌드**가 필요하다. 실제 장치·여유 VRAM은 아래 명령으로 확인한다. VRAM을 임의로 24GB라고 가정하지 않는다.
- 기본 **microbatch 1 × accumulation 16**, FP16 autocast, gradient checkpointing으로 시작한다. 가중치 전체를 미세조정하며 LoRA 실험이 아니다.
- 필요하면 `batch-size 2 / accumulation 8` 등 유효 배치 16을 유지하는 조합을 **실행 전에** 정한다. 실제 GPU에서 학습 가능 여부·소요 시간은 아직 측정하지 않았다. 메모리가 부족해도 코드가 모델·정밀도·배치를 몰래 바꾸지 않는다.
- 첫 학습은 공개 가중치를 다운로드한다. 준비 단계는 **tokenizer만** 다운로드한다. 이후 캐시가 있으면 HF offline 환경변수를 사용할 수 있다.

```powershell
python --version
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

## 실행 — 저장소 루트, PowerShell

아래는 CPU가 아닌 **B의 GPU에서 본 학습**하는 명령이다. macOS/Linux에서는 환경변수 설정 문법만 셸에 맞게 바꾸면 된다.

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = 'src'
$exp = 'experiments/exp44-xlmr-handoff'

# 데이터·해시·누수·라벨 검사. --gpu는 장치 이름도 표시한다.
python -X utf8 "$exp/handoff.py" doctor --gpu

# XLM-R tokenizer로 BIO를 새로 만든다. KoELECTRA의 BIO를 재사용하면 안 된다.
python -X utf8 "$exp/handoff.py" prepare --output-dir "$exp/runs/bio-xlmr"

# 전체 20epoch 후 내부 dev 최고 모델을 선택한다. GPU 본 학습.
python -u -X utf8 "$exp/train_large.py" --bio-dir "$exp/runs/bio-xlmr" --output-dir "$exp/runs/xlmr-large" --epochs 20 --batch-size 1 --accumulation 16 --device cuda

# 완료된 선택 모델 하나로만 평가한다. 규칙 off / threshold 0.7 고정.
python -u -X utf8 "$exp/handoff.py" evaluate --run-dir "$exp/runs/xlmr-large" --bio-dir "$exp/runs/bio-xlmr" --device cuda
```

각 명령이 **성공한 것을 확인한 뒤 다음 명령**을 실행한다. 실패 후 같은 출력 폴더를 덮어쓰지 않는다. 이 러너는 중단 실행의 optimizer/RNG를 복구하는 resume 기능을 제공하지 않는다. 평가 폴더가 이미 있으면 재추론을 거부한다. 저장된 결과가 있으면 그 파일을 읽고, 평가 실패의 재실행이 필요하면 먼저 원인을 기록한다.

## 고정 조건과 검증

- 동일한 수정 라벨 **2,281편 / 2,706스팬**, 원문은 기존 합성 데이터만 사용한다.
- 기존 실험과 같은 **인물 단위 내부 dev 10% / seed 20260911**. dev 인물 9명은 manifest에 고정돼 있고 다시 대조한다. XLM-R 토큰화로 창 수는 바뀌어도 글·인물 분할은 바뀌지 않는다.
- 20epoch, AdamW lr `1e-5`, weight decay `.01`, O weight `.02`, 유효 batch 16, 길이 256 / stride 64. 단일 seed 실험이다.
- accumulation은 microbatch별 평균을 단순 평균하지 않는다. **그룹 전체 유효 토큰의 class-weight 합**으로 weighted CE 합을 나눠 배치의 양성 비율 차이를 반영한다. 미완성 마지막 그룹도 실제 분모를 쓴다.
- 매 에폭 내부 dev partial F1을 측정해 최고를 선택한다. 동점이면 앞선 에폭이다. test·추가 63편·실제 블로그는 체크포인트·임계값 선택에 쓰지 않는다.
- `best/` 하나만 저장하고 optimizer를 20벌 남기지 않는다. 전체 요청 에폭이 완료돼야 `selection.json`을 발행한다. OOM이면 `completed:false`이고 선택 파일을 발행하지 않는다.
- 선택 모델의 config·tokenizer·weights 및 준비 데이터 해시를 재검사한다. raw BIO의 경계·유형만 평가하며 `level`·`subject` 정확도를 주장하지 않는다.

## 후속 — 큰 모델용 학습 설정 (선택 · 위 실행이 끝난 뒤)

위 기본 명령은 KoELECTRA 실험과 같은 설정(lr `1e-5` 고정 · 웜업/감쇠 없음 · 클리핑 없음 · seed 1개)이다. XLM-R-large 같은 큰 인코더는 이 설정에서 학습이 흔들리기 쉬워, 기본 실행 결과만으로 「큰 모델이 안 좋다」고 결론 내리지 않는다. 비교를 공정하게 하려면 아래를 **추가로** 돌린다.

- `--schedule linear --warmup-ratio 0.1` — 전체 optimizer step 의 10% 동안 lr 을 `1e-5 / 웜업step` 에서 `1e-5` 까지 올리고, 이후 선형으로 줄여 마지막 업데이트 뒤 0 이 된다. 웜업 step 은 전체보다 항상 1 이상 적게 잡힌다. fp16 overflow 로 건너뛴 업데이트에서는 스케줄이 진행하지 않는다
- `--max-grad-norm 1.0` — fp16 scaler 를 푼(unscale) 실제 그래디언트의 노름을 1.0 으로 자른다
- `--train-seed N` — 학습 쪽 난수(분류 헤드 초기화 · 학습 순서 · dropout)를 바꾼다. **dev 인물 9명 분할은 seed `20260911` 로 고정**이라 seed 를 바꿔도 dev 는 같다

옵션을 주지 않으면 기존 러너(커밋 `1cb782d`)와 학습 경로가 같다 — 테스트가 tiny 모델로 두 러너의 최종 가중치 해시와 에폭별 loss 가 같은지 대조한다. 기록 JSON 에 필드가 몇 개 늘어난 것만 다르다. 이미 돌고 있는 실행은 영향 없다. 기본 실행이 끝난 뒤, 출력 폴더를 seed 마다 새로 만들어 3번 돌린다.

```powershell
foreach ($s in 1, 2, 3) {
  python -u -X utf8 "$exp/train_large.py" --bio-dir "$exp/runs/bio-xlmr" --output-dir "$exp/runs/xlmr-large-sched-s$s" --epochs 20 --batch-size 1 --accumulation 16 --device cuda --schedule linear --warmup-ratio 0.1 --max-grad-norm 1.0 --train-seed $s
  if ($LASTEXITCODE -ne 0) { break }
  python -u -X utf8 "$exp/handoff.py" evaluate --run-dir "$exp/runs/xlmr-large-sched-s$s" --bio-dir "$exp/runs/bio-xlmr" --device cuda
  if ($LASTEXITCODE -ne 0) { break }
}
```

- 걸리는 시간: 기본 실행의 「에폭당 시간 × 20」 × 3 정도. 급하지 않다 — 11/8 제출과 무관한 실험이다
- 반환: 각 폴더의 `selection.json`(선택 에폭 · dev F1)과 `evaluation/metrics.json`. 비교는 **seed 3개의 평균과 최소~최대**로 하고, 가장 좋은 seed 하나만 골라 보고하지 않는다
- 기록: `run_metrics.json` 의 `training_config`(실패한 실행에도 남는다)와 `selection.json` 의 `training_config` 에 `schedule` · `warmup_steps` · `total_optimizer_steps` · `max_grad_norm` · `train_seed` 가 남는다. `run_metrics.json` 의 에폭별 `history[].train` 에는 `skipped_steps`(fp16 일 때 · overflow 로 건너뛴 업데이트) · `clipped_steps`(클리핑을 켰을 때) · `lr_end`(스케줄을 켰을 때 · 에폭 끝 lr) 가 남는다
- 해석: 참고값으로 KoELECTRA 수정 모델의 내부 dev F1 은 **0.7345**(같은 수정 라벨 · 같은 dev 인물 9명(200편 · 정답 243스팬 = 그 실행의 tp+fn 과 일치) · typed partial F1 · threshold 0.7 · 규칙 off · 20epoch 중 20epoch 선택 · tp 195 / fp 93 / fn 48)다. 단 이 값은 **단일 seed 실행이고 dev 를 선택에도 쓴 최고값**이며 실행 기록은 저장소 밖 PM 로컬에 있다. 그래서 XLM-R 세 seed 와의 차이는 「이 설정 · 이 dev 에서 관찰한 차이」로만 적는다. 모델 계열의 우열을 말하려면 KoELECTRA 도 같은 seed 반복이 필요하다

## 평가 기준 — 유리한 정답만 골라 보고하지 않는다

| 이름 | 글 수 | 스팬 | 용도 |
|---|---:|---:|---|
| `official239` | 239 | 358 | 기존 공식 정답에 대한 **raw 모델** 진단 |
| `previous_ai239` | 239 | 428 | 앞서 통일한 AI 라벨 관례에 얼마나 맞는지 |
| **`conservative239`** | **239** | **454** | 기존의 명백한 오류만 보수적으로 수정한 주 비교 기준 |
| **`adjudicated63`** | **63** | **70** | 학습·기존 test 밖 글을 무작위 추출한 추가 비교 기준 |
| `annotator_a63 / b63 / c63` | 각 63 | 61 / 79 / 65 | 같은 추가 글에 대한 세 독립 AI 원자료의 민감도 점검 |

평가 원문은 **239 + 63 = 302편을 한 번씩** 추론하고 7개 정답으로 재채점한다. 기준은 계약과 같은 **유형 일치 + 문자 IoU ≥ 0.5, 1:1 매칭**이다. exact는 참고치다. 유형별 정답 30건 미만은 `sample_insufficient`를 표시한다.

`official239`의 조사 미포함 등 알려진 경계 오류와 `conservative239`의 미해결 경계는 **진단 기준으로 보존**했다. doctor는 이 평가 경계를 경고로 집계하고 학습 라벨의 경계는 엄격히 검사한다. 평가 정답을 새 모델에 맞춰 고치지 않는다.

### 이미 측정한 KoELECTRA 비교 값

모두 규칙 off / threshold .7 / 전체 partial F1이다. 상세 고정 값은 [`baselines.json`](baselines.json)에 있다.

| 기준 | 이전 clean | 수정 KoELECTRA |
|---|---:|---:|
| 공식 239 | .3690 | .4013 |
| 이전 AI 239 | .7954 | .7533 |
| 보수 수정 239 | .5893 | .6062 |
| 추가 63 | .7153 | .7361 |

이는 **공식 앱의 동결 체크포인트 + 명시 규칙 전체와 직접 비교한 결과가 아니다.** 기존 기준선 raw 모델은 별도 재학습한 실험 모델이다. base는 학습 10epoch, clean·수정 모델은 각각 20epoch 예산에서 dev로 선택했다. 합성239의 기존 base/clean 예측은 CPU, 수정 모델 예측은 CUDA였다. 추가63편은 세 모델 모두 CUDA였다. 근소한 부동소수점 경계 차이를 따로 분리하지 않았다.

### 해석 한계

학습 수리 전에 기존 test의 오류 유형을 이미 관찰했다. 보수 수정 정답과 추가63편도 사람·작성자 검증 골드가 아닌 **AI 탐색용 기준**이다. 추가63편은 21인물에서 각 3편을 무작위 선택했고 세 워커가 예측 없이 독립 주석한 뒤 불일치 24곳을 원문 검토해 고정했다. 새 글이어도 같은 합성 코퍼스·일부 기존 test와 같은 인물이므로 외부 사용자 일반화 검증이 아니다. 추가63편은 INCOME 정답이 0개라 소득 탐지 향상을 검증할 수 없다. 라벨 수리는 경계·범위·유형·양성 감독량을 함께 바꿨다.

큰 모델의 정확도가 좋아져도 CPU 지연·메모리와 앱의 귀속·규칙·2단 연동은 별도 확인해야 한다. **자동으로 공식 모델을 교체하지 않는다.**

## B가 반환할 것

공유 가능한 진단 결과:

- `runs/xlmr-large/evaluation/metrics.json`
- `runs/xlmr-large/selection.json`, `run_metrics.json`
- `runs/bio-xlmr/prepare_manifest.json` 및 실제 실행 명령
- GPU 이름·VRAM·PyTorch/CUDA/Transformers 버전, 실패/OOM 또는 명령 변경 여부
- `git rev-parse HEAD`로 확인한 실행 커밋 SHA

선택된 **`best/` 폴더 전체**(config·tokenizer·weights)는 팀 비공개 경로로 전달한다. 파일 일부만 보내면 해시 검증에 실패한다. 모델 가중치·체크포인트·optimizer·원본 로그를 public PR/이슈에 붙이지 않는다. 결과 수치를 공개할 때도 로컬 경로·환경의 자격증명이 섞이지 않았는지 확인한다.

`data/`는 합성 글의 라벨 복사본이며 **공식 `data/corpus/v0/gold/`를 대체하지 않는다.** 새 측정값은 기존 제출 값 옆에 실험으로 기록한다.

## 전달 전 로컬 검증

```powershell
python -X utf8 experiments/exp44-xlmr-handoff/handoff.py doctor
python -X utf8 -m unittest discover -s experiments/exp44-xlmr-handoff/tests -v
```

로컬 확인 결과는 [`verification.json`](verification.json)에 있다. 실제 고정 XLM-R tokenizer로 **6,737창 / 2,706스팬 왕복 exact·bad 0**을 확인했고, tiny random XLM-R의 CPU 학습→선택→302편·7기준 평가→재평가 거부까지 연결했다. tiny 검증은 실제 대형 모델의 성능 측정이 아니다.

전용 CI는 모델 다운로드 없이 doctor와 가벼운 데이터·채점 테스트를 실행한다. 전체 16개 테스트의 학습·gradient accumulation·OOM 경로는 로컬 CPU에서 검증했다(후속 학습 설정 옵션 테스트 6개를 더해 지금은 22개). 로컬 라이브러리 버전과 저장소 설치 핀의 차이도 verification에 기록했다. **5.6억 모델 본 학습·성능·B GPU 메모리 적합성은 아직 검증하지 않았다.**
