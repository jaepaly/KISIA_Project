# Ablation 비교표 — 벤치마크 러너

> 이 문서는 **W9 안에 확정**한 ablation 목록이다. 10/29(목) 최종 측정 때 이 명령들을 순서대로 돌린다.
>
> **원칙**: 이미 쓴 판정셋은 결과 비교에만 쓰고, 조합을 고르는 데 다시 쓰지 않는다.

---

## 비교표

| # | 무엇을 묻나 | 데이터 | 지표 (실제 산출 키) | 명령 (예시) | 담당 | 비고 |
|---|---|---|---|---|---|---|
| ① | **1단 모델 단독 vs 규칙 결합** — 규칙을 붙이면 F1 이 얼마나 오르는가 | test (10/29) | partial F1 · P · R (등급별) | **B 러너 인계(10/17) 뒤 확정 — 규칙 켬/끔** | B (1단 러너) | 명령 · 옵션 이름은 B 러너 인터페이스 합의 대기. 규칙 켬/끔 각각의 1단 예측 파일이 나오면 `d_downstream.py` 는 그 파일을 그대로 받아 하류를 돌린다 |
| ② | **글 하나 vs 계정 누적** — 같은 단서도 여러 글에 걸쳐 누적되면 위험이 오르는가 | dev (개발 확인) / test (10/29) | `summary.{with_geo,spans_only}` 의 `raised_ratio`(글 하나 최댓값보다 계정 위험이 오른 사용자 비율) · `raise_among_raised`(오른 사용자의 증가폭) · `raise_all` · `single_max_mean` · `account_mean` | `python experiments/bench/d_downstream.py --preds <preds> --out <out> --ablation single_vs_account` | D | `d_risk_action.run_ablation("single_vs_account", ...)` · 분모 = 계정 위험 > 0 인 사용자 (`n_zero_excluded` 따로) |
| ③ | **명시 단서 제거 전후 위험** — explicit 스팬을 입력에서 빼면 위험도가 얼마나 낮아지는가 | dev (개발 확인) / test (10/29) | `summary.{with_geo,spans_only}` 의 `before_mean` · `after_mean`(제거 전후 위험) · `reduction_pct`(사용자별 감소율 평균 · 중앙값) · `pooled_reduction_pct` | `python experiments/bench/d_downstream.py --preds <preds> --out <out> --ablation explicit_removed` | D | `d_risk_action.run_ablation("explicit_removed", ...)` · 탐지 F1 은 재지 않는다(스팬을 빼고 위험만 다시 계산) |
| ④ | **2단 규칙 경로 vs 모델 경로** — QLoRA 어댑터와 규칙 폴백의 판정 일치율 · 속도 차이 | dev (개발 확인) / test (10/29) | `stage2_compare.verdict_agreement`(두 경로끼리 verdict 일치율 · 분모 = 두 실행에 모두 있는 사용자 × 속성 7 · `per_attr_agreement`) · `stage2.parse_failure_rate` · `stage2.fallback_rate` · `stage2.seconds_per_user` | 두 번 돌리고 **출력 폴더를 다르게** 준다:<br>`python experiments/bench/d_downstream.py --preds <preds> --out <out>/rules --stage2-mode rules`<br>`python experiments/bench/d_downstream.py --preds <preds> --out <out>/model --stage2-mode model --compare-stage2 <out>/rules` | D | `d_stage2.compare_stage2` — 정답 적중률이 아니라 **두 경로끼리의 일치율**이다. 같은 파일을 가리키면 **측정 전에**(아무것도 쓰기 전에) 종료 코드 1 로 멈춘다 |

### 보조 지표 — 기존 실험 수치와 다르다

`risk_action` 이 내는 두 숫자는 README D13 의 기존 지표를 **재현한 값이 아니다**. 이름을 섞어 쓰지 않는다.

| 산출 키 | 무엇인가 | 섞으면 안 되는 기존 지표 |
|---|---|---|
| `risk.vs_gold.pred_vs_gold_risk_spearman` | 사용자별 **예측 스팬 위험 vs 골드 스팬 위험**의 Spearman ρ — 1단 예측이 위험 순위를 골드만큼 매기는지 | exp11 ρ = 0.813 (**위험 vs LLM 추론 성공** · README G1 「위험도 상관」) |
| `action.full_reduction_pct` · `action.app_target_reduction_pct` | **예측 스팬 · 앱 조건 생성(`infer._app_conditions`)** 기준 조치 3단계 감소율 | exp10 (**골드 스팬 · `clues.build_conditions`** · 본 표본 중앙값 −58.6%) |

기존 수치는 `--final` 에서만 그 실험 코드로 다시 낸다 (아래 「최종 측정 회귀」).

### 최종 측정 회귀 (`--final` 전용)

`--final` 은 test 글을 하위 단계까지 허용하고 아래 명령을 차례로 돌려 `metrics_downstream.json` 의 `regressions` 에 **명령 · 종료 코드 · 산출 파일 SHA-256** 을 남긴다. 하나라도 실패하면 종료 코드 1.

