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
