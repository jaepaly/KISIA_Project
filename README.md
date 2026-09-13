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

---

## 지금 상태

**W4 설계서·골드셋 완료, 파인튜닝·통합 W5 착수** — [compare/w03...w04](../../compare/w03...w04)

| 항목 | W4 끝 |
|---|---|
| 코퍼스 | **v1 동결** ✅ 115명 3,092편 · d4cf8cb · 9/9 |
| 골드셋 검수 | **417편 587스팬** ✅ A·B·D·E 4명 · [gold/README.md](data/corpus/v0/gold/README.md) · 9/11 |
| blind 200 | **재제출 대기** ← #229 계약 5건 (C) |
| IAA | 1차 27.0% ✅ · **2차 대기** (C #229 완료 후 A·C 공동) |
| 1단 파인튜닝 | train.py ✅ (#239) · **과적합 F1 0.9157** · 전체 1 epoch F1 0.0602 · o_weight 진단 (#240) |
| 2단 QLoRA | 첫 잡 ✅ dev loss 0.005 · 함정 배제 15/18 (#214) |
| 지명 사전 | UNKNOWN 18→2 ✅ · 픽스처 19/19 (#218) |
| 가상 SNS | v0 + **시딩** ✅ (#237) |
| 설계서 | ✅ 제출 완료 9/10 |
| `w04` 태그 | ✅ 9/11 |

| 역할 | 담당 | **이번 주 핵심** |
|---|---|---|
| **[A · 데이터 리드](docs/roles/A-data.md)** | 이은선 | **train/test 분리** + test set 방향 결정 |
| **[B · 1단 탐지](docs/roles/B-detector.md)** | 최진필 | **o_weight 튜닝 → v1 확정** · W6 잡 착수 |
| **[C · 특정성·누적](docs/roles/C-specificity.md)** | 신정현 | **#229 재제출** + IAA 2차 + **기여도 엔진 v1** |
| **[D · 2단 추론·조치](docs/roles/D-stage2.md)** | 박재현 (PM) | **가명화·복원 계층** + W6 잡 착수 |
| **[E · 시스템·컴플라이언스](docs/roles/E-system.md)** | 이지희 | **분석 웹앱 3화면 연결** + 수동 업로드 |

---

# W5 (9/15~9/19) — 각자 할 일

**제출물**: 주간활동보고서 (외부)
**단계**: **M2-b 통합 1차** · 근무일 5일

> ## 이번 주 한 문장 — **파인튜닝 수렴 경로를 찾고, 분석 화면을 목 엔진으로 먼저 연결한다.**
>
> 로드맵 §3:
>
> W5는 B가 학습 v1을 확정하고, E가 통합을 조기 착수하는 주다. C의 기여도 엔진 v1도 시작한다.
> **다음 주(W6)가 추석 연휴 — 근무일 3일.** B·D는 이번 주 말일(9/19)에 학습 잡을 킥오프해 연휴 중 GPU 가 돌아가도록 한다.

---

## 0. 월요일 킥오프 — 10:00, 30분

### 먼저 받기

```bash
git pull
pip install -e .
```

### 월요일에 정할 것 둘

#### ① test set 구성 방향 (W4 이월) — 담당 A · PM

| 선택지 | 내용 | 장단점 |
|---|---|---|
| **(가)** blind 검수분 재활용 | 현재 `gold/blind/` 스팬을 test로 | 빠르지만 blind 조건 논란 가능 |
| **(나)** 새 소음 표본 | 단서 0 글에서 새로 뽑아 A가 라벨 | 깔끔하지만 시간 추가 |
| **(다)** 교사 라벨 그대로 | `gold/detect/` 를 test에 직접 | 빠르지만 라벨 품질 낮음 |

**결정 후 이슈로 기록** — B의 train/test 분리가 이 결정에 걸려있다.

#### ② C blind 200 재제출 (#229) 일정 확인

C가 이번 주 어느 시점에 재제출 가능한지 킥오프에서 확인한다.

---

## W4 이월 항목

| 항목 | 담당 | 상태 |
|---|---|---|
| blind 200 재제출 (계약 5건 수정) | C | #229 진행 중 |
| train/test 분리 (`split_train_test.py`) | A | W4 이월 (검수 완료 후 순서) |
| test set 구성 방향 결정 | A · PM | 미결 |
| IAA 2차 (A·C 20편) | A · C | C #229 완료 후 착수 |
| `label-schema` #223 §3-2 배우자 호칭 1줄 | A | 미결 |

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

원고는 드라이브 — PM(재현)에게 **수 23:59** 까지 보낸다.

---

## A · 이은선 — 라벨 품질관리 · 네거티브 보강

> 전체 매뉴얼 [docs/roles/A-data.md](docs/roles/A-data.md)

### 월 오전 — 킥오프 + test set 방향 결정

(가)·(나)·(다) 중 선택 후 즉시 이슈 등록. B에게 알린다 — B의 train/test 분리가 이 결정에 걸려있다.

### 월~화 — split 누수 검증 (✅ #230 W4 머지 완료)

`scripts/split_train_test.py` 와 `data/corpus/v0/splits/` 는 **W4 에 완료** (`#230` 머지됨). 이번 주는 새로 작성하지 않는다.

대신 방향 결정(#235) 이후 **기존 split에 누수가 없는지 한 번 확인**하고 B에게 경로를 알린다.

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

### 화 — label-schema §3-2 수정

```bash
# 수정 위치 확인
grep -n "배우자\|호칭" docs/contracts/label-schema.md
```

[#223](../../issues/223) 합의된 배우자 호칭 FAMILY 분류 1줄을 §3-2에 추가 후 PR.

### 수~목 — IAA 2차 준비

C의 #229가 머지되면 IAA 2차 표본을 C와 함께 뽑는다.

```
IAA 2차 절차:
1. C #229 머지 확인
2. gold/iaa/_assignment_v2.json 생성 — 새 20편 표본 (seed 기록)
   (기준: explicit/implicit/inferential 등급 분포 층화)
3. A·C 각자 독립 라벨링
   → gold/iaa/A_spans_v2.jsonl
   → gold/iaa/C_spans_v2.jsonl
4. scripts/iaa.py 로 등급별 F1 계산
5. 결과 이슈 등록
```

### 수~목 — 네거티브 보강 (roadmap A W5 항목)

test set 방향과 무관하게 진행한다. 네거티브 컨트롤(신상 단서 없는 글)이 학습 데이터에 충분히 포함되어야 모델이 "잡담 글에서 오탐"을 내지 않는다.

- 현재 gold/에 reviewed=true + 스팬 0 인 글이 몇 편인지 확인
- 10% 이하면 A-data.md §3 지침대로 소음 글 추가 라벨

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

- [ ] test set 구성 방향 결정 + 이슈 기록
- [ ] split 누수 검증 통과 + B 에게 경로 공유
- [ ] `label-schema` #223 §3-2 배우자 호칭 1줄 추가 PR
- [ ] IAA 2차 착수 (C #229 완료 조건부)

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

### 월 오전 — 킥오프 + A의 분리 결과 대기

A가 `split_train_test.py`를 완성하면 즉시 연결한다. 그 전엔 `gold/` 전체로 과적합 테스트를 계속한다.

A의 분리 결과 사용법:

```bash
python experiments/exp06-finetune/prepare_bio.py \
  --gold-dir   data/corpus/v0/gold \
  --posts-dir  data/corpus/v0/posts \
  --split      data/corpus/v0/splits/train.jsonl \
  --out        experiments/exp06-finetune/data/train_bio.jsonl
```

### 월~화 — o_weight 그리드 탐색

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
| 0.005 | | | |
| 0.01 | | | W4 기준 |
| 0.02 | | | |
| 0.05 | | | |

**멈추는 기준**: eval F1이 2 epoch 연속 내려가면 그 직전 체크포인트가 best.

### 수 — 학습률·배치 세컨더리 스윕 (o_weight 확정 후)

```bash
# o_weight 최적값이 OW_BEST 라고 할 때
for LR in 1e-5 2e-5 5e-5; do
  python experiments/exp06-finetune/train.py \
    --o-weight $OW_BEST --epochs 10 --lr $LR --batch 16 \
    --output experiments/exp06-finetune/runs/v1_lr${LR}
done
```

### 목 — v1 체크포인트 확정 + models/registry.md 등록

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

### 목~금 — 추론 함수 래퍼 (E에게 넘길 것)

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

### 금 말일 — W6 비동기 학습 잡 착수

연휴 중 PC가 켜져 있어야 한다. tmux를 쓰면 ssh 연결이 끊겨도 실행이 유지된다.

```bash
# tmux 세션 열기
tmux new -s w6_train

# 긴 학습 시작
python experiments/exp06-finetune/train.py \
  --o-weight <최적값> \
  --epochs 20 \
  --output experiments/exp06-finetune/runs/v1_long \
  --resume-from-checkpoint latest \
  2>&1 | tee logs/v1_long.log

# Ctrl+B → D 로 세션에서 빠져나옴 (학습은 계속 실행)
# 연휴 후 확인: tmux attach -t w6_train
```

### 만들 것

```
experiments/exp06-finetune/runs/v1_*/     o_weight 실험 결과들
experiments/exp06-finetune/infer.py       추론 함수 래퍼
models/registry.md                        v1 체크포인트 등록
```

### 완료 기준

- [ ] o_weight 그리드 탐색 — 전체 eval F1 ≥ 0.25
- [ ] v1 체크포인트 확정 + `models/registry.md` 등록 PR
- [ ] CPU 지연 측정 + 기록 (목표 < 300ms)
- [ ] 추론 함수 `infer.py` — `span.schema.json` 계약 통과
- [ ] W6 비동기 학습 잡 착수 (금 말일 · tmux)

---

## C · 신정현 — 기여도 엔진 v1

> 전체 매뉴얼 [docs/roles/C-specificity.md](docs/roles/C-specificity.md) · [howto/c-engine.md](docs/roles/howto/c-engine.md)

### ⭐ 이번 주 C 의 두 과제

1. **blind 200 재제출 (#229)** — W4 이월. 계약 5건 수정 후 이번 주 초에 다시 올린다.
2. **기여도 엔진 v1** — LOO 정답 생성기 + 증류 타깃. D의 추천 엔진이 이 데이터를 쓴다.

### 월~화 — #229 blind 200 재제출

PR #229 리뷰에서 지적된 계약 위반 5건을 수정한다.

```bash
# 수정 후 품질 검사 — ERROR 0건이 합격선
python scripts/check_gold.py data/corpus/v0/gold/blind/ --all

# 통과하면 PR #229 에 추가 커밋 후 ready for review 전환
git add data/corpus/v0/gold/blind/
git commit -m "data(c5): blind 200 계약 수정 (#229 재제출)"
```

**⚠️ blind 조건 유지**: 수정 중에도 `gold/detect/`(교사 출력)를 열지 않는다. 형식 오류를 고치는 것이지 내용을 다시 보는 게 아니다.

### 화 — IAA 2차 표본 추출 (A와)

A의 train/test 분리가 완료되면 IAA 2차 표본을 뽑는다.

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

### 수~목 — 기여도 엔진 v1 (LOO)

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

### 금 — IAA 2차 결과 이슈 등록

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

- [ ] #229 계약 5건 수정 + 재제출 (PR 업데이트 → 머지)
- [ ] IAA 2차 라벨링 완료 + 등급별 F1 이슈 등록
- [ ] `loo.py` LOO 기여도 — 단위 테스트 통과
- [ ] 증류 타깃 세트 — `contribution.schema.json` 계약 통과

---

## D · 박재현 — 가명화·복원 계층 (+ PM)

> 전체 매뉴얼 [docs/roles/D-stage2.md](docs/roles/D-stage2.md)

### ⭐ 이번 주 D 의 핵심 — 가명화 모듈

B가 스팬을 찾으면 그 구간을 실제 표현에서 **가명 라벨로 교체**하고, 나중에 다시 원래 표현으로 **복원**한다. 이 단계가 있어야 D의 2단 모델이 원문 지명을 보지 않고 구조만 판단할 수 있다.

### 월~화 — 가명화 모듈 구현

```python
# src/kopl/c4_stage2/anonymize.py

# 가명 라벨 규칙 (label-schema §6 기반)
LABEL_TEMPLATE = {
    "LOC_FACILITY": "[시설{idx}]",
    "LOC_REGION":   "[지역{idx}]",
    "AGE":          "[{decade}0대]",    # 48 → 40대
    "JOB":          "[직업{idx}]",
    "FAMILY":       "[관계{idx}]",
    "COMMUTE":      "[통근지{idx}]",
    "INCOME":       "[소득{idx}]",
    "SEX":          "[성별{idx}]",
    "REL_WORK":     "[직장관계{idx}]",
}

def anonymize(text: str, spans: list[dict]) -> tuple[str, dict]:
    """
    text:  원문 문자열
    spans: B(c1) 출력 스팬 목록 (start·end·type·text 포함)

    반환:
      anon_text: 가명 처리된 텍스트
      key:       복원 매핑 {"[시설1]": "신갈저수지", "[40대]": "마흔여덟", ...}
    """
    # 스팬을 역순(뒤에서 앞으로)으로 교체해야 offset이 안 밀린다
    sorted_spans = sorted(spans, key=lambda s: -s["start"])
    key = {}
    counter = {}   # 유형별 카운터

    result = text
    for sp in sorted_spans:
        typ = sp.get("type", "UNKNOWN")
        counter[typ] = counter.get(typ, 0) + 1
        idx = counter[typ]

        if typ == "AGE":
            # 48 → 40대 변환 시도
            import re
            m = re.search(r"\d+", sp["text"])
            decade = (int(m.group()) // 10) if m else "X"
            placeholder = f"[{decade}0대]"
        else:
            tpl = LABEL_TEMPLATE.get(typ, "[단서{idx}]")
            placeholder = tpl.format(idx=idx)

        key[placeholder] = sp["text"]
        result = result[:sp["start"]] + placeholder + result[sp["end"]:]

    return result, key


def restore(anon_text: str, key: dict) -> str:
    """가명 텍스트 + 키 → 원문 복원"""
    result = anon_text
    for placeholder, original in key.items():
        result = result.replace(placeholder, original)
    return result
```

**라운드트립 단위 테스트**:

```python
# tests/test_anonymize.py
def test_roundtrip():
    text = "집 근처 신갈저수지 조황입니다. 마흔여덟 되니 무릎이…"
    spans = [
        {"start": 4,  "end": 10, "text": "신갈저수지", "type": "LOC_FACILITY"},
        {"start": 14, "end": 18, "text": "마흔여덟",   "type": "AGE"},
    ]
    anon, key = anonymize(text, spans)
    assert "[시설1]" in anon
    assert "[40대]" in anon
    restored = restore(anon, key)
    assert restored == text, f"복원 실패: {restored!r} ≠ {text!r}"

def test_multi_same_type():
    text = "신갈저수지 옆 기흥호수 조황"
    spans = [
        {"start": 0,  "end": 5,  "text": "신갈저수지", "type": "LOC_FACILITY"},
        {"start": 6,  "end": 10, "text": "기흥호수",   "type": "LOC_FACILITY"},
    ]
    anon, key = anonymize(text, spans)
    assert "[시설1]" in anon and "[시설2]" in anon
```

```bash
python -m pytest tests/test_anonymize.py -v
```

### 화~수 — QLoRA 2단 학습 계속

W4 첫 잡(dev loss 0.005) 이후 에포크를 늘린다.

```bash
python experiments/exp07-qwen3-finetune/train.py \
  --epochs 5 \
  --batch 4 \
  --lr 1e-4 \
  --output experiments/exp07-qwen3-finetune/runs/v1_e5
```

**이번 주부터 가명 처리 후 입력 사용**:

```python
# 학습 데이터 생성 시
from kopl.c4_stage2.anonymize import anonymize

anon_text, key = anonymize(post["body"], gold_spans)
# anon_text 를 Qwen3 입력으로 사용 (원문 대신)
```

### 수 23:59 — 주간보고서 + 팀원 보고 취합

PM 역할: 팀원 5명 보고 취합 + 막힌 항목 확인 (특히 C #229 상황, A test set 결정).

### 목 20:00 — 멘토링

**이번 주 멘토링 안건:**
1. **W6 추석 대응** — B·D 학습 잡 비동기 배치 방식 보고
2. **IAA 2차 결과** (C #229 완료 시) — 암묵 F1 수준 보고

### 금 말일 — W6 비동기 학습 잡 착수

```bash
tmux new -s w6_qwen3
python experiments/exp07-qwen3-finetune/train.py \
  --epochs 20 \
  --output experiments/exp07-qwen3-finetune/runs/v1_long \
  2>&1 | tee logs/qwen3_v1.log
# Ctrl+B → D
```

### PM 몫

| 언제 | 무엇 |
|---|---|
| 월 10:00 | 킥오프 30분 — test set 방향 / C #229 일정 |
| 수 23:59 | 개별 보고 5줄 취합 |
| 목 20:00 | 멘토링 — W6 대응 안건 |
| 금 | 주간보고서 최종 + `w05` 태그 |

### 만들 것

```
src/kopl/c4_stage2/anonymize.py              가명화·복원 모듈
tests/test_anonymize.py                      라운드트립 단위 테스트
experiments/exp07-qwen3-finetune/runs/v1_*   QLoRA 추가 실험
```

### 완료 기준

- [ ] `anonymize()` + `restore()` — 라운드트립 단위 테스트 통과
- [ ] 가명화 모듈 PR 머지
- [ ] QLoRA 에포크 ≥ 3 완료 + loss 곡선 이슈 등록
- [ ] W6 비동기 학습 잡 착수 (금 말일 · tmux)

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

### 월 — 통합 아키텍처 확인 + 경계 스크립트

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

### 월~화 — 목 엔진 구현 + 계약 검증

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

### 화~수 — 분석기 서버 + 3화면 구현

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

### 수~목 — 수동 업로드 경로

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

### 목 — 엔드투엔드 흐름 점검

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

- [ ] 목 엔진 4종 — 계약 스키마 검증 4/4 통과
- [ ] `check_boundary.sh` — 0줄 (경계 유지)
- [ ] 3화면 (스캔·진단·조치) — `ENGINE_MODE=mock` 엔드투엔드 에러 없음
- [ ] 수동 업로드 경로 — 파일 메모리 처리, 디스크 저장 없음
- [ ] AWS 크레딧 조건 확인 — 사용 가능 범위·기간 PM에게 전달 (W4 이월)
- [ ] *(스트레치)* SNS 활동 메타 필드 — 공개/비공개 토글 착수

---

## 이번 주 일정

| 요일 | 시각 | 누가 | 무엇 |
|---|---|---|---|
| **월 9/15** | 10:00 | 전원 | 킥오프 30분 — test set 방향 / C #229 일정 |
| 월~화 | | A | train/test 분리 스크립트 |
| 월~화 | | B | o_weight 그리드 탐색 시작 |
| 월~화 | | C | #229 계약 5건 수정 + 재제출 |
| 월~화 | | D | 가명화 모듈 구현 + 라운드트립 테스트 |
| 월~화 | | E | 목 엔진 4종 구현 + 계약 검증 |
| **화~수** | | B | o_weight 탐색 결과 비교표 작성 |
| 화 | | C | IAA 2차 표본 추출 (A와) |
| **수** | | E | 분석기 서버 + 3화면 연결 |
| 수 | | A | label-schema §3-2 수정 PR |
| **수 23:59** | | 팀원 5명 | 주간보고서 5줄 PM 에게 |
| **목 9/18** | | B | v1 체크포인트 확정 + registry.md PR |
| 목 | | C | LOO 기여도 엔진 + 증류 타깃 생성 |
| 목 | | D | 가명화 PR 머지 + QLoRA ≥ 3 epoch |
| 목 | | E | 엔드투엔드 흐름 점검 + check_boundary |
| **목 20:00** | | 전원+멘토 | 멘토링 — W6 추석 대응 + IAA 2차 |
| **금 9/19** | | B·D | W6 비동기 학습 잡 착수 (tmux) |
| 금 | | E | (스트레치) 활동 메타 필드 착수 |
| **금 마감 전** | | D(PM) | 주간보고서 최종 제출 + `w05` 태그 |

---

## 이번 주 반드시 지킬 것 3가지

**① C는 #229 수정 중에도 `gold/detect/`(교사 출력)를 열지 않는다.**
형식 오류를 고치는 것이지 내용을 다시 보는 게 아니다. blind 조건은 그대로다.

**② B는 test set 분리 전에 test 글로 학습하지 않는다.**
A의 `split_train_test.py` 결과가 나오기 전까지는 `gold/` 전체로 과적합 테스트만 한다. 분리 결과가 나오는 즉시 연결한다.

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
#183: ✅ 설계 수용 (nuewsun 9/7) + corpus_audit.py 에 「인물 경계 넘는 동일 문장」 항목 추가(A). 9/8 재생성으로 동일 문장 40건도 소멸
```

동결 선행조건은 풀렸다. **9/8 p2.3 (#201) 이 동결 후보**다.

#### ⑤ 골드셋 검수 현황 취합 · 2단 라벨 형식

⚠️ 9/8 확인 — **검수한 스팬은 0건**이었다. 원인은 Claude API 키가 9/7 에야 붙어 교사 라벨(④)이 W3 에 못 돌았고, 그 키도 팀 키라 API 경로가 느렸던 것 ([#210](../../issues/210) §1). **PM 이 9/8 밤 CLI 8병렬로 대행** → 9/9 아침 `gold/detect/` → **수~목 A·B·D·E 각 100~125 검수 → 금 취합 600~700.** C 의 blind 200 은 독립이며 교사 출력을 보기 전에 한다. 이 재배치는 #210 에서 전원 확인(9/8).
**파인튜닝 데이터로 쓸 수 있는 분량이 얼마인지** 이번 주 안에 확인해야 한다.

2단 학습 라벨 형식은 D 가 초안을 올렸다 — [`data/corpus/v0/gold/stage2/README.md`](data/corpus/v0/gold/stage2/README.md). **A(형식)·B(교사 스팬이 오면 1단·2단이 같은 `*_spans.jsonl` 을 읽는 구조) 확인 필요.**

---

## ⚠️ W3 이월 항목 — 이번 주 해소 대상

| 항목 | 담당 | 기한 |
|---|---|---|
| ~~**LLM 도달 가능성 측정** → 중단 기준 판정~~ | ✅ HOLD ([#202](../../pull/202) 파일 추가 후 머지) | — |
| ~~**IAA 파일럿** (A·C 16편)~~ | ✅ 27.0% (9/7 표본 · #221 보완 후 재계산, 보완 전 22.9%) → [#200](../../issues/200) 기준 조정 후 새 표본 2차 | — |
| ~~**IAA 계산** (PR [#188](../../pull/188))~~ | ✅ 머지 9/7 | — |
| ~~PR #191 · #189 · #192 · #181 머지~~ | ✅ 9/7 전부 main | — |
| ~~PR [#180](../../pull/180) · [#195](../../pull/195) 머지~~ | ✅ 9/7~8 | — |
| created_at ([#182](../../issues/182)) — 날짜는 재생성으로 해소, **시각(active_windows)만** | A | **수** |
| ~~D17·B16 재생성~~ | ✅ [#196](../../pull/196) | — |
| ~~S14 미달 ([#177](../../issues/177))~~ | ✅ [#197](../../pull/197) | — |
| ~~cross-persona 중복 ([#183](../../issues/183))~~ | ✅ 설계 수용 (9/7) · 재생성으로 소멸 · audit 항목 추가는 A | — |
| 2단 라벨 형식 초안 확인 ([`gold/stage2/`](data/corpus/v0/gold/stage2/README.md)) | A·B | **화** |
| **교사 라벨 전량 실행** ([#204](../../issues/204)) | **PM 대행** (9/8 밤 · Opus 4.8 8병렬) | 9/9 아침 |
| **검수 각 100~125 스팬** → `gold/<pid>_spans.jsonl` ([#210](../../issues/210)) | **A · B · D · E** | **수~목** |
| **C 대행분** — 지명 사전 계층 #115 · L1 픽스처 · 설계서 특정성 초안 | **D** | **목** |
| **blind 200 재라벨** (새 본문 · 교사 출력 보기 전) | **C** | — |
| **도달 가능성 재측정** (새 코퍼스 · `extract_clues → 3종 → compare`) | **B** | #201 뒤 |

---

## 전원 공통 — 설계서 자기 파트 완성

이번 주 외부 제출물은 **모델·서비스 설계서** 하나다.
각 역할이 자기 파트를 맡아 **초안은 수요일 개별 보고 보낼 때 같이, 검수 때문에 안 되면 늦어도 목요일 · 최종 금요일** 로 낸다 ([#210](../../issues/210)). 원고는 저장소가 아니라 드라이브 — PM 이 개별 보고 통로로 받는다.

| 역할 | 설계서에서 맡는 파트 |
|---|---|
| A | 데이터·골드셋 파이프라인, 코퍼스 통계 |
| B | 1단 탐지 모델 구조·학습 계획, 베이스라인 비교표 |
| C | 특정성 k 산출 방법론, 지명 사전 구조 |
| D | 2단 추론·조치 모델 구조, QLoRA 설정, 전체 취합 |
| E | 시스템 아키텍처, SNS 인터페이스, AWS 배포 계획 |

**G2 지표 갱신** — M1 실측값(exp01·exp05)을 반영해 [목표]/[도전] 지표를 갱신한다.
멘토 승인은 **목요일 멘토링**에서 받는다.

```
현재 [목표] 지표 두 가지 — M1 실측으로 채운다
  · 스팬 탐지 F1(암묵): M1 IAA 측정치의 80% 이상 → IAA 수치 나오면 확정
  · Qwen3 vs 외부 LLM 속성 적중 일치율 ≥ 0.8 → 학습된 Qwen3 v1 이 있어야 잰다 (exp07 · W7)
    ⚠️ exp04(Claude vs GPT)가 아니다 — 그건 plan.md §6 ⑤ 「특정 모델의 아티팩트가 아님」 방어이고
       임계값이 없다. exp05(1.7B vs 4B)도 이 지표의 근거가 아니다.
       (이 줄이 9/7 까지 exp04 를 가리키고 있어 exp04 게이트가 0.8 로 잘못 잡혔다 — PM 실수)
```

---

## A · 이은선 — 데이터 리드

> 전체 매뉴얼 [docs/roles/A-data.md](docs/roles/A-data.md)

### 월 — 킥오프 + 이월 결정 참여

②③④ 결정에 A 가 의견을 내야 한다. 특히 **created_at(②)** 는 A 결정이다.

### 월 오후 — 골드셋 현황 정리

[#191](../../pull/191) 이 머지돼 `data/corpus/v0/gold/blind/` 에 150편 · 110스팬이 main 에 있다 (9/7). IAA 파일럿은 별도 16편(`gold/iaa/_assignment.json`)이다.

### ~~화 — IAA 파일럿 라벨링~~ ✅ 9/7 실측 22.9% → #221 보완 후 27.0% → [#200](../../issues/200) 기준 조정이 남은 일

### ~~화~수 — 교사 라벨 전량 실행~~ → PM 대행 ([#204](../../issues/204) · 9/8 밤)

A 가 5명으로 시험하니 편당 75초·전체 60시간 (팀 키가 Claude Code 용이라 API 경로가 느리다). PM 이 CLI 8병렬(Opus 4.8)로 9/8 22:43 시작 → `gold/detect/<pid>_spans.jsonl` 115개. A 는 **동결 선언·검수**만 한다.

### 화~수 — 코퍼스 v1 동결 준비

1. ~~**D17·B16 재생성**~~ → [#201](../../pull/201) 115명 전량 p2.3 (9/8) — **이것이 동결 후보**
2. **created_at 시각** — 날짜·계절은 재생성으로 해소. `account.active_windows` 를 인물 JSON 에 넣을지만 정한다 ([#182](../../issues/182))
3. ~~E15.jsonl~~ ✅ #201·#203

### 수 오전 — 코퍼스 v1 동결 선언 + 파인튜닝 데이터 정리

```bash
# 동결 확인 — validate ERROR 0건이 합격선 (audit 은 판정하지 않으므로 참고용)
python -m kopl.c5_corpus.validate --cards data/realism/cards data/corpus/v0/personas/*.json
python scripts/corpus_audit.py > docs/evidence/W4_코퍼스동결.txt
```

파인튜닝용 train/test 분리 준비:
- blind 배정 글 + IAA 배정 글은 **test 전용** — train 에 넣지 않는다
- `scripts/gen_partition.py` 는 인물 분류기라 train/test 용도가 아님 → `scripts/split_train_test.py` 새로 작성
- 출력: `data/corpus/v0/splits/train.jsonl`, `test.jsonl` · seed 커밋 필수 · 누수 검사 (`test` 글 id 가 `train` 에 없는지 확인)

### 수 오후~목 — 검수 100~125 스팬 ⭐ ([#210](../../issues/210))

`gold/detect/<pid>_spans.jsonl` 을 보고 고쳐 `gold/<pid>_spans.jsonl` 로 저장한다 (계약 경로 · label-schema §8). A 인물 26명 중 100~125 스팬. 스팬당 1~2분이면 3~4시간.

### ~~목 — IAA 계산~~ ✅ #188 머지 — 2차는 [#200](../../issues/200) 기준 합의 뒤 새 표본으로

### 수(개별 보고에 같이)~목 — 설계서 데이터 파트 초안 · 금 — 최종 + `w04` 태그 지원

### 만들 것

```
data/corpus/v0/gold/iaa/A_spans.jsonl        IAA 라벨링 (A)
docs/evidence/W4_코퍼스동결.txt              동결 선언 근거
scripts/patch_created_at.py                  (②-가 선택 시)
```

### 완료 기준

- [x] ~~IAA 1차 16편 · 등급별 F1~~ ✅ 27.0% (9/7 표본 · #221 보완 후, 보완 전 22.9%)
- [x] ~~**검수 100~125 스팬**~~ ✅ #224 머지 (78편 111스팬 · 9/10)
- [x] ~~코퍼스 v1 동결 선언~~ ✅ #220 (validate FAIL 0 · 기준 커밋 d4cf8cb · 9/9)
- [x] ~~D17·B16 처리~~ ✅ #201 전량 재생성
- [x] ~~created_at 시각(active_windows) 결정~~ ✅ #212 (편중 57%→13% · #182 종료)
- [ ] 파인튜닝 train/test 분리 — W5 로 이월 (검수 뒤라 자연스러운 순서)
- [ ] 설계서 「데이터 설계」칸 검토 — D 초안 있음(제출물/4주차), 틀린 데만

---

## B · 최진필 — 1단 탐지

> 전체 매뉴얼 [docs/roles/B-detector.md](docs/roles/B-detector.md)

### ⭐ 이번 주 B 의 두 과제

1. ~~**도달 가능성 측정 → 중단 기준 판정 완료**~~ ✅ **HOLD** — implicit 86.5% · inferential 42.4% ([#202](../../pull/202) Gemini 출력 파일 추가 후 머지). #201 뒤 새 코퍼스로 재측정 (`extract_clues → 3종 → compare`)
2. **1단 파인튜닝 착수** (W4 신규) — 순서: PM 교사 라벨(9/8 밤, #204) → `gold/detect/` 로 BIO 변환기 먼저 연결(목) → A·B·D·E 검수(수~목) → 검수분 `gold/<pid>_spans.jsonl` 로 교체 → 파인튜닝. 검수분 없이 detect 로 파이프라인만 검증한다

### ~~월 오후 — LLM 도달 가능성 측정 시작~~ ✅ [#202](../../pull/202) 9/8

`experiments/exp01-baseline/results/metrics.json` 에 `llm_recovers: 0` 으로 남아있다. LLM 상한을 채운다.

```
대상: 기존 도구 3종이 모두 놓친 스팬 98개
LLM:  Gemini (생성/교사 어느 쪽과도 겹치지 않는 유일한 자리)
측정: 그 98개 중 LLM 이 잡는 비율 — 등급별로
```

**게이트 임계값**: implicit ≥ 60% AND inferential ≥ 60%

### ~~화 — 중단 기준 판정 기록~~ ✅ HOLD (9/8) — 멘토링 안건: inferential 42% 는 「문장 하나만 준 측정」이라 구조적으로 낮다

미탐 공간 (W3 확정) + 도달 가능성 (W4 측정) → 판정.

```
미탐 공간 결과 (W3):
  implicit   50.0%  ≥ 45% ✅
  inferential 51.6%  ≥ 45% ✅

도달 가능성 (W4 측정 후):
  implicit   ?% vs 60%
  inferential ?% vs 60%

판정: 둘 다 넘으면 통과 · 하나만 넘으면 보류 · 둘 다 미달이면 중단
```

`experiments/exp01-baseline/results/metrics.json` 에 `gate_decision` 을 기록하고 커밋.

### 수~목 — 검수 100~125 스팬 ([#210](../../issues/210)) + 파인튜닝 데이터 준비

골드셋 스팬 → 1단 학습 포맷 변환.

```python
# 입력 형식 (검토):
# {text: "...", spans: [{start, end, type, level}...]}
# 학습 포맷: token classification (BIO) — A·B 합의
```

- `data/corpus/v0/gold/*_spans.jsonl` (검수분) 을 학습 입력으로 — **아직 없다.** 교사 라벨([#204](../../issues/204)) → 검수 뒤에 생긴다. 그 전엔 `gold/detect/` 탐지본으로 파이프라인만 연결
- B 몫 검수: 교사 라벨이 나오면 B 인물 21명 100~125 스팬
- blind + IAA 배정 글은 **test 전용으로 격리** (A 와 협의)

### 수~금 — 파인튜닝 환경 세팅 + 첫 학습 잡

```bash
# 환경 확인
python -c "import torch; print(torch.cuda.is_available())"
# 첫 학습 잡 — 에포크 1, 소규모 체크
```

**이번 주는 「돌아가는지」 확인이 목표**. 최소 epoch 1 종료 + exit code 0 + checkpoint 저장. 성능은 W5 에서.

⚠️ **학습 잡 전에 2단 라벨(QLoRA 입력) 위치를 D 와 확인한다.** D 의 학습 잡도 같은 데이터가 필요하다.

### 금 — 설계서 1단 파트 + 베이스라인 비교표

exp01 수치 (미탐 공간 + 도달 가능성) 를 표로 정리해 설계서에 넣는다.
⚠️ exp01 채점이 `type-agnostic` — 계약상 주 지표는 type 일치 + IoU ≥ 0.5 이므로, 설계서에 「재채점 예정」 또는 현 수치의 한계를 명시.

### 만들 것

```
experiments/exp01-baseline/results/metrics.json   LLM 도달 가능성 + 판정 기록 ⭐
experiments/exp06-finetune/                       파인튜닝 첫 잡 결과
```

### 완료 기준

- [x] ~~**LLM 도달 가능성 측정** — 등급별~~ ✅ #202
- [x] ~~**중단 기준 판정 기록**~~ ✅ HOLD (9/8) → **PASS** (DEC-006 · inferential 게이트 제외 · #231)
- [x] ~~#202 에 Gemini 출력 파일 추가 → 머지~~ ✅ `results/gemini_labeled.jsonl`
- [x] ~~#201 뒤 재측정~~ ✅ #233 (p2.3 설계 단서 967건 · 미탐 47.3% · 도달 implicit 83.4% → PASS) · #228 머지 (Opus 4.8 재측정 · inferential 51.5%)
- [x] ~~B 인물 21명 검수 100~125 스팬~~ ✅ #222 머지 (78편 114스팬 · 9/9)
- [x] ~~검수 골드 BIO 변환기~~ ✅ #236 머지 (학습 대상 391편 555스팬 789채널 · 9/11)
- [x] ~~파인튜닝 학습 잡 최소 1회 성공~~ ✅ #240 (과적합 F1 0.9157 · 전체 1 epoch F1 0.0602 · o_weight 진단 완료 · 9/11)
- [ ] 설계서 「모델 설계」칸 1단 부분 검토 — D 초안 있음

---

## C · 신정현 — 특정성·누적

> 전체 매뉴얼 [docs/roles/C-specificity.md](docs/roles/C-specificity.md)

### ~~월 — PR #181 수정 재제출~~ ✅ 머지됨 (9/7)

### 월 오후 — ~~PR #191 Draft → Ready 전환~~ ✅ 머지됨 (9/7)

jhyun114 로 작업한 blind 라벨링(110스팬)을 Ready 상태로 전환해 머지 가능 상태로 만든다.

### ~~화 — IAA 파일럿 라벨링~~ ✅ 9/7 실측 22.9% (partial) · exact 0% → #221 보완 후 27.0% · exact 5.4%

갈린 자리 넷(경계·수준·누락·유형)은 [#200](../../issues/200) 에서 A 와 기준을 맞춘 뒤, **새 표본 16편**으로 2차 — 옛 표본은 재생성으로 무효.

### 화~ — blind 200 재라벨 ⭐ ([#201](../../pull/201) 합의)

9/8 코퍼스 전량 재생성으로 blind 배정 글의 본문이 전부 바뀌었다. `gold/blind/_assignment.json` 배정은 그대로, **새 본문으로 다시 매긴다.** 조건은 같다 — 교사 출력(`gold/detect/`)을 **열지 않고** 독립으로 매긴다. 교사 라벨은 9/8 밤 이미 돌았으니 순서가 아니라 열람 여부가 조건이다.

```
저장: data/corpus/v0/gold/blind/<pid>_spans.jsonl  (덮어쓰기)
기록: 기존 110스팬은 이전 코퍼스 기준 진단 기록으로 보존 — 파일명에 판을 붙이거나 git 이력으로
```

### ~~화~수 — 행정구역 계층 사전 완성 ([#115](../../issues/115))~~ → **PM(D) 이 가져감** ([#210](../../issues/210) · 전원 확인 9/8)

blind 200 재라벨이 C 단독 몫이라 이번 주 C 부하가 가장 크다. 지명 사전 계층·L1 픽스처·설계서 특정성 초안을 D 가 대행한다. C 는 결과를 검토만 한다.

### ~~목 — IAA 계산~~ ✅ [#188](../../pull/188) 머지 (9/7) — 2차 IAA 때 같은 스크립트로

### ~~목~금 — 특정성 L1 픽스처 테스트 완성~~ → D 대행 (#210)

### 목 — 설계서 특정성 파트: D 가 C-specificity.md 로 초안 → C 30분 검토 (#210) · 금 최종

### 완료 기준

- [x] ~~PR [#181](../../pull/181) 수정·재제출~~ ✅
- [x] PR [#191](../../pull/191) 머지 (9/7)
- [x] ~~IAA 1차 16편 · 등급별 F1~~ ✅ 27.0% (9/7 표본 · #221 보완 후, 보완 전 22.9%)
- [ ] [#200](../../issues/200) 기준 합의 → 새 표본 2차 IAA (A 와)
- [ ] **blind 200 재라벨** ⭐ — #229 올림(159편 195스팬) → 계약 항목 5개 맞춰 재제출 (리뷰 참조)
- [ ] ~~행정구역 계층 픽스처~~ → D 대행 #218 리뷰
- [x] ~~특정성 L1 fixture~~ ✅ D 대행 19/19 · pytest 18 (#218)
- [ ] 설계서 특정성 파트 — D 초안 검토 30분

---

## D · 박재현 — 2단 추론·조치 (+ PM)

> 전체 매뉴얼 [docs/roles/D-stage2.md](docs/roles/D-stage2.md)

### 월 오전 — 킥오프 진행 + 결정 ①②③④

Qwen3 크기는 **4B 로 이미 확정** (DEC-004 · decisions.md:96). QLoRA 학습 환경 세팅에 바로 진입.

**exp05 함정 오용 참고**: 4B 64.7% vs 1.7B 91.2% — 4B 가 함정 오용이 낮아 더 안전하다.
(숫자 해석: 34개 인물 중 1.7B=31명, 4B=22명이 함정을 잘못 근거로 사용)

### 월~화 — 설계서 초안 구성

각 역할 파트를 취합하는 뼈대를 먼저 만들어둔다.

```
(설계서 원고는 드라이브 · 제출물/4주차 — DEC-003. 각자 절은 PM 이 직접 받는다)
```

### 화~수 — QLoRA 환경 세팅

```bash
# 체크리스트
pip show peft bitsandbytes trl
# 확정된 모델 크기로 첫 실험 설정
```

**이번 주는 환경 세팅 + 첫 학습 잡 1회** — 수렴 여부는 W5 에서 본다.

### 수~목 — 검수 24명 100~125 스팬 · C 대행분 (지명 사전 계층 #115 · L1 픽스처 · 설계서 특정성 초안) · 멘토링 준비

#210 으로 C 부하를 흡수했다. 검수 4h + 지명 사전 4h + 픽스처 3h + 특정성 초안 2h.

### 수 — 개별 보고 취합

```
docs/mentoring/W04-보고-포인트.md     ← 신규
```

**목요일 멘토링 안건:**
1. **G2 지표 갱신 승인** — exp01·exp05 수치를 보고 [목표] 지표 갱신
2. **중단 기준 판정 보고** (B 결과 가져감)
3. AWS 크레딧 사용 조건 확인

### 수 23:59 — 개별 보고 5줄 취합

```
1. 이번주 내 목표:
2. 실제로 한 일:
3. 달라진 것 (before → after, 숫자):
4. 증빙 링크:
5. 막힌 것 + 필요한 지원:
```

### 목 20:00 — 멘토링

### 금 — 설계서 최종 제출 + `w04` 태그

```bash
bash scripts/tag_week.sh w04
```

### PM 몫

| 언제 | 무엇 |
|---|---|
| 월 10:00 | **킥오프 45분** — ①Qwen3 ②created_at ③D17/B16 ④골드셋 현황 |
| 화 | 개인 AWS 크레딧 확인 (MF-015 후속) |
| **수~목** | 검수 24명 · C 대행분(#115·픽스처·특정성 초안) · 목 설계서 초안 취합 + 멘토링 질문 |
| 수 23:59 | 개별 보고 5줄 취합 |
| **목 20:00** | 멘토링 — **G2 지표 갱신 승인** 포함 ⭐ |
| 금 | 설계서 최종 + 주간보고 + `w04` 태그 |

### 만들 것

```
(설계서 원고 — 드라이브 · 제출물/4주차. 자기 절은 PM 에게 직접 보낸다)
docs/mentoring/W04-보고-포인트.md
experiments/exp07-qwen3-finetune/      QLoRA 첫 잡 결과 (디렉터리만이라도)
models/registry.md                    Qwen3 크기 확정 기록
```

### 완료 기준

- [x] ~~**킥오프에서 ①②③④⑤ 확정 + 기록**~~ ✅ 9/7
- [x] ~~QLoRA 첫 학습 잡 1회~~ ✅ #214 (dev loss 0.005 · 함정 배제 15/18)
- [x] ~~D 인물 24명 검수~~ ✅ #217 (95편 135스팬) · S01·S01b #227 (40편 42스팬 · 승인 대기)
- [x] ~~C 대행: 지명 사전 계층 #115 · L1 픽스처 · 설계서 특정성 초안~~ ✅ #218 (UNKNOWN 18→2 · 픽스처 19/19) · §3 초안
- [x] ~~교사 라벨 8샤드 완료~~ ✅ #215 (115명 3,092편 3,169스팬)
- [x] ~~멘토링 질문~~ → 2건(G2 지표 · AWS). HOLD 건은 우리 결정(DEC-006)으로 처리
- [x] ~~설계서 취합·제출~~ ✅ hwp 완성 · 멘토링 결과 기입 완료 (9/10)
- [x] ~~금 취합~~ ✅ 417편 587스팬 · `gold/README.md` 상태표 · `w04` 태그 (9/11)

---

## E · 이지희 — 시스템·컴플라이언스

> 전체 매뉴얼 [docs/roles/E-system.md](docs/roles/E-system.md)

### 월~화 — 시딩 스크립트

합성 코퍼스 → SNS DB 에 자동 삽입하는 스크립트를 만든다.

```python
# scripts/seed_sns.py
# 입력: data/corpus/v0/posts/*.jsonl + data/corpus/v0/personas/*.json
# 출력: apps/sns/db 에 삽입 (SQLite or 직접 INSERT)
# 필드: title, body, photo_captions, created_at, user_ref (persona_id)
```

**A 와 협의**: 코퍼스 v1 동결 후 확정본으로 시딩한다. 동결 전 실행하면 다시 해야 한다.

### 화~수 — apps/sns 미완 부분 점검

v0 확인:
- 활동 메타 필드 (`created_at` · `visibility` · `nickname`) — schema.sql 에 이미 있음 ✅. W6 에 기능으로 연결.
- `test_export.py` 통과 여부 확인 (`GET /api/export/<user_ref>`)

```bash
cd apps/sns && python -m pytest test_export.py -v
```

⚠️ 시딩 시 `user_ref` 는 `persona_id` 가 아니라 `u_[0-9a-f]{8,}` 형식으로 별도 생성한다 (`sns-minimal-spec.md` 계약).

### 수~목 — E 인물 21명 검수 100~125 스팬 ([#210](../../issues/210)) · 설계서 시스템 파트 초안은 수 개별 보고에 같이, 늦어도 목

```
시스템 아키텍처 (SNS ↔ 분석기 경계)
배포 계획 (AWS 크레딧 범위)
수동 업로드 경로 계획 (W5 구현 예정)
```

### 목~금 — 설계서 완성 + 무료 배포 가능 범위 확인

멘토링 후속: **AWS 크레딧 조건 + 무료 배포 범위** (대회 제출 요건).

### 만들 것

```
scripts/seed_sns.py                    코퍼스 → SNS 시딩
(설계서 시스템 파트 — PM 에게 직접 보낸다. 원고는 드라이브 · DEC-003)
```

### 완료 기준

- [x] ~~시딩 스크립트 PR~~ ✅ #237 머지 (9/11)
- [x] ~~E 인물 21명 검수 100~125 스팬~~ ✅ #225 머지 (126편 185스팬 · 9/10)
- [x] ~~`test_export.py` 통과~~ ✅ 10 passed (9/10 main)
- [x] ~~설계서 시스템 파트~~ ✅ §5 초안 전달 → 반영됨(제출물/4주차 · 「서비스·화면」칸)
- [ ] AWS 크레딧 조건 확인 — 멘토링 뒤

---

## 이번 주 일정

| 요일 | 시각 | 누가 | 무엇 |
|---|---|---|---|
| **월 9/7** | 10:00 | 전원 | ~~킥오프 45분~~ ✅ ①~⑤ 결정 |
| 월~화 | | B | ~~도달 가능성 측정·판정~~ ✅ HOLD (#202) |
| 화 9/8 | | A·C | ~~IAA 파일럿~~ ✅ 27.0% (9/7 표본 · #221 보완 후) → #200 조정 |
| 화 | | D | 115명 3,052편 p2.3 재생성 머지(#201) · 교사 라벨 8병렬 대행 시작(22:43, #204) · QLoRA 첫 잡 · #210 계획 변경 전원 확인 |
| **수 9/9** | 오전 | A | 코퍼스 v1 **동결 선언** + train/test 분리 |
| 수 | 오전 | D | p2.3 통독 확인 · 교사 라벨 완료 → `gold/detect/` 알림 |
| **수~목** | | **A · B · D · E** | **검수 각 100~125 스팬** → `gold/<pid>_spans.jsonl` ⭐ |
| 수~금 | | **C** | **blind 200 재라벨** (교사 출력 보기 전) ⭐ |
| 수~목 | | D | C 대행분 — 지명 사전 계층 #115 · L1 픽스처 · 설계서 특정성 초안 (#210) |
| 수~목 | | E | 시딩 스크립트(동결 후) + apps/sns 점검 |
| **수 23:59** | | 팀원 5명 | 개별 보고 5줄 |
| **목 9/10** | | B | 재측정(새 코퍼스) · BIO 변환기 `gold/detect/` 연결 |
| 수 23:59~목 | | 전원 | **설계서 파트 초안** — 수 개별 보고에 같이, 늦어도 목 (#210) |
| **목 20:00** | | 전원+멘토 | **멘토링** — 질문 3건 (HOLD · IAA · v0 라벨) ⭐ |
| **금 9/11** | | D(PM) | 검수 취합 → **골드셋 600~700** |
| 금 | | E | AWS 크레딧 조건 확인 |
| **금 마감 전** | | D(PM) | 설계서 최종 제출 + 주간보고 + `w04` 태그 |

---

## 이번 주 반드시 지킬 것 3가지

**① blind 200 은 C 가 교사 출력을 보기 전에 매긴다.** (IAA 1차는 끝났다 — 2차도 같은 원칙)
C 는 `gold/detect/` 를 열지 않는다. 검수하는 A·B·D·E 는 반대로 detect 를 보고 고친다.

**② 코퍼스 v1 동결 전에는 파인튜닝 데이터를 확정하지 않는다.**
9/8 p2.3 전량 재생성([#201](../../pull/201))이 동결 후보다. 수요일 동결 선언 후에 분리 — blind·IAA 배정 글은 test 전용.

**③ 설계서 파트는 담당자가 직접 쓴다.** — 예외 하나: 이번 주 C 특정성 파트는 D 가 C-specificity.md 로 초안을 쓰고 C 가 검토·수정한다 ([#210](../../issues/210) 전원 확인). 담당자가 최종 책임을 지는 건 같다.
수치는 실험 결과에서, 방법론은 각 역할 매뉴얼에서 가져온다.

---

## 막히면

| 상황 | 어떻게 |
|---|---|
| LLM API 키가 없다 | Gemini API key — PM 에게 확인 (KISIA 제공 Claude key 와 별개) |
| QLoRA 메모리 부족 | 배치 사이즈 절반으로, 그래도 안 되면 D 에게 |
| IAA 스크립트 오류 | PR #188 이슈에 로그 붙여 C(jhyun114) 에게 |
| PR 머지가 안 된다 | nuewsun 에게 리뷰 요청 — 재촉하지 말고 한 번만 |
| 설계서 양식이 없다 | D 가 드라이브 `제출물/4주차/W04_설계서_원고.md` 뼈대를 공유한다 (저장소엔 두지 않는다 · DEC-003) |
| 앞사람 산출물이 안 온다 | 사슬 위 작업이면 PM 에게 즉시. 사슬 밖이면 가짜 데이터로 먼저 |
| 명령이 Windows 에서 안 된다 | Git Bash 쓰거나 각 절의 PowerShell 대안 |

전체 규칙은 [docs/RULES-DO-NOT.md](docs/RULES-DO-NOT.md).

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
│  ├─ corpus/v0/gold/blind/       blind 분 (C · #229 재제출 대기)
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

## 현재 미결 (9/13 기준)

**PR** — #229 C blind 200 재제출 대기

**이슈 — W5**
- [ ] test set 구성 방향 결정 (A · PM) — 킥오프에서 확인
- [ ] [#200](../../issues/200) IAA 2차 — C #229 완료 후 A·C 착수
- [ ] [#223](../../issues/223) label-schema §3-2 배우자 호칭 A 옵션 1줄 추가 (A)
- [ ] AWS 크레딧 조건 확인 (E · 멘토링 후)
- [ ] [#206](../../issues/206) #201 후속 추적 — 각자 인물 JSON 확인

**장기**
- [ ] [MF-015](docs/mentor-log.md) 대회 제출 요건·배포 범위 확인 — PM · 기한 9/18 전
- [ ] AWS 크레딧 조건 확인 — E · 금
- [ ] 잡담 글 「단서 0」 계약 vs 자영업·농업 인물의 삶 (#201 남은 쟁점) — v2