| 회귀 | 명령 (코드: `d_stage2.exp09_commands` · `d_risk_action.regression_commands`) | 비고 |
|---|---|---|
| exp09 외부 LLM 일치율 (v2) | **`d_downstream.py --final` 에서만 실행** (`d_stage2.py` 단독 CLI 의 `--final` 은 test 허용만 하고 exp09 를 돌리지 않는다)<br>`run_config.py --config v2 --adapter <2단과 같은 어댑터>` → `score.py --qwen-file qwen_cfg_v2.jsonl --out metrics_cfg_v2.json` | 로컬 Qwen 생성(GPU) · 외부 API 는 부르지 않는다(외부 판정은 저장본). 산출 3종(`data/qwen_cfg_v2.jsonl` · `data/qwen_cfg_v2_meta.json` · `results/metrics_cfg_v2.json`)은 실험 폴더 고정 경로이고 meta · metrics 는 **git 추적 파일(DEC-012 근거)** 이라 **절대 덮어쓰지 않는다**:<br>· meta + metrics 가 있고 meta 의 `adapter_sha256` · `inputs_sha256` · `external_sha256` 이 이번 어댑터 · 지금의 `data/inputs.jsonl` · `data/external.jsonl` SHA 와 모두 같으면 → 실행 없이 `existing_verified` + 세 파일 해시 (동결 구성과 같은 어댑터 · 입력 · 외부 판정으로 잰 저장 결과 재사용)<br>· 하나라도 있는데 어댑터 · 입력 · 외부 판정이 다르거나 확인할 수 없으면(입력 · 외부 판정 파일은 .gitignore 라 없는 PC 가 있다) → 실행 없이 `failed` — 새로 재려면 사람이 세 파일을 옮기고 다시 실행<br>· 셋 다 없을 때만 명령을 돌린다 |
| exp10 조치 재현 | `build_inputs.py --out <out>/regressions/exp10` | 골드 스팬 · `clues.build_conditions` · 모델 호출 없음. 필수 산출: `data/inputs_sample.jsonl` · `data/inputs_full.jsonl` · `results/preview.json` |
| exp11 위험 vs 추론 성공 | `score.py --scored results/teacher_all_scored.csv --windows-out … --metrics-out …` → `sensitivity.py --results <out>/regressions/exp11` | **저장된 교사 판정**을 재채점만 한다. `run_teacher.py`(외부 LLM 호출)는 넣지 않는다. 결과는 실행 폴더에만 쓴다(실험 폴더를 덮지 않는다). 필수 산출: `teacher_window_scores.csv` · `teacher_metrics.json` · `sensitivity_{v1,v1_rules}_{scored.csv,window_scores.csv,metrics.json}` · `sensitivity_person_block_permutation.json` |

---

## 하지 않는 것

| 항목 | 이유 |
|---|---|
| triage 절감 vs 놓침 비율 ablation | README G1 표 「Triage 토큰 70%+ 절감 [도전] — **미달** −51.9% (exp13)」 = exp13 anchor 정책의 **2단 입력 토큰 절감 51.9%** (원문 토큰 기준 78.5% 는 참고 · `experiments/exp13-triage/README.md`). 한계로 기록 · 동결 전에 새 구현 불가 |
| 2단 v1 vs v2 ablation | DEC-012 v2 채택 완료(10/12) · 비교는 exp22b 결과로 대신 |
| 어댑터 없는 폴백 vs 어댑터 있는 모델 비교 | 체크포인트가 없는 PC 는 규칙 경로로 자동 폴백 · 동일 구성으로 재현하기 어렵다 |
| CPU 가속(int8) ablation | exp24 미채택(10/13) · 스팬 일치 0.064 로 출력이 무너졌다 |
| test 를 개발용으로 돌리는 비교 | **test 는 10/29 한 번만** — 고르는 데 다시 쓰지 않는다 |

---

## 명령 한 줄 예시 (10/29 최종 측정)

```bash
export PYTHONIOENCODING=utf-8 PYTHONPATH=src

# dev 예측 파일로 하류 전체 확인 (개발 동결 전) — 입력은 exp24 의 1단 v2 dev 예측 (2,281편 · #350)
python experiments/bench/d_downstream.py \
  --preds experiments/exp24-cpu-accel/results/preds_dev_fp32.jsonl \
  --out results/bench/downstream_dev \
  --stage2-mode rules \
  --ablation single_vs_account explicit_removed

# 10/29 최종 측정 — test 글 포함 · --final 필수
python experiments/bench/d_downstream.py \
  --preds <test_preds>.jsonl \
  --out results/bench/downstream_final \
  --stage2-mode model \
  --ablation single_vs_account explicit_removed \
  --final

# ④ 의 다른 쪽 — 출력 폴더를 다르게 주고 위 실행과 비교
python experiments/bench/d_downstream.py \
  --preds <test_preds>.jsonl \
  --out results/bench/downstream_final_rules \
  --stage2-mode rules \
  --compare-stage2 results/bench/downstream_final \
  --final
```

> `--final` 없이 test 글이 섞이면 **오류로 멈춘다** (10/29 이전 보호). 단계마다 `status`(ok · skipped · failed · existing_verified)가 붙고, failed 가 하나라도 있으면(ablation · 회귀 안쪽 포함) 종료 코드 1 이다. skipped 는 그 단계 모듈 파일 자체가 없을 때만이다.
>
> 회귀 명령은 종료 코드 0 이어도 위 필수 산출 파일이 없거나 JSON · JSONL · CSV 로 읽히지 않으면 `failed` 다.
>
> 어댑터는 한 번만 해석한다(`--adapter` > `STAGE2_ADAPTER_DIR` > 앱 기본 exp08 `results/adapter_v2`). model 모드 2단과 exp09 가 같은 경로를 쓰고, 지문에 `stage2_adapter` · `stage2_adapter_sha256` 을 남긴다(rules 모드는 null · exp09 쪽 어댑터는 `regressions.exp09.adapter` 에 남는다).
>
> ⚠️ 두 번째 `--final` 실행도 회귀(exp09 · exp10 · exp11)를 다시 돈다. exp09 는 첫 실행 산출물이 같은 어댑터면 `existing_verified` 로 기록된다.
