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

**W3 코드·코퍼스 완료, 골드셋·판정 W4 이월** — [compare/w02...w03](../../compare/w02...w03)

| 항목 | W3 시작 | W3 끝 |
|---|---|---|
| 인물 | 35명 | **115명** ✅ |
| 글 (커밋) | 0편 | **3,092편** ✅ (E15 중복 5줄 제거 · D17·B16 14편 재생성 [#196](../../pull/196)) |
| 코퍼스 결함 | — | clue null 버그 수정 · 2,792편 패치 ([#189](../../pull/189) ✅) · 재탕 원인은 잡담 소재 순환 → p1.3 ([#196](../../pull/196) ✅) |
| 베이스라인 미탐 | — | **implicit 50.0% · inferential 51.6%** (임계값 45% 초과) ✅ ⚠️ type-agnostic 채점 — W4 재채점 필요 |
| LLM 도달 가능성 | — | **PENDING** — W4 이월 ⚠️ |
| Qwen3 크기 | — | **4B 확정** (DEC-004) — exp05 완료, decisions.md 기록 ✅ |
| 가상 SNS | — | **v0 골격 완성** (apps/sns/) ✅ — 활동 메타(visibility 등) schema.sql 포함 |
| §13 규제 매핑표 | — | **확정** ✅ ([#179](../../pull/179) merged) |
| blind 라벨링 | — | **150편 · 110스팬 main 에 있음** ([#191](../../pull/191) ✅ 9/7) — offset 110/110 · 스팬 0인 글 56편도 `reviewed` 로 기록 |
| IAA | — | 16편 배정 ([#192](../../pull/192) ✅) · A·C 라벨링 → 실측 W4 |
| 교차모델 exp04 | — | Claude vs GPT-5.5 · **둘 다 값 19/20 (0.95)** · 공동 기권 22칸 분리 ([#195](../../pull/195) 리뷰 중) — 임계값 없는 방어 ⑤ |
| QLoRA 환경 | — | **3060 8GB 상한 seq 1024 · 피크 5.1GB** ([exp07](experiments/exp07-qwen3-finetune/)) · 2단 라벨 형식 초안 [`gold/stage2/`](data/corpus/v0/gold/stage2/README.md) |
| 골드셋 검수 | — | A·B·D·E 분량 — 월요일 킥오프에서 취합 |
| 지명 사전 | — | 픽스처 **8/18** (W3 완료) — 나머지 W4 이월 |

| 역할 | 담당 | **다음 주 핵심** |
|---|---|---|
| **[A · 데이터 리드](docs/roles/A-data.md)** | 이은선 | **코퍼스 v1 동결** + IAA 파일럿 |
| **[B · 1단 탐지](docs/roles/B-detector.md)** | 최진필 | **LLM 도달 가능성** 측정 → 판정 + **파인튜닝 착수** |
| **[C · 특정성·누적](docs/roles/C-specificity.md)** | 신정현 | **행정구역 계층 사전** + IAA 파일럿 |
| **[D · 2단 추론·조치](docs/roles/D-stage2.md)** | 박재현 (PM) | **QLoRA 착수** + **설계서 취합** |
| **[E · 시스템·컴플라이언스](docs/roles/E-system.md)** | 이지희 | **시딩 스크립트** + 설계서 |

---

# W4 (9/7~9/13) — 각자 할 일

**제출물**: 모델·서비스 설계서 (외부) + 주간활동보고서 (외부)
**단계**: **M2-a 시작** · 근무일 5일

> ## 이번 주 한 문장 — **W3에서 쌓은 재료로 파인튜닝에 들어간다.**
>
> 로드맵 §3:
>
> > **G2 게이트**: M1 실측 반영 → 멘토 승인 하에 지표 1회 갱신.
>
> 코퍼스는 이번 주 안에 동결한다. 동결 이후에는 재생성이 없다.
> **설계서가 이번 주 유일한 외부 제출물**이다 — 판단 근거(exp05·exp01 수치)를 문서에 박는다.

---

## 0. 월요일 킥오프 — 10:00, 45분

### 먼저 받기 (5분)

```bash
git pull
pip install -e .
```

### 월요일에 정할 것 다섯

#### ① 1단 학습 포맷 결정 — 담당 A·B ✅

```
결정: (가) BIO 태깅 — token classification (HuggingFace Trainer 직결)
```

**A·B 합의 완료.** B 는 화~수 골드셋 스팬을 BIO 학습 포맷으로 변환한다.

#### ② created_at 버그 처리 방향 ([#182](../../issues/182)) — 담당 A · **(가) 로 결정** (9/7)

```
결정: (가) generated_at 역산 — 재생성 없이 스크립트로 전체 posts 의 created_at 을 재계산해 덮어쓴다
남은 것: 시각을 typical_active_hours 정규식 파싱으로 할지, 인물 JSON 에 active_windows 를 추가할지 — A
```

`scripts/patch_created_at.py` 는 A 가 만든다 (`A-data.md` W4 실무 §3 에 역산식이 있다).

#### ③ D17·B16 재생성 ([#184](../../issues/184)) — ✅ [#196](../../pull/196) 머지 (9/7)

```
원인 정정: resume 오류가 아니라 잡담 소재 순환 — D17 은 소재 13개에 잡담 22편이라 b19 부터 b01 소재로 되돌아갔다
처리:     D17 12편 · B16 2편 재생성 + prompts p1.3 (소재 반복 시 앞 글 제목·첫 문장 힌트)
결과:     첫 문장 동일 쌍 D17 8 → 1 (남은 건 기존 글끼리) · B16 0
라벨:     blind D17_b22 는 C 가 재검토해 판정 유지 · B16_b21·b26 은 본문 그대로
```

#### ④ cross-persona 중복 · S14 미달 처리 ([#183](../../issues/183), [#177](../../issues/177)) — 전원

```
#177: ✅ S14 카드 40 → 28자 · 인물 5명 선언값을 실측 평균으로 하향 (#197 머지 9/7). 재생성 없음
#183: 동일 도입부 문장 40건 cross-persona — 측정 지표 보정 vs 재생성 vs 수용  ← 아직 미결
```

**#183 이 동결 선행조건**이다. 수요일 동결 선언 전에 확정.

#### ⑤ 골드셋 검수 현황 취합 · 2단 라벨 형식

A·B·D·E 각자 지금까지 검수한 스팬 수를 취합한다.
**파인튜닝 데이터로 쓸 수 있는 분량이 얼마인지** 이번 주 안에 확인해야 한다.

2단 학습 라벨 형식은 D 가 초안을 올렸다 — [`data/corpus/v0/gold/stage2/README.md`](data/corpus/v0/gold/stage2/README.md). **A(형식)·B(교사 스팬이 오면 1단·2단이 같은 `*_spans.jsonl` 을 읽는 구조) 확인 필요.**

---

## ⚠️ W3 이월 항목 — 이번 주 해소 대상

| 항목 | 담당 | 기한 |
|---|---|---|
| **LLM 도달 가능성 측정** → 중단 기준 판정 | **B** | **화** |
| **IAA 파일럿** (A·C 같은 20편 라벨링) | **A · C** | **화** |
| **IAA 계산** (PR [#188](../../pull/188) 활성화) | **A · C** | **목** |
| ~~PR #191 · #189 · #192 · #181 머지~~ | ✅ 9/7 전부 main | — |
| PR [#180](../../pull/180) 머지 (문장 분리기 fix) | nuewsun (리뷰 후) | — |
| PR [#195](../../pull/195) exp04 교차모델 — `via` 확인 후 머지 | B 답 → PM | — |
| created_at 패치 ([#182](../../issues/182) · (가) 결정됨) | A — 시각 처리 방식 정한 뒤 스크립트 | **수** |
| ~~D17·B16 재생성~~ | ✅ [#196](../../pull/196) | — |
| ~~S14 미달 ([#177](../../issues/177))~~ | ✅ [#197](../../pull/197) | — |
| cross-persona 중복 처리 방향 ([#183](../../issues/183)) | 전원 결정 | **월** ← 미결 |
| 2단 라벨 형식 초안 확인 ([`gold/stage2/`](data/corpus/v0/gold/stage2/README.md)) | A·B | **화** |

---

## 전원 공통 — 설계서 자기 파트 완성

이번 주 외부 제출물은 **모델·서비스 설계서** 하나다.
각 역할이 자기 파트를 맡아 **수요일까지 초안, 금요일 최종**으로 낸다.

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

### 화 — IAA 파일럿 라벨링

`data/corpus/v0/gold/iaa/_assignment.json` 의 16편을 C 와 **독립적으로** 라벨링한다.

```
저장: data/corpus/v0/gold/iaa/A_spans.jsonl    ← 파일명 규칙 확인 필요
형식: label-schema §8-1 (8필드)
주의: C 가 매긴 값을 보기 전에 완료
```

### 화~수 — 코퍼스 v1 동결 준비

1. ~~**D17·B16 재생성**~~ ✅ [#196](../../pull/196) — D 가 돌렸다. 원인은 잡담 소재 순환(p1.3 로 수정)
2. **created_at 처리** (킥오프 결정에 따라): (가) 선택 시 `patch_created_at.py` 작성 후 전체 덮어쓰기
3. **E15.jsonl** git status 에 `M` 으로 표시됨 — 내용 확인 후 커밋

### 수 — 코퍼스 v1 동결 선언 + 파인튜닝 데이터 정리

```bash
# 동결 확인 — validate ERROR 0건이 합격선 (audit 은 판정하지 않으므로 참고용)
python -m kopl.c5_corpus.validate --cards data/realism/cards data/corpus/v0/personas/*.json
python scripts/corpus_audit.py > docs/evidence/W4_코퍼스동결.txt
```

파인튜닝용 train/test 분리 준비:
- blind 배정 글 + IAA 배정 글은 **test 전용** — train 에 넣지 않는다
- `scripts/gen_partition.py` 는 인물 분류기라 train/test 용도가 아님 → `scripts/split_train_test.py` 새로 작성
- 출력: `data/corpus/v0/splits/train.jsonl`, `test.jsonl` · seed 커밋 필수 · 누수 검사 (`test` 글 id 가 `train` 에 없는지 확인)

### 목 — IAA 계산 (C 와 함께)

C 가 PR [#188](../../pull/188) 의 `scripts/iaa.py` 를 활성화하면 함께 돌린다.

```bash
python scripts/iaa.py \
  data/corpus/v0/gold/iaa/A_spans.jsonl \
  data/corpus/v0/gold/iaa/C_spans.jsonl
```

**등급별 F1 을 G2 지표에 반영한다.**

### 금 — 설계서 데이터 파트 + `w04` 태그 지원

### 만들 것

```
data/corpus/v0/gold/iaa/A_spans.jsonl        IAA 라벨링 (A)
docs/evidence/W4_코퍼스동결.txt              동결 선언 근거
scripts/patch_created_at.py                  (②-가 선택 시)
```

### 완료 기준

- [ ] IAA 라벨링 16편 완료 — C 보기 전에 ⭐
- [ ] IAA 등급별 F1 산출 완료
- [ ] 코퍼스 v1 동결 선언 (audit + validate 통과)
- [ ] D17·B16 처리 완료 (재생성 또는 문서화)
- [ ] created_at 처리 완료 (수정 또는 문서화)
- [ ] 파인튜닝 train/test 분리 완료
- [ ] 설계서 데이터 파트 완성 (금)

---

## B · 최진필 — 1단 탐지

> 전체 매뉴얼 [docs/roles/B-detector.md](docs/roles/B-detector.md)

### ⭐ 이번 주 B 의 두 과제

1. **도달 가능성 측정 → 중단 기준 판정 완료** (W3 이월)
2. **1단 파인튜닝 착수** (W4 신규)

### 월 오후 — LLM 도달 가능성 측정 시작

`experiments/exp01-baseline/results/metrics.json` 에 `llm_recovers: 0` 으로 남아있다. LLM 상한을 채운다.

```
대상: 기존 도구 3종이 모두 놓친 스팬 98개
LLM:  Gemini (생성/교사 어느 쪽과도 겹치지 않는 유일한 자리)
측정: 그 98개 중 LLM 이 잡는 비율 — 등급별로
```

**게이트 임계값**: implicit ≥ 60% AND inferential ≥ 60%

### 화 — 중단 기준 판정 기록

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

### 화~수 — 파인튜닝 데이터 준비

골드셋 스팬 → 1단 학습 포맷 변환.

```python
# 입력 형식 (검토):
# {text: "...", spans: [{start, end, type, level}...]}
# 학습 포맷: token classification (BIO) — A·B 합의
```

- `data/corpus/v0/gold/*_spans.jsonl` (검수분) 을 학습 입력으로
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

- [ ] **LLM 도달 가능성 측정** — 등급별 (implicit · inferential) ⭐
- [ ] **중단 기준 판정 기록** (통과/보류/중단) ⭐
- [ ] 파인튜닝 학습 잡 최소 1회 성공
- [ ] 설계서 1단 파트 완성

---

## C · 신정현 — 특정성·누적

> 전체 매뉴얼 [docs/roles/C-specificity.md](docs/roles/C-specificity.md)

### 월 — PR #181 수정 재제출

[#181](../../pull/181) 이 CHANGES_REQUESTED 상태다. 리뷰 코멘트를 확인하고 이번 주 안에 수정·재제출.

### 월 오후 — ~~PR #191 Draft → Ready 전환~~ ✅ 머지됨 (9/7)

jhyun114 로 작업한 blind 라벨링(110스팬)을 Ready 상태로 전환해 머지 가능 상태로 만든다.

### 화 — IAA 파일럿 라벨링

`data/corpus/v0/gold/iaa/_assignment.json` 의 16편을 A 와 **독립적으로** 라벨링한다.

```
저장: data/corpus/v0/gold/iaa/C_spans.jsonl
주의: A 가 매긴 값을 보기 전에 완료
      blind 와 달리 IAA 는 교사 라벨을 봐도 된다 (IAA = 동일 글 두 라벨러 비교)
```

### 화~수 — 행정구역 계층 사전 완성 ([#115](../../issues/115))

W3 에서 픽스처 3/18 + ①②④ 일부. 이번 주에 **18/18 완성 또는 미해결 격리** 를 목표로 한다.

```
남은 것:
  ③ 법정동 → 행정동 (10건) — PR #181 (KIKmix) 머지되면 자동 해소
  남은 미해결 지명은 UNKNOWN 격리 + 제외 인물 수 기록
```

PR #181 이 이번 주 머지되면 ③ 가 같이 해소된다.

### 목 — IAA 계산

A 와 함께 PR [#188](../../pull/188) `scripts/iaa.py` 를 실행한다.

```bash
python scripts/iaa.py \
  data/corpus/v0/gold/iaa/A_spans.jsonl \
  data/corpus/v0/gold/iaa/C_spans.jsonl
```

**등급별 F1 결과를 G2 지표에 반영.** PR #188 을 Draft → Ready 로 전환해 머지 요청.

### 목~금 — 특정성 L1 픽스처 테스트 완성

```bash
python -m kopl.c2_specificity.test_l1
```

R1~R6 기대값과 일치하는지 확인.

### 금 — 설계서 특정성 파트

### 완료 기준

- [ ] PR [#181](../../pull/181) 수정·재제출 (월) ⭐
- [x] PR [#191](../../pull/191) 머지 (9/7)
- [ ] IAA 라벨링 16편 완료 — A 보기 전에 (화) ⭐
- [ ] **IAA 등급별 F1 산출** + PR #188 Ready 전환 (목) ⭐
- [ ] 행정구역 계층 픽스처 — 해소 또는 UNKNOWN 격리 완료
- [ ] 특정성 L1 fixture 18/18 (또는 미해결 문서화)
- [ ] 설계서 특정성 파트 완성

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
docs/design/W04-모델서비스설계서.md    ← 이번 주 신규
```

### 화~수 — QLoRA 환경 세팅

```bash
# 체크리스트
pip show peft bitsandbytes trl
# 확정된 모델 크기로 첫 실험 설정
```

**이번 주는 환경 세팅 + 첫 학습 잡 1회** — 수렴 여부는 W5 에서 본다.

### 수 — 멘토링 준비 + 개별 보고 취합

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
| **수** | 설계서 초안 취합 + 멘토링 준비 문서 |
| 수 23:59 | 개별 보고 5줄 취합 |
| **목 20:00** | 멘토링 — **G2 지표 갱신 승인** 포함 ⭐ |
| 금 | 설계서 최종 + 주간보고 + `w04` 태그 |

### 만들 것

```
docs/design/W04-모델서비스설계서.md
docs/mentoring/W04-보고-포인트.md
experiments/exp07-qwen3-finetune/      QLoRA 첫 잡 결과 (디렉터리만이라도)
models/registry.md                    Qwen3 크기 확정 기록
```

### 완료 기준

- [ ] **킥오프에서 ①②③④⑤ 확정 + 기록** ⭐
- [ ] QLoRA 첫 학습 잡 1회 (epoch 1 종료, exit code 0, checkpoint 저장)
- [ ] 멘토링 안건 3건 + G2 지표 갱신 승인 ⭐
- [ ] 설계서 취합·제출 (금)
- [ ] `w04` 태그

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

### 수 — 설계서 시스템 파트 초안

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
docs/design/W04-모델서비스설계서.md     시스템 파트 (D 취합본에 합류)
```

### 완료 기준

- [ ] 시딩 스크립트 동작 확인 (코퍼스 v1 동결 후 실행)
- [ ] `test_export.py` 통과
- [ ] 설계서 시스템 파트 완성
- [ ] AWS 크레딧 조건 확인 (금)

---

## 이번 주 일정

| 요일 | 시각 | 누가 | 무엇 |
|---|---|---|---|
| **월** | 10:00 | 전원 | **킥오프 45분** — ①Qwen3 ②created_at ③D17/B16 ④골드셋 현황 ⭐ |
| 월 | 오후 | B | LLM 도달 가능성 측정 시작 ⭐ |
| 월 | 오후 | C | ~~PR #181 · #191~~ ✅ 둘 다 머지 (9/7) |
| **화** | | **A · C** | ⭐ **IAA 파일럿 라벨링** — 16편 독립 라벨링 |
| 화 | | B | 중단 기준 판정 기록 ⭐ |
| 화~수 | | A | D17·B16 처리 + created_at 처리 (결정에 따라) |
| 화~수 | | C | 행정구역 계층 사전 완성 |
| 화~수 | | E | 시딩 스크립트 + apps/sns 점검 |
| 화~수 | | B | 파인튜닝 데이터 준비 |
| 화~수 | | D | QLoRA 환경 세팅 + 첫 학습 잡 |
| **수** | | A | 코퍼스 v1 동결 선언 + 파인튜닝 분리 |
| 수 | | D | 설계서 초안 취합 + 멘토링 준비 문서 |
| **수 23:59** | | 팀원 5명 | 개별 보고 5줄 |
| **목** | | **A · C** | **IAA 계산** (scripts/iaa.py) ⭐ |
| **목 20:00** | | 전원+멘토 | **멘토링** — G2 지표 갱신 승인 ⭐ |
| 금 | | B | 파인튜닝 1차 체크 |
| 금 | | C | 특정성 L1 fixture 확인 |
| 금 | | E | AWS 크레딧 조건 확인 |
| **금 마감 전** | | D(PM) | 설계서 최종 제출 + 주간보고 + `w04` 태그 |

---

## 이번 주 반드시 지킬 것 3가지

**① IAA 는 A·C 가 서로 보기 전에 독립 라벨링한다.**
각자 **비공개 브랜치**에서 작업 후 화요일 저녁에 동시에 PR 을 올린다.
먼저 끝났다고 파일을 공개 브랜치에 올리면 독립성이 무너진다.

**② 코퍼스 v1 동결 전에는 파인튜닝 데이터를 확정하지 않는다.**
D17·B16 재생성 여부가 train 분포에 영향을 준다. 수요일 동결 선언 후에 분리.

**③ 설계서 파트는 담당자가 직접 쓴다.**
수치는 실험 결과에서, 방법론은 각 역할 매뉴얼에서 가져온다.
다른 사람 파트를 대신 쓰거나 복붙하지 않는다.

---

## 막히면

| 상황 | 어떻게 |
|---|---|
| LLM API 키가 없다 | Gemini API key — PM 에게 확인 (KISIA 제공 Claude key 와 별개) |
| QLoRA 메모리 부족 | 배치 사이즈 절반으로, 그래도 안 되면 D 에게 |
| IAA 스크립트 오류 | PR #188 이슈에 로그 붙여 C(jhyun114) 에게 |
| PR 머지가 안 된다 | nuewsun 에게 리뷰 요청 — 재촉하지 말고 한 번만 |
| 설계서 양식이 없다 | `docs/design/` 에 없으면 D 가 빈 파일 만들어 공유 |
| 앞사람 산출물이 안 온다 | 사슬 위 작업이면 PM 에게 즉시. 사슬 밖이면 가짜 데이터로 먼저 |
| 명령이 Windows 에서 안 된다 | Git Bash 쓰거나 각 절의 PowerShell 대안 |

전체 규칙은 [docs/RULES-DO-NOT.md](docs/RULES-DO-NOT.md).

---

## 저장소 구조

```
KISIA_Project/
├─ README.md                 ← 이번 주 할 일 (이 문서)
├─ CONTRIBUTING.md           브랜치·커밋·리뷰 규칙
├─ docs/
│  ├─ overview.md            프로젝트가 뭔지
│  ├─ plan.md                계획 전문 (v2.2)
│  ├─ roadmap.md             12주 주차별 계획
│  ├─ roles/                 역할별 작업 매뉴얼 5종
│  ├─ contracts/             ⭐ 모듈 인터페이스 계약 6종 (W2 고정)
│  ├─ design/                설계서 (W4~)
│  ├─ decisions.md           결정 기록 [DEC-NNN]
│  ├─ mentor-log.md          멘토 피드백 [MF-NNN]
│  └─ RULES-DO-NOT.md        절대 하면 안 되는 것
├─ src/kopl/c1~c7/           컴포넌트별 코드
├─ data/
│  ├─ corpus/v0/personas/    인물 JSON (115명 · W4 동결)
│  ├─ corpus/v0/posts/       생성 글 (3,097편 · W4 동결)
│  ├─ corpus/v0/gold/        골드셋 검수분
│  ├─ corpus/v0/gold/blind/  blind 분 (jhyun114 110스팬 · PR #191)
│  ├─ corpus/v0/gold/iaa/    IAA 배정 + A·C 라벨링 (W4)
│  ├─ realism/cards/         리얼리즘 카드 18장
│  └─ dict/admin/            행정구역·인구 사전
├─ experiments/
│  ├─ exp01-baseline/        베이스라인 3종 + LLM 상한 (W4 완성)
│  ├─ exp05-model-size/      Qwen3 크기 비교 (W3 완료)
│  └─ exp06-finetune/        1단 파인튜닝 (W4 신규)
├─ apps/sns/                 가상 SNS (v0 완성 · W4 시딩)
└─ scripts/                  운영 스크립트
```

---

## 현재 미결

**PR — nuewsun 리뷰 대기**
- [x] [#189](../../pull/189) clue null 버그 수정 + E 인물 150편 (9/6)
- [x] [#192](../../pull/192) sample_gold.py 수정 (9/6)
- [ ] [#180](../../pull/180) 문장 분리기 자모 이모티콘 수정

**PR — 당사자 수정 필요**
- [x] [#191](../../pull/191) jhyun114 blind 110스팬 (9/7)
- [x] [#181](../../pull/181) KIKmix 법정동 조회 (9/7) · [#196](../../pull/196) D17·B16 재생성 (9/7) · [#197](../../pull/197) S14 하향 (9/7) · [#198](../../pull/198) BIO 확정 (9/7)
- [ ] [#195](../../pull/195) exp04 교차모델 — `via` 확인 후 머지
- [ ] [#188](../../pull/188) IAA 계산기 — Draft, 실측 후 Ready 전환 (A·C)
- [ ] [#181](../../pull/181) KIKmix 법정동→행정동 — CHANGES_REQUESTED 수정 (C)

**이슈 — W4 결정 후 처리**
- [ ] [#182](../../issues/182) created_at 버그 — 방향 결정 후 수정 또는 문서화
- [ ] [#183](../../issues/183) cross-persona 중복 — 처리 방향 결정
- [ ] [#184](../../issues/184) D17·B16 재생성 — 킥오프 결정 후 처리
- [ ] [#177](../../issues/177) S14 카드 문장길이 미달 — 동결 전 판단

**장기 미결**
- [ ] [#171](../../issues/171) blind 200 배정 확인
- [ ] [#124](../../issues/124) 주인 없는 산출물 4건
- [ ] [#116](../../issues/116) 코퍼스 측정 불가 (성별 단서)
- [ ] [MF-015](docs/mentor-log.md) 대회 제출 요건·배포 범위 확인 — PM · 기한 9/18 전
- [ ] AWS 크레딧 조건 확인 — PM · W4
