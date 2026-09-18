# 파도풀 — 공개 게시글 누적·결합에 따른 재식별 위험 자가진단 및 보호조치 추천 시스템

KISIA 2026 AI 보안기술개발 · 개인정보 트랙 3팀 · 2026-08-17 ~ 11-06 (12주) · 담당 멘토 권영길

> 흩어진 글이 쌓이고 서로 결합하면서 발생하는 재식별 위험을 진단하고,
> **가장 적은 부담으로 되돌릴 수 있는 조치를 추천**한다. 탐지는 **외부 전송 없이 이용자 기기에서** 수행한다.

---

> ## 📌 이 문서는 **이번 주에 할 일**만 다룬다
>
> | 찾는 것 | 문서 |
> |---|---|
> | **이번 주 내가 뭘 해야 하나** | **여기 (아래)** |
> | 내 역할 전체 (12주) | [docs/roles/](docs/roles/) |
> | 프로젝트가 뭔지 | [docs/overview.md](docs/overview.md) |
> | 계획 전문 | [docs/plan.md](docs/plan.md) |
> | 주차별 일정·게이트 | [docs/roadmap.md](docs/roadmap.md) |
> | 협업 규칙 (브랜치·커밋·리뷰) | [CONTRIBUTING.md](CONTRIBUTING.md) |
> | **골드셋 형식** | [docs/contracts/label-schema.md](docs/contracts/label-schema.md) §8 · §9 |
> | **절대 하면 안 되는 것** | [docs/RULES-DO-NOT.md](docs/RULES-DO-NOT.md) |
> | **팀 대시보드 (로컬)** | `python scripts/open_dashboard.py` — gh CLI 필요 ([설치](https://cli.github.com/)) · `gh auth login` 최초 1회 |

---

## 지금 상태

**W4 설계서·골드셋 완료, 파인튜닝·통합 W5 착수** — [compare/w03...w04](../../compare/w03...w04)

| 항목 | W4 끝 |
|---|---|
| 코퍼스 | **v1 동결** ✅ 115명 3,092편 · d4cf8cb · 9/9 |
| 골드셋 검수 | **417편 587스팬** ✅ A·B·D·E 4명 · [gold/README.md](data/corpus/v0/gold/README.md) · 9/11 |
| blind 200 | ✅ 머지 완료 (159편 267스팬) · 9/14 (#229) |
| IAA | 1차 27.0% ✅ · **2차 완료 ✅** overall 50.0% (explicit 51.9% · implicit 44.4% · inferential 20.0% · 공통 16편 · 9/17) |
| 1단 파인튜닝 | train.py ✅ (#239) · **과적합 F1 0.9157** · 전체 1 epoch F1 0.0602 · o_weight 진단 (#240) |
| 2단 QLoRA | 첫 잡 ✅ dev loss 0.005 · 함정 배제 15/18 (#214) |
| 지명 사전 | UNKNOWN 18→2 ✅ · 픽스처 19/19 (#218) |
| 가상 SNS | v0 + **시딩** ✅ (#237) |
| 설계서 | ✅ 제출 완료 9/10 |
| `w04` 태그 | ✅ 9/11 |

| 역할 | 담당 | **이번 주 핵심** |
|---|---|---|
| **[A · 데이터 리드](docs/roles/A-data.md)** | 이은선 | ~~test set 결정~~ ✅ #244 + ~~IAA 2차~~ ✅ #248 + ~~네거티브 보강~~ ✅ #249 |
| **[B · 1단 탐지](docs/roles/B-detector.md)** | 최진필 | **v1 확정 ✅** (#263 · checkpoint-epoch-10 · p95 276ms) |
| **[C · 특정성·누적](docs/roles/C-specificity.md)** | 신정현 | ~~IAA 2차~~ ✅ #250 + ~~기여도 엔진 v1~~ ✅ #251 |
| **[D · 2단 추론·조치](docs/roles/D-stage2.md)** | 박재현 (PM) | **가명화·복원 계층 ✅** + 3ep adapter v1 확정 ✅ (#264) |
| **[E · 시스템·컴플라이언스](docs/roles/E-system.md)** | 이지희 | **분석 웹앱 3화면 연결** + 수동 업로드 |

---

# W5 (9/14~9/18) — 각자 할 일

**제출물**: 주간활동보고서 (외부)
**단계**: **M2-b 통합 1차** · 근무일 5일

> ## 이번 주 한 문장 — **파인튜닝 수렴 경로를 찾고, 분석 화면을 목 엔진으로 먼저 연결한다.**
>
> 로드맵 §3:
>
> W5는 B가 학습 v1을 확정하고, E가 통합을 조기 착수하는 주다. C의 기여도 엔진 v1도 시작한다.
> **다음 주(W6)가 추석 연휴 — 근무일 3일.** B·D는 학습 epoch 소요 시간을 먼저 확인하고, 연휴를 걸쳐야 할 만큼 오래 걸리는 경우에만 금 말일에 tmux 잡을 띄운다.

---

## 0. 화요일 팀 회의 — 21:00, 30분

### 먼저 받기

```bash
git pull
pip install -e .
```

### 화요일에 정할 것 둘

#### ① ~~test set 구성 방향 (W4 이월)~~ ✅ 결정 완료 (9/14 · #244 머지)

| 선택지 | 내용 | 장단점 |
|---|---|---|
| **(가)** blind 검수분 재활용 | 현재 `gold/blind/` 스팬을 test로 | 빠르지만 blind 조건 논란 가능 |
| **(나)** 새 소음 표본 | 단서 0 글에서 새로 뽑아 A가 라벨 | 깔끔하지만 시간 추가 |
| **(다)** 교사 라벨 그대로 | `gold/detect/` 를 test에 직접 | 빠르지만 라벨 품질 낮음 |

**A가 (가) 계열로 결정** — 검수 정본의 negative_control 잡담 80편을 test에 추가 (#244 머지 · test 255편 = clue 175 + noise 80). 각자 `python scripts/split_train_test.py` 재실행해서 새 분리로 맞춘다.

#### ② ~~C blind 200 재제출 (#229)~~ ✅ 머지 완료 (9/14)

#229 머지 완료 — 팀 회의에서 IAA 2차 착수 일정 확인으로 전환.

---

## W4 이월 항목

| 항목 | 담당 | 상태 |
|---|---|---|
| ~~blind 200 재제출 (계약 5건 수정)~~ | C | ✅ #229 머지 완료 (9/14 · 159편 267스팬) |
| ~~test set 구성 방향 결정~~ | A · PM | ✅ (가) 잡담 80편 test 추가 · #244 머지 (9/14) |
| ~~IAA 2차 (A·C 20편)~~ | A · C | ✅ 완료 — overall F1 50.0% (9/17 · #248 · #250) |
| ~~`label-schema` #223 §3-2 배우자 호칭 1줄~~ | A | ✅ #245 머지 (9/14 · v1.1) |

---

## 전원 공통 — 주간보고서 (수 23:59)

이번 주 **외부 제출물은 주간활동보고서 하나**다. 설계서는 W4에 제출 완료.

```
1. 이번 주 내 목표:
2. 실제로 한 일:
3. 달라진 것 (before → after, 숫자):
4. 증빙 링크:
5. 막힌 것 + 필요한 지원:
```

원고는 드라이브 — PM(재현)에게 **수 23:59** 까지 보낸다. (KISIA 줌 주간보고회 월 11:15에 발표)

---

## 전원 공통 — 로컬 대시보드 실행

저장소가 9/14 비공개 전환 이후 GitHub Pages가 중단됐다. **gh CLI 스냅샷 기반**으로 로컬에서 동일한 대시보드를 열 수 있다.

### 1회 설정

```bash
# 1) gh CLI 설치 (없는 경우만)
#    Windows: winget install GitHub.cli
#    macOS:   brew install gh

# 2) GitHub 인증 (최초 1회)
gh auth login
# → GitHub.com / HTTPS / 브라우저 로그인 선택 후 완료
```

### 대시보드 열기

```bash
# 저장소 루트에서
python scripts/open_dashboard.py
```

`site/index.html`이 생성되고 브라우저가 자동으로 열린다.

> ⚠️ 브라우저에서 새로고침(F5)해도 데이터가 바뀌지 않는다. 최신 현황을 보려면 스크립트를 다시 실행해야 한다.

---

## A · 이은선 — 라벨 품질관리 · 네거티브 보강

> 전체 매뉴얼 [docs/roles/A-data.md](docs/roles/A-data.md)

### ~~test set 방향 결정~~ ✅ 완료 (9/14 · #244)

[위 팀 회의 §①](#-test-set-구성-방향-w4-이월--담당-a--pm) 표 참고:

| 선택지 | 내용 | 비고 |
|---|---|---|
| **(가)** | `gold/blind/` 스팬을 test로 재활용 | 빠르지만 blind 조건 논란 가능 |
| **(나)** | 단서 0 글에서 새로 뽑아 A가 라벨 | 깔끔하지만 추가 시간 필요 |
| **(다)** | `gold/detect/` 교사 라벨 그대로 | 빠르지만 라벨 품질 낮음 |

✅ (가) 계열로 결정·구현 완료 — 검수 정본 negative_control 잡담 80편을 seed 고정으로 test에 추가 (#244 머지 · #235 닫힘). 한계(blind 아님·인물 겹침)는 `split_meta.json` note에 기록됨.

### 월~화 — split 누수 검증 (✅ #230 W4 머지 완료)

`scripts/split_train_test.py` 와 `data/corpus/v0/splits/` 는 **W4 에 완료** (`#230` 머지됨). 이번 주는 새로 작성하지 않는다.

#244 머지 시 누수 검사(train·test 교집합 0) 통과 확인됨. B에게 split 재실행만 안내하면 된다.

**누수 검사 (반드시 통과)**:

```bash
# Git Bash 전용 (PowerShell 대안은 아래)
python - <<'EOF'
import json
train_ids = {json.loads(l)["post_id"] for l in open("data/corpus/v0/splits/train.jsonl")}
test_ids  = {json.loads(l)["post_id"] for l in open("data/corpus/v0/splits/test.jsonl")}
leak = train_ids & test_ids
print("누수 0건" if not leak else f"⚠️ 누수 {len(leak)}건: {list(leak)[:5]}")
EOF
```

```powershell
# PowerShell 대안
python -c "
import json
train_ids = {json.loads(l)['post_id'] for l in open('data/corpus/v0/splits/train.jsonl')}
test_ids  = {json.loads(l)['post_id'] for l in open('data/corpus/v0/splits/test.jsonl')}
leak = train_ids & test_ids
print('누수 0건' if not leak else f'누수 {len(leak)}건')
"
```

### ~~화 — label-schema §3-2 수정~~ ✅ 완료 (9/14 · #245)

```bash
# 수정 위치 확인
grep -n "배우자\|호칭" docs/contracts/label-schema.md
```

✅ 완료 — [#223](../../issues/223) 합의안(SEX/implicit 고정·explicit 격상 금지)을 §3-2에 추가, #245 머지 (9/14 · label-schema v1.1).

### ~~수~목 — IAA 2차 준비~~ ✅ 완료 (9/17 · #248 #250 · overall 50.0%)

C의 #229가 9/14 머지됐다. IAA 2차 표본을 C와 함께 뽑는다.

```
IAA 2차 절차:
1. C #229 머지 완료 ✅ (9/14)
2. gold/iaa/_assignment_v2.json 생성 — 새 20편 표본 (seed 기록)
   (기준: explicit/implicit/inferential 등급 분포 층화)
3. A·C 각자 독립 라벨링
   → gold/iaa/A_spans_v2.jsonl
   → gold/iaa/C_spans_v2.jsonl
4. scripts/iaa.py 로 등급별 F1 계산
5. 결과 이슈 등록
```

### ~~수~목 — 네거티브 보강 (roadmap A W5 항목)~~ ✅ 완료 (9/15 · #249)

test set 방향과 무관하게 진행한다. 네거티브 컨트롤(신상 단서 없는 글)이 학습 데이터에 충분히 포함되어야 모델이 "잡담 글에서 오탐"을 내지 않는다.

- 현재 gold/에 reviewed=true + 스팬 0 인 글이 몇 편인지 확인
- 10% 이하면 A-data.md **§1·§2** 기준대로 소음 글 추가 라벨 (§1: 네거티브 컨트롤 전체의 10~15%, §2: 노이즈 70~80%)

```bash
python -c "
import json, pathlib
gold_dir = pathlib.Path('data/corpus/v0/gold')
zero_span = sum(
    1 for f in gold_dir.glob('*_spans.jsonl')
    for rec in [json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l]
    if rec.get('reviewed') and not rec.get('spans')
)
print(f'스팬 0 검수 글: {zero_span}편')
"
```

### 만들 것

```
data/corpus/v0/gold/iaa/A_spans_v2.jsonl  IAA 2차 (C #229 완료 후)
```

### 완료 기준

- [x] test set 구성 방향 결정 + 구현 (#244 머지 · 9/14)
- [x] split 누수 검증 통과 + B 에게 경로 공유 (#244 머지 시 통과 · 9/14)
- [x] `label-schema` #223 §3-2 배우자 호칭 — #245 머지 (9/14)
- [x] IAA 2차 라벨링 완료 + 등급별 F1 계산 (#248 #249 #250 머지 · overall 50.0% · 9/17)

---

## B · 최진필 — 1단 v1 학습

> 전체 매뉴얼 [docs/roles/B-detector.md](docs/roles/B-detector.md) · [howto/b-finetune.md](docs/roles/howto/b-finetune.md)

### ⭐ 이번 주 B 의 핵심 문제 — o_weight와 F1

W4에서 학습 잡을 돌린 결과가 갈렸다:

```
과적합 모드 (26편, --overfit 26):  F1 0.9157  ← 모델은 배울 수 있다
전체 1 epoch:                      F1 0.0602  ← 학습이 안 된다
```

**진단**: O 클래스 불균형. 토큰의 99.2%가 `O`(Outside)라 모델이 "전부 O로 찍기"를 택한다. `--o-weight 0.01`이 과적합에서는 작동했지만 전체 데이터에서는 부족하다.

**이번 주 목표**: o_weight 최적값을 찾아 전체 epoch eval F1 ≥ 0.25를 달성한다.

### ~~학습 전 — split 재실행 (#244 반영)~~ ✅ 완료 (9/15)

✅ train 2,837편 / test 255편, 누수 0건 확인 후 BIO를 재생성했다.
학습 검수 정본 311편·464스팬 → 801개 창, 왕복 exact 464/464·손실 0건.
내부 persona 분리 train 706 / eval 95개 창으로 아래 탐색을 진행했다.

#244 머지로 test에 잡담 80편이 추가됐다 (train 2,917 → 2,837). **`python scripts/split_train_test.py` 재실행 후 학습**해야 noise 80편이 train에서 빠진다 — splits 는 meta만 커밋되고 jsonl은 로컬 생성이다.

A의 분리 결과 사용법:

```bash
python experiments/exp06-finetune/prepare_bio.py \
  --gold-dir   data/corpus/v0/gold \
  --posts-dir  data/corpus/v0/posts \
  --split      data/corpus/v0/splits/train.jsonl \
  --out        experiments/exp06-finetune/data/train_bio.jsonl
```

### ~~월~화 — o_weight 그리드 탐색~~ ✅ 완료 (9/15)

순서대로 하나씩 돌린다 (병렬로 돌리면 GPU 공유로 결과가 섞인다).

```bash
for OW in 0.005 0.01 0.02 0.05; do
  python experiments/exp06-finetune/train.py \
    --data   experiments/exp06-finetune/data/train_bio.jsonl \
    --output experiments/exp06-finetune/runs/v1_ow${OW//./} \
    --o-weight $OW \
    --epochs 5 \
    --batch 16 \
    --lr 2e-5
done
```

| o_weight | eval F1 epoch3 | eval F1 epoch5 | 비고 |
|---|---|---|---|
| 0.005 | 0.1157 | 0.1717 | |
| 0.01 | 0.1167 | 0.2081 | W4 기준 |
| 0.02 | 0.0905 | **0.2257** | 최고 F1 · 수요일 LR 탐색 기준 |
| 0.05 | 0.0617 | 0.2198 | |

5 epoch 탐색에서는 목표 F1 0.25를 넘긴 설정이 없었다. 가장 높은 F1은
`o_weight=0.02`의 0.2257이며, 이를 수요일 learning-rate 탐색의 기준값으로 사용한다.

**멈추는 기준**: eval F1이 2 epoch 연속 내려가면 그 직전 체크포인트가 best.

### ~~수 — 학습률·배치 세컨더리 스윕 (o_weight 확정 후)~~ ✅ 완료 (9/16 · batch 16 고정, LR 3종 비교)

```bash
# o_weight 최적값이 OW_BEST 라고 할 때
for LR in 1e-5 2e-5 5e-5; do
  python experiments/exp06-finetune/train.py \
    --o-weight $OW_BEST --epochs 10 --lr $LR --batch 16 \
    --output experiments/exp06-finetune/runs/v1_lr${LR}
done
```

| learning rate | 최고 epoch | 최고 eval F1 | 비고 |
|---|---|---|---|
| 1e-5 | 10 | 0.2269 | 목표 미달 |
| 2e-5 | 9 | 0.3235 | 목표 달성 |
| 5e-5 | 10 | **0.3690** | 최적 후보 |

측정: 2026-09-16 · corpus-v0 p2.3 · `monologg/koelectra-base-v3-discriminator`.
`o_weight=0.02`, batch 16, 10 epochs, fp16, 동일 persona 단위 train/eval 분리
(706/95개 창)로 각 LR을 처음부터 순차 실행했다. 평가는 type 일치 + partial match(IoU ≥ 0.5) 스팬 F1이다.

LR `5e-5`의 `runs/v1_lr5e-5/checkpoint-epoch-10`을 최적 후보로 선정했다
(P 0.2925 · R 0.5000 · TP 31 · FP 75 · FN 31).
내부 eval 목표 F1 ≥ 0.25를 달성했다. 위 수치는 당시 후처리 기준의 이력으로 유지한다.

`analyze_errors.py`로 오탐·미탐과 예측 점수를 분석하고, `train.py`에
동일 텍스트 채널의 겹침을 긴 스팬 우선으로 해소하는 처리와 `--min-span-score`를 추가했다.
임계값은 스팬을 구성하는 예측 토큰 확률의 평균(동일 스팬은 창별 점수의 평균)에 적용하며,
학습 손실을 바꾸지 않는다. 이 점수는 보정된 정답 확률이 아니다.

| 실행 | 후처리 | 내부 eval F1 | P | R | TP / FP / FN |
|---|---|---|---|---|---|
| 9/16 기존 체크포인트 | 당시 기준 | 0.3690 | 0.2925 | 0.5000 | 31 / 75 / 31 |
| 같은 체크포인트 재평가 (추가 학습 없음) | 겹침 해소 + 임계값 0.7 | **0.4839** | 0.4839 | 0.4839 | 30 / 32 / 32 |
| deterministic 새 학습 A·B, epoch 10 | 겹침 해소 + 임계값 0.7 | **0.4516** | 0.4516 | 0.4516 | 28 / 34 / 34 |

측정: 2026-09-17 · corpus-v0 p2.3 · `monologg/koelectra-base-v3-discriminator` ·
동일 내부 persona train/eval 706/95개 창 · type 일치 + partial match(IoU ≥ 0.5).
새 학습은 o_weight 0.02, LR 5e-5, batch 16, 10 epochs, fp16, seed 20260911로 실행했다.

`--deterministic`은 결정적 연산을 강제하고 eager attention·TF32 비활성화를 적용한다.
데이터·라벨·학습 코드 SHA-256, 학습 설정, 실행 환경을 체크포인트 평가 기록과
`run_metrics.json`에 남긴다. A·B 두 실행의 출력 손실과 epoch별 평가 수치는 모두 일치했다.
가중치 파일 동일성은 아직 확인하지 않았으며, 환경 간 재현성과 체크포인트 재개 시
중단 없는 학습과의 동일성은 보장하지 않는다(현재 재개는 RNG·scaler·shuffle 상태 미복원).

기존 `runs/v1_lr5e-5/checkpoint-epoch-10`은 보존한다.
0.4839는 기존 모델의 후처리 재평가, 0.4516은 새 학습 결과로 구분하며,
모두 내부 eval 수치로 최종 test 성능이 아니다. 최종 v1 선정·등록은 아직 미완료다.
회귀 테스트 18개 및 `git diff --check` 통과. 오탐은 여전히 남아 있어 완전 해결로 보지 않는다.
모델·체크포인트·분석 결과는 `runs/` 로컬 산출물로 유지하며 커밋하지 않는다.

### ~~목 — v1 체크포인트 확정 + models/registry.md 등록~~ ✅ 완료 (9/18 · #263 · checkpoint-epoch-10 · p95 276ms)

```markdown
# models/registry.md 에 추가할 행 예시

| 이름 | 날짜 | 데이터 버전 | eval F1 | CPU 지연 | 경로 |
|---|---|---|---|---|---|
| koelectra-v1 | 2026-09-18 | gold-v4/splits-v1 | 0.xx | xxx ms | experiments/exp06-finetune/runs/v1_best |
```

CPU 지연 측정 (목표 < 300ms):

```python
import time, torch
from transformers import AutoModelForTokenClassification, AutoTokenizer

model_path = "experiments/exp06-finetune/runs/v1_best"
tok = AutoTokenizer.from_pretrained("monologg/koelectra-base-v3-discriminator")
model = AutoModelForTokenClassification.from_pretrained(model_path)
model.eval()

text = "집 근처라 자주 가는 신갈저수지 조황입니다. 마흔여덟 되니 무릎이 예전 같지 않네요."
inputs = tok(text, return_tensors="pt")

t0 = time.perf_counter()
with torch.no_grad():
    _ = model(**inputs)
print(f"{(time.perf_counter()-t0)*1000:.1f} ms")
```

### ~~목~금 — 추론 함수 래퍼 (E에게 넘길 것)~~ ✅ 완료 (9/17 · #260 · infer.py · F1 0.4839 parity)

E가 분석기에 연결할 수 있도록 계약 형식으로 감싼다:

```python
# experiments/exp06-finetune/infer.py

def detect_spans(post: dict, checkpoint_dir: str) -> dict:
    """
    입력: {"post_id": str, "body": str}
    출력: {
      "schema_version": "1.0",
      "post_id": str,
      "spans": [{"start": int, "end": int, "text": str,
                 "type": str, "level": str, "score": float}]
    }
    계약: docs/contracts/span.schema.json
    """
    ...
```

계약 검증:

```bash
pip install check-jsonschema   # 없으면 설치
python experiments/exp06-finetune/infer.py \
  --post '{"post_id":"test","body":"신갈저수지 조황입니다"}' \
  > /tmp/span_result.json
check-jsonschema --schemafile docs/contracts/span.schema.json /tmp/span_result.json
```

### ~~금 말일 — W6 비동기 학습 잡 (조건부)~~ ✅ 불필요 확정 (9/17 · #262 · 1ep=16.57초 · 연휴 tmux 불필요)

**먼저 확인**: o_weight 탐색 1 epoch 실측 시간이 얼마인지. 연휴 3일을 걸쳐야 할 만큼 오래 걸리는 경우에만 tmux 잡을 띄운다. 몇 시간이면 W6 정상 근무일(화~목)에 돌려도 충분.

```bash
# 연휴를 걸쳐야 할 만큼 오래 걸릴 때만 실행
tmux new -s w6_train
python experiments/exp06-finetune/train.py \
  --o-weight <최적값> \
  --epochs 20 \
  --output experiments/exp06-finetune/runs/v1_long \
  --resume-from-checkpoint latest \
  2>&1 | tee logs/v1_long.log
# Ctrl+B → D 로 세션에서 빠져나옴
```

### 만들 것

```
experiments/exp06-finetune/runs/v1_*/     o_weight 실험 결과들
experiments/exp06-finetune/infer.py       추론 함수 래퍼
models/registry.md                        v1 체크포인트 등록
```

### 완료 기준

- [x] o_weight 그리드 탐색 — 전체 eval F1 ≥ 0.25 (LR 후속 탐색에서 0.3690 달성 · 9/16)
- [x] 오탐 분석 + 겹침 해소 + 신뢰도 임계값 0.7 후처리 — F1 0.3690 → **0.4839** (#255 · 9/17 · FP 75→32)
- [x] v1 체크포인트 확정 + CPU 지연 측정 (checkpoint-epoch-10 · 임계값 0.7 · #263 · 9/18 · test F1 0.2940 · p95 276ms < 300ms)
- [x] 추론 함수 `infer.py` — `span.schema.json` 계약 통과 (#260 · 9/17 · F1 0.4839 parity 확인)
- [x] W6 학습 잡 — 1ep=16.57초 확인 · 연휴 tmux 불필요 (#262 · 9/17)

---

## C · 신정현 — 기여도 엔진 v1

> 전체 매뉴얼 [docs/roles/C-specificity.md](docs/roles/C-specificity.md) · [howto/c-engine.md](docs/roles/howto/c-engine.md)

### ⭐ 이번 주 C 의 두 과제

1. ~~**blind 200 재제출 (#229)**~~ — ✅ 9/14 머지 완료 (159편 267스팬)
2. **기여도 엔진 v1** — LOO 정답 생성기 + 증류 타깃. D의 추천 엔진이 이 데이터를 쓴다.

### ~~월~화 — #229 blind 200 재제출~~ ✅ 완료 (9/14)

PR #229 머지 완료. 159편 267스팬 · check_gold --strict 101개 통과 · Codex 2차 검토 통과.

> 이슈 #242: D03_b04_s01 서술어 경계 잔존 기록됨 (267스팬 중 3% · IAA 비교 허용 범위)

### ~~화 — IAA 2차 표본 추출 (A와)~~ ✅ 완료 (9/17 · A·C 라벨링 · overall F1 50.0%)

#229 머지 완료 → IAA 2차 즉시 착수 가능.

```bash
# A가 만들어야 할 스크립트 — 아직 없으면 A에게 요청
python scripts/sample_iaa.py \
  --gold    data/corpus/v0/gold \
  --exclude data/corpus/v0/splits/test.jsonl \
  --n 20 \
  --seed 42 \
  --out data/corpus/v0/gold/iaa/_assignment_v2.json
```

표본이 나오면 A·C가 각자 독립 라벨링한다.

### ~~수~목 — 기여도 엔진 v1 (LOO)~~ ✅ 완료 (9/17 · #251 머지)

**LOO(Leave-One-Out) 기여도가 무엇인가:**

```
글 전체 위험도 = 100.0 (예: k=150 → 위험도 100점)
A11_b07 를 뺐을 때 위험도 = 73.0
→ A11_b07 의 기여도 delta = 100.0 - 73.0 = 27.0
                            (이 글이 빠지면 위험도가 27 내려간다)
```

이 계산을 모든 글에 반복하면 **어느 글이 위험을 가장 많이 만드는지** 순위가 나온다. D의 추천 엔진이 이 순위를 써서 "이 글 3개만 비공개하면 됩니다"를 낸다.

```python
# src/kopl/c3_contribution/loo.py

# c2 엔진의 실제 공개 함수를 확인하고 맞춰 import한다.
# src/kopl/c2_specificity/__init__.py 에서 export하는 함수 중
# k값(또는 위험도 점수)을 반환하는 것을 쓴다.
# 확인 방법: python -c "import kopl.c2_specificity as m; print(dir(m))"
from kopl.c2_specificity import specificity   # k·등급·위험도를 반환하는 주 함수

def extract_attrs(posts: list[dict], spans: list[dict]) -> dict:
    """posts + spans → specificity() 입력 형식으로 변환"""
    ...  # c2_specificity의 입력 스키마(specificity.schema.json)에 맞춤

def loo_contribution(author_id: str, posts: list[dict],
                     spans: list[dict]) -> list[dict]:
    """
    posts: [{"post_id": ..., "body": ...}, ...]  — 이 인물의 전체 글
    spans: [{"post_id":..., "start":..., "type":..., ...}, ...]

    반환: [{"post_id": str, "delta": float, "rank": int}, ...]
      delta > 0 → 이 글을 뺐을 때 위험도가 delta만큼 내려간다
    """
    all_attrs = extract_attrs(posts, spans)
    baseline = specificity(all_attrs)
    baseline_k = baseline["result"]["k"] or 9999.0

    results = []
    for i, post in enumerate(posts):
        remaining_posts = posts[:i] + posts[i+1:]
        remaining_spans = [s for s in spans if s["post_id"] != post["post_id"]]
        attrs_minus = extract_attrs(remaining_posts, remaining_spans)
        result_minus = specificity(attrs_minus)
        k_minus = result_minus["result"]["k"] or 9999.0

        delta = round(risk(baseline_k) - risk(k_minus), 2)
        results.append({"post_id": post["post_id"], "delta": delta, "rank": 0})

    results.sort(key=lambda x: -x["delta"])
    for r, item in enumerate(results):
        item["rank"] = r + 1
    return results

def risk(k: float) -> float:
    """k → 0~100 위험도 점수. k 가 낮을수록 위험."""
    import math
    return max(0.0, min(100.0, 100.0 - 10.0 * math.log10(max(k, 1))))
```

단위 테스트:

```bash
# 3편짜리 소규모로 LOO 방향이 맞는지 확인
python -m pytest tests/test_contribution.py -v
```

### 목~금 — 증류 타깃 세트 생성

LOO 기여도가 나오면 D가 학습할 데이터를 만든다.

```bash
python scripts/gen_contribution_targets.py \
  --gold     data/corpus/v0/gold \
  --personas data/corpus/v0/personas \
  --output   data/corpus/v0/gold/contribution/
```

출력 예:

```json
{"author_id": "A11",
 "posts": [{"post_id":"A11_b07","body":"..."}],
 "contribution": [{"post_id":"A11_b07","delta":27.0,"rank":1},
                  {"post_id":"A11_b02","delta":5.1, "rank":2}]}
```

계약 검증:

```bash
check-jsonschema --schemafile docs/contracts/contribution.schema.json \
  data/corpus/v0/gold/contribution/A11.json
```

### ~~금 — IAA 2차 결과 이슈 등록~~ ✅ 완료 (9/17 · #248 #250 머지 · overall 50.0%)

```bash
python scripts/iaa.py \
  data/corpus/v0/gold/iaa/A_spans_v2.jsonl \
  data/corpus/v0/gold/iaa/C_spans_v2.jsonl
# 등급별 F1 (explicit / implicit / inferential) 출력
```

결과를 이슈로 기록한다. **암묵(implicit) F1 수치가 [목표] 지표의 기준이 된다.**

### 만들 것

```
data/corpus/v0/gold/blind/<pid>_spans.jsonl  (수정본)   blind 200 재제출
data/corpus/v0/gold/iaa/C_spans_v2.jsonl                IAA 2차 라벨
src/kopl/c3_contribution/loo.py                           LOO 기여도 엔진
data/corpus/v0/gold/contribution/<pid>.json               증류 타깃 세트
```

### 완료 기준

- [x] #229 blind 200 머지 완료 (9/14 · 159편 267스팬)
- [x] IAA 2차 라벨링 완료 + 등급별 F1 계산 (#248 #250 머지 · overall 50.0% · 9/17)
- [x] `loo.py` LOO 기여도 — 단위 테스트 통과 (#251 머지 · 9/16 · CI guard pass)
- [ ] 증류 타깃 세트 — `contribution.schema.json` 계약 통과

---

## D · 박재현 — 가명화·복원 계층 (+ PM)

> 전체 매뉴얼 [docs/roles/D-stage2.md](docs/roles/D-stage2.md)

### ⭐ 이번 주 D 의 핵심 — 가명화 모듈

B가 스팬을 찾으면 그 구간을 실제 표현에서 **가명 라벨로 교체**하고, 나중에 다시 원래 표현으로 **복원**한다. 이 단계가 있어야 D의 2단 모델이 원문 지명을 보지 않고 구조만 판단할 수 있다.

### ~~월~화 — 가명화 모듈 구현~~ ✅ 완료 (9/14 · #243 머지)

`src/kopl/c4_stage2/anonymize.py` — `anonymize(text, spans) → (anon_text, key)` / `restore(anon_text, key) → 원문`.

- 정본 10종(§3-2) 유형명 준수 · 정본 외 유형은 `ValueError` 거부
- 가명 토큰은 유일 + 원문에 부분문자열로 부재 → 라운드트립 무조건 보장
- 입력 경계 검증: offset 범위 · `text[start:end]` 일치 · 겹침(§6) 거부
- AGE 는 숫자면 연령대(`[40대]`) 일반화, 출생연도(`1990년생`)·한글 나이는 일반 토큰 폴백

```bash
python -m pytest src/kopl/c4_stage2/test_anonymize.py -v   # 15 passed
```

Codex 2회 + C 리뷰 반영. 설계 상세는 #243.

### ~~수~목 — v1 SFT 빌더 (본문 + 골드 스팬 + anonymize)~~ ✅ 완료 (9/15 · train 342 / dev 30)

⚠️ **v0 학습 입력에는 anonymize 를 연결하지 않는다.** v0 입력(clue_plan 유도, `make_sft.py`)의 스팬 `text` 는 값이 아니라 **단서 구절 전체**라, 통째로 치환하면 등급·subject·함정 판단 근거가 같이 지워진다 (9/14 Codex 검토로 확정).

대신 골드 스팬(#229 까지 머지 · 본문 offset 포함)으로 **v1 SFT 입력**을 만들고 거기에 가명화를 건다:

1. 글 본문 + `gold/<pid>_spans.jsonl` → `anonymize()` → 가명 본문을 모델 입력으로
2. 함정(`통로=`) 정보는 clue_plan 과 조인 — 골드 스팬엔 note 가 없어 설계 필요
3. test 글 제외 기준은 **#244 새 split**을 따른다 (test 255편 = clue 175 + noise 80)
4. train/dev 재생성 후 **QLoRA 재학습(epochs ≥ 3)은 v1 데이터로** — 금 또는 W6 잡

### ~~수 23:59 — 주간보고서 + 팀원 보고 취합~~ ✅ 완료 (9/18 최종 제출)

PM 역할: 팀원 5명 보고 취합 + 막힌 항목 확인 (특히 IAA 2차 진행). 취합본 기준으로 다음날 KISIA 줌 주간보고회(월 11:15) 발표.

### ~~목 21:00 — 멘토링~~ ✅ 완료 (9/17 · 데모 문맥·일정 조율·EC2 이전)

**이번 주 멘토링 안건:**
1. **W6 추석 대응** — B epoch 소요 시간 확인 후 tmux 잡 여부 결정
2. **IAA 2차 결과** — 암묵 F1 수준 보고

### ~~금 말일 — W6 학습 잡 (조건부)~~ ✅ 불필요 확정 (9/18 · 3ep v1 확정 · verdict 90% · #264)

**먼저 확인**: QLoRA 1 epoch 실측 시간. 연휴를 걸쳐야 할 만큼 오래 걸릴 때만 실행. v1 SFT 데이터가 목요일까지 준비되면 **v1(가명화) 데이터로** 돌린다 — 안 되면 v0 로 돌리고 v1 재학습은 W7.

```bash
tmux new -s w6_qwen3
python experiments/exp08-stage2-sft/train.py \
  --epochs 20 \
  2>&1 | tee logs/qwen3_v1.log
# Ctrl+B → D
```

### PM 몫

| 언제 | 무엇 |
|---|---|
| 화 21:00 | 팀 회의 30분 — IAA 2차 착수 일정 / #244 split 재실행 공유 |
| 수 23:59 | 개별 보고 5줄 취합 |
| 목 21:00 | 멘토링 — W6 대응 안건 |
| 금 | 주간보고서 최종 + `w05` 태그 |

### 만들 것

```
src/kopl/c4_stage2/                          가명화·복원 모듈 ✅ (#243 · 테스트 co-located)
experiments/exp08-stage2-sft/make_sft_v1.py  v1 SFT 빌더 ✅ (9/15 · train 342 / dev 30)
experiments/exp08-stage2-sft/data/           v1 train/dev 재생성분 (로컬 생성, .gitignore)
```

### 완료 기준

- [x] `anonymize()` + `restore()` — 라운드트립 15종 통과 (9/14)
- [x] 가명화 모듈 PR 머지 (#243 · 9/14)
- [x] v1 SFT 빌더 — gold spans + anonymize → 가명 입력 (test 제외 #244 · train 342 / dev 30 · 9/15)
- [x] QLoRA 에포크 ≥ 3 완료 (v1 데이터) + loss 곡선 이슈 등록 (#253 · 9/16 · dev_loss 0.41→0.0044 · verdict 90%)
- [x] W6 학습 잡 — 3ep adapter v1 확정 · 추가 학습 불필요 (#264 · 9/18 · verdict 90%)

---

## E · 이지희 — 통합 조기 착수

> 전체 매뉴얼 [docs/roles/E-system.md](docs/roles/E-system.md) · [howto/e-integration.md](docs/roles/howto/e-integration.md)

### ⭐ 이번 주 E 의 목표 — "스캔이 한 번 끝까지 돌아가는 것"

숫자가 맞는 것은 목표가 아니다. B·C·D 모델이 아직 완성이 아니어도 괜찮다. **목(mock) 엔진으로 3화면이 에러 없이 연결되는 것**이 이번 주 완료 기준이다.

```
[SNS 포트 3000]                    [분석기 포트 8000]
  GET /api/export/<user_ref>  →→→  POST /scan/<user_ref>
  returns: {posts: [...]}           ENGINE_MODE=mock
                                    ├─ engines/mock.py  ← 이번 주
                                    │   detect_spans()
                                    │   specificity()
                                    │   contribution()
                                    │   stage2()
                                    └─ engines/real.py  ← B·C·D 완성 후
```

### ~~월 — 통합 아키텍처 확인 + 경계 스크립트~~ ✅ 완료 (#254 · 9/17)

```bash
# 경계 검증 — 분석기가 SNS 내부를 직접 건드리지 않는지 확인
grep -rn "sns\.db\|apps\.sns\|apps/sns" apps/analyzer/ 2>/dev/null \
  || echo "OK: 경계 유지"
```

`check_boundary.sh` 가 없으면 만든다:

```bash
cat > scripts/check_boundary.sh << 'EOF'
#!/bin/bash
# 분석기가 SNS 내부를 건드리면 exit 1
result=$(grep -rn "sns\.db\|apps\.sns\|apps/sns" apps/analyzer/ 2>/dev/null)
if [ -n "$result" ]; then
  echo "⚠️ 계층 경계 위반:"
  echo "$result"
  exit 1
fi
echo "OK: 경계 유지"
EOF
chmod +x scripts/check_boundary.sh
```

### ~~월~화 — 목 엔진 구현 + 계약 검증~~ ✅ 완료 (#254 · 9/17 · 4종 스키마 통과)

`howto/e-integration.md §2`의 코드를 `apps/analyzer/engines/mock.py`로 만든다.

4개 함수를 각각 계약 스키마로 검증:

```bash
# 1) span 탐지
python -c "
import json, sys
sys.path.insert(0, '.')
from apps.analyzer.engines import mock
r = mock.detect_spans({'post_id':'test_b01', 'body':'집 근처 신갈저수지 다녀왔어요'})
json.dump(r, open('/tmp/test_span.json','w'))
"
check-jsonschema --schemafile docs/contracts/span.schema.json /tmp/test_span.json

# 2) 특정성
python -c "
from apps.analyzer.engines import mock; import json
r = mock.specificity({'region_code':'41460'})
json.dump(r, open('/tmp/test_spec.json','w'))
"
check-jsonschema --schemafile docs/contracts/specificity.schema.json /tmp/test_spec.json

# 3) 기여도
python -c "
from apps.analyzer.engines import mock; import json
r = mock.contribution('A11', [{'post_id':'A11_b01','body':'글'}])
json.dump(r, open('/tmp/test_contrib.json','w'))
"
check-jsonschema --schemafile docs/contracts/contribution.schema.json /tmp/test_contrib.json

# 4) 2단 판정
python -c "
from apps.analyzer.engines import mock; import json
r = mock.stage2({'author_id':'A11','posts':[]})
json.dump(r, open('/tmp/test_stage2.json','w'))
"
check-jsonschema --schemafile docs/contracts/stage2-io.schema.json /tmp/test_stage2.json
```

**4개 모두 통과**해야 다음 단계로 간다.

### ~~화~수 — 분석기 서버 + 3화면 구현~~ ✅ 완료 (#254 · 9/17 · 에러 없음)

```
apps/analyzer/
├─ server.py           FastAPI (또는 Flask)
├─ engines/
│  ├─ mock.py          이번 주
│  └─ real.py          B·C·D 완성 후 교체
├─ external.py         외부 LLM 호출 게이트
└─ static/
   ├─ scan.html         1화면: 글 목록 + 스캔 요청
   ├─ diagnosis.html    2화면: 위험도 진단 결과
   └─ action.html       3화면: 조치 추천
```

분석기 서버 기본 구조:

```python
# apps/analyzer/server.py
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

ENGINE_MODE = os.getenv("ENGINE_MODE", "mock")

if ENGINE_MODE == "mock":
    from apps.analyzer.engines import mock as engine
else:
    from apps.analyzer.engines import real as engine

app = FastAPI()
app.mount("/static", StaticFiles(directory="apps/analyzer/static"), name="static")

@app.post("/scan/{user_ref}")
async def scan(user_ref: str):
    # 1. SNS에서 글 목록 가져오기
    import requests
    posts_resp = requests.get(f"http://localhost:3000/api/export/{user_ref}")
    posts = posts_resp.json()["posts"]

    # 2. 각 글에 스팬 탐지
    spans_list = [engine.detect_spans(p) for p in posts]

    # 3. 특정성·기여도·2단 판정
    all_spans = [s for sr in spans_list for s in sr["spans"]]
    attrs = extract_attrs(all_spans)
    spec   = engine.specificity(attrs)
    contrib = engine.contribution(user_ref, posts)
    stage2  = engine.stage2({"author_id": user_ref, "posts": posts})

    return {"spans": spans_list, "specificity": spec,
            "contribution": contrib, "stage2": stage2}
```

서버 시작 확인:

```bash
# 터미널 1: SNS 서버
cd apps/sns && python app.py   # 포트 3000

# 터미널 2: 분석기 서버
ENGINE_MODE=mock uvicorn apps.analyzer.server:app --port 8000 --reload

# 터미널 3: 흐름 확인
curl http://localhost:8000/scan/u_$(python -c "
import hashlib
print(hashlib.sha256('A11'.encode()).hexdigest()[:12])
")
```

### ~~수~목 — 수동 업로드 경로~~ ✅ 완료 (#254 · 9/17 · 디스크 저장 없음)

```python
# apps/analyzer/server.py 에 추가

from fastapi import UploadFile, File

@app.post("/upload")
async def upload_and_scan(file: UploadFile = File(...)):
    """
    글 파일을 업로드해 분석기에 직접 보낸다.
    ⚠️ 파일은 메모리에서 읽고 버린다 — 디스크에 저장하지 않는다.
    M4에서 실제 블로거 글을 검증할 때 이 경로를 쓴다.
    """
    content = await file.read()   # 메모리
    text = content.decode("utf-8")
    post = {"post_id": "upload_0", "body": text}

    spans_result = engine.detect_spans(post)
    return {"post_id": "upload_0", "spans": spans_result["spans"]}
```

```html
<!-- apps/analyzer/static/upload.html -->
<form action="/upload" method="post" enctype="multipart/form-data">
  <h2>글 직접 분석</h2>
  <textarea name="text" rows="10"
    placeholder="분석할 글을 붙여넣으세요..."></textarea>
  <input type="file" name="file" accept=".txt,.md">
  <button type="submit">분석 시작</button>
</form>
```

### ~~목 — 엔드투엔드 흐름 점검~~ ✅ 완료 (#254 · 9/17 · ENGINE_MODE=mock 에러 없음)

```
SNS 시딩된 글 (예: A11 글 전체)
→ GET http://localhost:3000/api/export/u_<hash>
→ POST http://localhost:8000/scan/u_<hash>
→ mock 스팬 탐지 → mock 위험도 → mock 조치
→ 3화면 (scan.html → diagnosis.html → action.html) 에 표시
```

이 흐름이 에러 없이 끝까지 돌아가면 ✅.

```bash
# 경계 최종 검증
bash scripts/check_boundary.sh
```

### 금 — 스트레치: 활동 메타 필드 착수 (W6 선행)

W6 추석 연휴(근무일 3일) 대비. 여유가 있으면 착수한다.

```sql
-- apps/sns/schema.sql 확인
SELECT sql FROM sqlite_master WHERE name='posts';
-- geo_tag, visibility 가 있으면 통과
-- 없으면 마이그레이션:
```

```python
# apps/sns/migrate_meta.py
import sqlite3, os
conn = sqlite3.connect(os.environ["SNS_DB_PATH"])
try:
    conn.execute("ALTER TABLE posts ADD COLUMN geo_tag TEXT")
    conn.execute("ALTER TABLE posts ADD COLUMN visibility TEXT DEFAULT 'public'")
    conn.commit()
    print("마이그레이션 완료")
except sqlite3.OperationalError as e:
    print(f"이미 있음: {e}")
conn.close()
```

글 작성 화면에 공개/비공개 토글 추가 (완전 완성이 아니어도 됨 — W6에 이어서):

```html
<!-- apps/sns/templates/new_post.html 에 추가 -->
<label>
  <input type="checkbox" name="visibility" value="private">
  비공개로 게시
</label>
```

### 만들 것

```
apps/analyzer/engines/mock.py          목 엔진 4종
apps/analyzer/server.py                분석기 서버
apps/analyzer/static/                  3화면 HTML (scan·diagnosis·action)
apps/analyzer/external.py             외부 LLM 게이트 (ALLOW_EXTERNAL_LLM 플래그)
scripts/check_boundary.sh             계층 경계 검증
```

### 완료 기준

- [x] 목 엔진 4종 — 계약 스키마 검증 4/4 통과 (#254 · 9/17)
- [x] `check_boundary.sh` — 0줄 (경계 유지) (#254 · 9/17)
- [x] 3화면 (스캔·진단·조치) — `ENGINE_MODE=mock` 엔드투엔드 에러 없음 (#254 · 9/17)
- [x] 수동 업로드 경로 — 파일 메모리 처리, 디스크 저장 없음 (#254 · 9/17)
- [x] AWS 크레딧 조건 확인 — KISIA 계정 9/14 수령 · 개인 AWS 크레딧으로 Lightsail 운용 후 멘토 EC2 이전 완료 (9/17)
- [ ] *(스트레치)* SNS 활동 메타 필드 — 공개/비공개 토글 착수

---

## 이번 주 일정

| 요일 | 시각 | 누가 | 무엇 |
|---|---|---|---|
| **화 9/15** | 21:00 | 전원 | 팀 회의 30분 — IAA 2차 착수 일정 / #244 split 재실행 공유 |
| 월~화 | | A | train/test 분리 스크립트 |
| 월~화 | | B | ~~o_weight 그리드 탐색~~ ✅ 4종 완료 (9/15) |
| 월~화 | | C | ~~#229 재제출~~ ✅ 완료 → IAA 2차 표본 추출 착수 |
| 월~화 | | D | ~~가명화 모듈~~ ✅ #243 머지 (9/14 선완료) |
| 월~화 | | E | 목 엔진 4종 구현 + 계약 검증 |
| **화~수** | | B | ~~o_weight 탐색 결과 비교표 작성~~ ✅ 완료 · LR 3종 비교도 완료 (9/16) |
| 화 | | C | IAA 2차 표본 추출 (A와) |
| **수** | | E | 분석기 서버 + 3화면 연결 |
| ~~수~~ | | ~~A~~ | ~~label-schema §3-2 수정 PR~~ ✅ #245 머지 (9/14) |
| **수 23:59** | | 팀원 5명 | 주간보고서 5줄 PM 에게 |
| **월 9/21 11:15** | | D(PM) | KISIA 줌 주간보고회 발표 |
| **목 9/17** | | B | v1 체크포인트 확정 + registry.md PR |
| 목 | | C | LOO 기여도 엔진 + 증류 타깃 생성 |
| 수~목 | | D | v1 SFT 빌더 (본문+골드스팬+anonymize) + QLoRA ≥ 3 epoch (v1) |
| 목 | | E | 엔드투엔드 흐름 점검 + check_boundary |
| **목 21:00** | | 전원+멘토 | 멘토링 — W6 추석 대응 + IAA 2차 |
| **금 9/18** | | B·D | W6 학습 잡 — epoch 시간 확인 후 필요시 tmux 착수 |
| 금 | | E | (스트레치) 활동 메타 필드 착수 |
| **금 마감 전** | | D(PM) | 주간보고서 최종 제출 + `w05` 태그 |

---

## 이번 주 반드시 지킬 것 3가지

**① ~~C는 #229 수정 중에도 `gold/detect/`(교사 출력)를 열지 않는다.~~** ✅ #229 머지 완료 (9/14)
blind 조건 준수하며 재제출 완료. IAA 2차부터는 blind 조건 해제.

**② B는 #244 split 재실행 후에 학습한다.**
test에 잡담 80편이 추가돼 train이 2,917 → 2,837로 줄었다. `split_train_test.py` 재실행 없이 옛 분리로 학습하면 test 글이 train에 남는다.

**③ E는 분석기가 `apps/sns/` 내부를 직접 읽지 않도록 한다.**
`GET /api/export/<user_ref>` 경로만 쓴다. `check_boundary.sh` 를 PR마다 돌린다.

---

## 막히면

| 상황 | 어떻게 |
|---|---|
| o_weight 실험에서 F1이 0에서 안 올라온다 | `--overfit 30`으로 30편 과적합부터 확인. 과적합에서도 안 되면 데이터 문제 → B·PM 이슈 등록 |
| `train.py` 가 CUDA OOM 으로 죽는다 | `--batch 8` 로 낮추거나 `--fp16 false` |
| `check-jsonschema` 명령이 없다 | `pip install check-jsonschema` |
| SNS 서버 포트 3000 이 안 켜진다 | `apps/sns/` 디렉터리의 README 확인 또는 E에게 |
| C의 `compute_k` 함수가 없다 | `src/kopl/c2_specificity` 에서 import. 없으면 임시로 `return 9999.0` 을 쓰고 이슈 등록 |
| QLoRA OOM | `--bits 4 --batch 2` — 그래도 안 되면 Kaggle T4 |
| PR 머지가 안 된다 | nuewsun 에게 리뷰 요청 — 재촉하지 말고 한 번만 |
| 명령이 Windows 에서 안 된다 | Git Bash 쓰거나 아래 PowerShell 대안 |

```powershell
# PowerShell 대안 — grep 대신
Select-String -Path apps\analyzer\* -Pattern "sns\.db" -Recurse
```

---

## 저장소 구조

```
KISIA_Project/
├─ README.md                      ← 이번 주 할 일 (이 문서)
├─ CONTRIBUTING.md                브랜치·커밋·리뷰 규칙
├─ docs/
│  ├─ overview.md                 프로젝트가 뭔지
│  ├─ plan.md                     계획 전문 (v2.2)
│  ├─ roadmap.md                  12주 주차별 계획
│  ├─ roles/                      역할별 작업 매뉴얼 5종
│  ├─ contracts/                  ⭐ 모듈 인터페이스 계약 6종 (W2 고정)
│  ├─ design/                     설계서 (W4 제출 완료)
│  ├─ decisions.md                결정 기록 [DEC-NNN]
│  ├─ mentor-log.md               멘토 피드백 [MF-NNN]
│  └─ RULES-DO-NOT.md             절대 하면 안 되는 것
├─ src/kopl/
│  ├─ c1_detector/                1단 탐지 (B)
│  ├─ c2_specificity/             특정성 엔진 (C)
│  ├─ c3_contribution/            기여도 엔진 (C · W5 신규)
│  └─ c4_stage2/                  2단 추론·가명화 (D · W5 신규)
├─ data/
│  ├─ corpus/v0/personas/         인물 JSON (115명 · W4 동결)
│  ├─ corpus/v0/posts/            생성 글 (3,092편 · W4 동결)
│  ├─ corpus/v0/gold/             골드셋 검수분 (417편 587스팬)
│  ├─ corpus/v0/gold/blind/       blind 분 ✅ (C · #229 머지 완료 9/14 · 159편 267스팬)
│  ├─ corpus/v0/gold/iaa/         IAA 배정 + A·C 라벨링
│  ├─ corpus/v0/gold/contribution/ 증류 타깃 세트 (C · W5 신규)
│  ├─ corpus/v0/splits/           train/test 분리 (A · W5 신규)
│  ├─ realism/cards/              리얼리즘 카드 18장
│  └─ dict/admin/                 행정구역·인구 사전
├─ experiments/
│  ├─ exp01-baseline/             베이스라인 3종 + LLM 상한 (W4 완성)
│  ├─ exp05-model-size/           Qwen3 크기 비교 (W3 완료)
│  ├─ exp06-finetune/             1단 파인튜닝 (B · W4~)
│  └─ exp07-qwen3-finetune/       2단 QLoRA (D · W4~)
├─ apps/
│  ├─ sns/                        가상 SNS (v0 + 시딩 완료)
│  └─ analyzer/                   분석 웹앱 (E · W5 신규)
├─ models/
│  └─ registry.md                 모델 체크포인트 등록부
└─ scripts/                       운영 스크립트
```

---

## 현재 미결 (9/14 기준)

**PR** — ~~#229 C blind 200~~ ✅ 머지 완료 (9/14)

**이슈 — W5**
- [x] ~~test set 구성 방향 결정~~ ✅ (가) 잡담 80편 test 추가 — #244 머지 · #235 닫힘 (9/14)
- [x] ~~[#200](../../issues/200) IAA 2차~~ ✅ overall 50.0% (9/17 · #248 #250 머지)
- [x] ~~[#223](../../issues/223) label-schema §3-2 배우자 호칭~~ ✅ #245 머지 · 닫힘 (9/14)
- [x] AWS 크레딧 조건 확인 (E · 9/14 KISIA 계정 수령 · 멘토 EC2 이전 9/17 ✅)
- [ ] [#206](../../issues/206) #201 후속 추적 — 각자 인물 JSON 확인

**장기**
- [ ] [MF-015](docs/mentor-log.md) 대회 제출 요건·배포 범위 확인 — PM · 목 9/17 멘토링 전
- [x] AWS 크레딧 조건 확인 — E · 9/14 수령 · 9/17 멘토 EC2 이전 완료
- [ ] 잡담 글 「단서 0」 계약 vs 자영업·농업 인물의 삶 (#201 남은 쟁점) — v2
