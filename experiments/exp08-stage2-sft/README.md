# exp08 — 2단 판정기 QLoRA SFT 첫 잡 (v0 라벨)

**무엇을 왜 재는가** — 2단(종합 판정) 모델을 Qwen3-4B 에 QLoRA 로 붙여 첫 학습이 끝까지 돌고, `findings` 형식을 내며, **함정(과거거주·출신지·방문지 등 `subject: self` 인데 현 거주지가 아닌 단서)을 근거에서 배제하는지** 본다. exp05 에서 4B 는 34명 중 22명이 이 배제를 못 했다.

## 설정 (2026-09-09)

| | |
|---|---|
| 라벨 | v0 — `scripts/build_stage2_labels.py` 가 인물 `clue_plan` 에서 결정적으로 유도 ([`gold/stage2/README.md`](../../data/corpus/v0/gold/stage2/README.md) §3-1). 교사 스팬이 오면 v1 로 교체 (#207) |
| 데이터 | `make_sft.py` — 인물 113명, 글 부분집합 증강 k=8 seed 20260907 → train 743 · dev 90 (인물 12명 단위 분리). blind·IAA 배정 글 172편은 입력에서 제외 (test 전용) |
| 모델 | Qwen/Qwen3-4B · NF4 4bit · LoRA r16 α32 q/k/v/o · seq 1408 · batch 1 × grad-accum 8 · lr 2e-4 cosine · 1 epoch (92 업데이트) |
| 하드웨어 | RTX 3060 8GB · 피크 VRAM 6.15GB · 학습 7,664s |
| 코퍼스 | corpus-v0 p2.3 (#201) |

## 결과 — `results/metrics.json` · `results/eval_dev.json`

| 지표 | 값 |
|---|---|
| dev loss | 0.4259 → **0.0048** |
| JSON 형식 | 30/30 |
| verdict 정확도 (7속성 × 30예시) | **92.9%** — commute 1.00 · age/sex .97 · income .93 · location .90 · occupation/family .87 |
| evidence span_id F1 | **0.977** (P .962 · R .992) |
| **함정 배제** | **15/18 = 83.3%** |
| 추론 | 36s/예시 (생성 ~400 토큰) |

## 해석·한계

- 타깃이 입력의 `level`·`subject` 에서 규칙으로 유도되므로 verdict 는 거의 표 조회다 — 92.9% 는 「형식과 규칙을 배웠다」는 뜻이고 능력 지표는 아니다.
- 실제로 배워야 하는 건 **함정 배제**다. 입력에 함정 표지가 없으니 시제·장소 성격(「예전에 살던」「다녀온」)으로 걸러야 한다 → 83%. 남은 3건은 W5 에 살펴본다.
- seq 1408 이 8GB 상한 — 1536 에서 VRAM 7.9GB 로 스필돼 50업데이트에서 멈춘 적이 있다 (첫 실행). 20업데이트마다 어댑터를 저장한다.
- 어댑터(46MB)는 커밋하지 않는다 (`results/adapter/`). 재현: `make_sft.py` → `train.py --max-len 1408`.

## 다음

- v1: 교사 스팬(`gold/detect/` → 검수 정본)으로 입력을 바꾸고 재학습 (#207)
- rewrites 타깃 (§3-2, 교사 LLM) — v0 에서는 비움
- W7: 외부 LLM 대비 속성 적중 일치율 ≥ 0.8 측정의 대상 모델이 이것이다

## 증류 타깃 연결 (W6 · C PR 대기)

`contribution_targets.py` — C 의 `gold/contribution/<pid>.json`(contribution.schema.json) 을 읽어
① `posts[].contribution`(delta) 입력 ② `recommendation`(greedy_path → unpublish 조치, stage2-io 계약) 출력
③ 근사기 타깃(post 별 delta·rank) 으로 바꾼다. 계약·불변식(3)(5)(6) 검증 포함.

```bash
python experiments/exp08-stage2-sft/make_sft_v1.py --contribution data/corpus/v0/gold/contribution
python -m pytest experiments/exp08-stage2-sft/test_contribution_targets.py -q   # 픽스처 = loo.leave_one_out() 출력
```

- 전체-글 예시에만 붙는다. 부분집합 증강 예시는 LOO 를 다시 못 구하므로 findings 만 (v1 결정 · 재검토 W7)
- `user_ref` 를 12자리로 맞췄다 (`scripts/seed_sns.py` · C 생성기와 동일). 이전 v1 데이터는 재생성 필요
- 근사기(#124 ①) 학습 입력은 `approximator_targets()` — 별도 태스크로 두고 C PR 머지 후 착수

## v2 준비 — 길이 확인 (2026-10-12 · D · W9 D 5번)

v2 재학습 전에 「긴 계정 예시를 넣으면 몇 개가 버려지고 8GB 에 들어가나」를 먼저 쟀다. 재현: `v2_length.py` → `results/v2_length.json` · `v2_vram.py` → `results/v2_vram.json`.

**1. v1 은 긴 입력을 거의 못 봤다** — v1 은 `--max-len 1024` 로 학습해 train 342개 중 **90개(26%)를 버렸다**(`train_v1_ep3.log` 「train 252 (버림 90)」). 버린 것의 대부분이 글 많은 예시다 — 글 4편 이상 127개 중 **86개(68%)** 가 1024 를 넘는다. 남은 학습 예시는 검수 글(인물당 10~30%)로 만든 짧은 계정이다 (글 수 중앙값 3).

**2. 앱은 그보다 두 배 긴 입력을 보낸다** — 실제 크기 계정(115명 · 계정 전체 글 · test 글 제외 · 스팬 = 교사 라벨 + 검수 골드)을 앱과 같은 가명화 · 고르기(`select_for_model` · 상한 24/6 · 스팬 없는 글도 목록에 남김)로 만들면:

| 입력 | 토큰 중앙값 | 최대 | 1024 초과 | 2048 초과 | 답변 최대 |
|---|---:|---:|---:|---:|---:|
| v1 학습 데이터 원본 | 805 | 2,480 | 90/342 | 3 | 853 |
| **지금 앱** (상한 24/6 · 빈 글 포함) | **2,280** | 2,856 | 110/115 | 73 | 873 |
| 상한 24/6 · 빈 글 제외 | 2,045 | 2,611 | 93 | 57 | 873 |
| 상한 18/5 · 빈 글 제외 | 1,950 | 2,111 | 93 | 20 | 719 |
| **상한 16/4 · 빈 글 제외** | **1,837** | **1,950** | 93 | **0** | 663 |
| 상한 12/3 · 빈 글 제외 | 1,531 | 1,605 | 93 | 0 | 574 |

exp13 에서 「전체 이력을 넣으면 규칙 판정과 0.653 만 맞는다」고 본 것과 같은 방향이다 — 학습에서 본 적 없는 길이를 앱에서 받는다. (원인이 길이 하나라고 단정하지는 않는다)

**3. 8GB 에서 2048 까지 들어간다** — `train.py` 와 같은 설정으로 학습 한 걸음(답변 900 토큰)의 피크 VRAM:

| 길이 | 지금 방식(전 구간 logits) | 답변 구간만 logits |
|---|---:|---:|
| 1408 | 5.58 GB · 5.3초 | 4.93 GB · 4.3초 |
| **2048** | 7.17 GB · 9.8초 | **5.80 GB · 7.8초** |
| 2560 | 8.21 GB (넘침) | 7.16 GB · 19.7초 (빠듯) |
| 2900 | 8.90 GB (넘침) | 8.22 GB (넘침) |

어휘가 15만 개라 logits 가 길이에 비례해 커진다. 손실은 답변에만 걸리므로 답변 구간의 logits 만 만들면(`logits_to_keep`) 같은 손실을 1.4GB 적게 계산한다.

**결론 — v2 를 계속한다** (README 「화 10/13 길이 확인」). 구성안:

- **앱 입력** — 스팬 없는 글은 모델 입력에서 뺀다(근거가 될 수 없다) · 상한 **16/4** → 모든 계정이 2048 안. 규칙 판정 · 추천 · k 는 지금처럼 전체 스팬을 쓴다
- **학습** — `--max-len 2048` · 답변 구간만 logits · v1 부분집합 예시 + **실제 크기 계정 예시**(위 2번과 같은 방식 · 인물 단위 dev 분리)
- **출력 예산** — 답변 최대 663 토큰 → 지금 `output_budget` 하한 700 안
- **v1 보존** — 어댑터를 저장소 밖에 해시와 함께 보관했다 (`adapter_model.safetensors` SHA-256 `1053e7adcc77d1863e0789978b468d29d92930dc9c26a84a0a29e7fbc99a6a4b`). v2 는 `results/adapter_v2/` 에 따로 저장한다
- **판정** — 새 판정셋 exp22 에서 v1 · v2 를 한 번씩. 교체 기준은 exp22 를 열기 전에 적는다 (README W9 D 5번)
