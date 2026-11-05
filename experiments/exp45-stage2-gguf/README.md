# exp-045: 2단 v2 를 llama.cpp GGUF 로 — 판정 회귀 · 종단 시간

> **제출 이후 후보.** 11/1 동결 · 11/2 측정 · 제출 수치는 NF4 경로(`qwen3-4b-qlora-v2`) 그대로다. 이 실험은 그 수치를 바꾸지 않는다.
>
> **11/4 밤 갱신 — 앱 GGUF 는 「베이스 Q8_0 + v2 LoRA f32 분리」(`qwen3-4b-qlora-v2-gguf-q8-lora`)로 바뀌었다.** 결과 1~3 의 Q5_K_M merge 판(`…-gguf-q5km`)은 115계정 797/805 로 기각했고, 원인과 해결은 [결과 4](#결과-4--원인과-해결q8--lora-분리)에 있다.

## 무엇을 왜 재는가

2단(Qwen3-4B NF4 + v2 어댑터 `c045d353…`)은 RTX 3060 에서 약 12 tok/s 라 계정 하나에 약 55초가 걸린다(freeze-W11 · 점검 중앙 68.7초).
같은 판정을 더 빨리 낼 수 있는지 본다. 질문은 둘이다.

1. **판정이 같은가** — exp09 의 2단 v2 실행(105명 · 239편 · 735칸)을 GGUF 엔진으로 다시 돌려 NF4 저장 결과와 칸마다 비교한다
2. **사용자가 기다리는 시간이 얼마나 주나** — 「빠른 결과 먼저」(progressive) 분석기로 freeze-W11 의 11계정을 점검해 빠른 결과 · 정밀 판정 도착 시각을 잰다

## 가중치 — 왜 「dequant NF4 → merge」인가 (결과 1~3 의 판 · 지금은 결과 4 의 LoRA 분리)

| 후보 | 결과 (exp22b 30계정 · 저장소 밖 사전 실측) |
|---|---|
| 원본 bf16 베이스 + 어댑터 merge → Q4/Q5/Q8 | 판정 칸 204~206/210 · M1 0.97~0.98 — **기각** |
| **NF4 베이스를 bf16 으로 dequant + 어댑터 merge → Q5_K_M** | 판정 칸 **210/210** · M1 1.000 · M3 .998 · M5 .995 (NF4 와 같다) · 약 59 tok/s |
| 같은 방식 Q8_0 · Q4_K_M | 209/210 · 더 느리거나(Q8) 칸이 다르다 |

QLoRA 어댑터는 NF4 를 푼 가중치 위에서 학습됐다. 원본 bf16 에 merge 하면 어댑터가 본 적 없는 베이스가 된다 — 그래서 앱(`Stage2Model`)이 실제로 계산하는 값(NF4 dequant + LoRA)을 bf16 으로 만든 뒤 양자화한다.

이 「dequant 베이스」 판단은 결과 4 에서도 그대로다. 바뀐 것은 **merge 를 하지 않는다**는 것 하나다 — dequant 베이스만 Q8_0 으로 양자화하고 v2 어댑터는 LoRA GGUF(f32)로 따로 두어 llama-server `--lora` 로 실행 때 더한다(`dq_base.py` → `build_gguf_lora.cmd`).

## 설정

| 항목 | 값 |
|---|---|
| 측정일 | 2026-11-04 |
| 코드 | 브랜치 `PM/app/progressive-stage2` · `Stage2GGUF`(src/kopl/c4_stage2/infer.py) |
| GGUF (결과 1~3 · 기각) | `stage2v2-dq-Q5_K_M.gguf` 2,889,513,408 B · SHA-256 `7eb87c50b988d0d735e9d74b8af4c1c23e100a7a2c3f68120e991c489c3eb5b7` (저장소 밖) |
| GGUF (결과 4 · 앱) | 베이스 `stage2v2-dqonly-Q8_0.gguf` 4,280,404,928 B · SHA-256 `f4982df0149f89e7300314d0f1a5d20dc34b6b5d7d0c6e03a754c30431a575b0` (infer.py `GGUF_SHA256`) + LoRA `stage2v2-lora-f32.gguf` 47,205,760 B · `ae0104d45f7359af3484ff0585840ffd1432951519ff2f0fc19de8b2d07eb74d` (`GGUF_LORA_SHA256`) · 둘 다 저장소 밖 |
| 중간 산출물 | dequant-merge bf16 GGUF `30cc2f84e2e44b5f…` (8.05 GB · 저장소 밖) |
| llama.cpp | **b12090** — `llama-b12090-bin-win-cuda-13.4-x64.zip` SHA-256 `27d678fa55396cd90c7a4e74b24342593c73a3aadd33576435db092ca6fdcd7b` · `cudart-llama-bin-win-cuda-13.4-x64.zip` `738f8c251ac22b70…` · `llama-server.exe` `7026e5e3e5cf3d92…` · convert 는 같은 태그 소스 `convert_hf_to_gguf.py` (gguf 0.19.0) |
| merge 환경 | torch 2.12.1+cu130 · transformers 5.12.1 · peft 0.21.0 · bitsandbytes 0.50.2 |
| 디코딩 | `/completion` · 프롬프트는 `infer.chat_prompt`(Qwen3 템플릿 · thinking 끔 · `apply_chat_template` 과 글자까지 같음 — test_gguf) · temperature 0 · top_k 1 · seed 0 · `n_predict = output_budget(entries)` · `-c 4096 -np 1 -ngl 99` |
| 하드웨어 | RTX 3060 8GB · AMD 12스레드 · Windows 10 |
| NF4 비교 기준 | exp09 `qwen_cfg_v2.jsonl` — 어댑터 `c045d353…` · 10/27 재측정(`qwen_cfg_v2_meta.json` · GPU 서버 `/srv/kisia`) · 파일 SHA-256 `92efe374b4e7c201…`. **NF4 는 다시 돌리지 않았다** |

## 실행

```bash
# 0) 가중치 만들기 (한 번 · GPU) — 산출물은 저장소에 넣지 않는다 (.gitignore *.safetensors · *.gguf)
#    지금 앱의 판(결과 4): dequant 베이스(merge 없음) → Q8_0 · v2 어댑터 → LoRA GGUF f32
python experiments/exp45-stage2-gguf/dq_base.py --out <dq 폴더>
experiments\exp45-stage2-gguf\build_gguf_lora.cmd <dq 폴더> <v2 어댑터> <출력 폴더>   # LLAMA_SRC · LLAMA_BIN · CONVERT_PY · 끝에 SHA-256 두 개
#    옛 Q5_K_M merge 판(결과 1~3 재현용 · 기각)
python experiments/exp45-stage2-gguf/merge_dq.py --adapter <v2 어댑터> --out <merged 폴더>
experiments\exp45-stage2-gguf\build_gguf.cmd <merged 폴더> <출력 폴더>

# 1) exp09 회귀 — 엔진만 GGUF, 입력 · 상한은 run_config.py --config v2 그대로
#    결과 1~3(Q5 merge 한 파일)은 Q8 + LoRA 코드 전 커밋 e61c197 에서만 재현된다 — 지금 Stage2GGUF 는 두 파일 · Q8 해시를 요구한다
#    지금 코드로 돌리면: STAGE2_GGUF=<...dqonly-Q8_0.gguf> STAGE2_GGUF_LORA=<...lora-f32.gguf> · 출력 파일 이름을 바꿔 Q5 결과를 덮지 않는다
export PYTHONIOENCODING=utf-8 PYTHONPATH="src;." STAGE2_GGUF=<...Q5_K_M.gguf> LLAMA_SERVER=<...llama-server.exe>   # e61c197 기준
python experiments/exp45-stage2-gguf/run_exp09.py                 # → exp09 data/qwen_cfg_v2_gguf.jsonl (커밋 안 함)
python experiments/exp45-stage2-gguf/compare.py                   # → results/compare_exp09.json
python experiments/exp09-external-agreement/score.py --qwen-file qwen_cfg_v2_gguf.jsonl --out metrics_cfg_v2_gguf.json   # → results/metrics_exp09_gguf.json 로 옮김

# 2) 종단 — Veilo(3100 · 별도 DB 를 seed_sns.py --reset 으로) + 분석기(8100) 를 띄운 뒤
python experiments/exp45-stage2-gguf/run_e2e.py --base http://127.0.0.1:8100 --label gguf --out results/e2e_gguf.json
```

분석기 환경: `ENGINE_MODE=real STAGE2_MODE=auto C1_CHECKPOINT_DIR=<1단 v2> SNS_BASE_URL=http://localhost:3100` + GGUF 면 `STAGE2_ENGINE=gguf STAGE2_GGUF LLAMA_SERVER`(결과 4 부터 `STAGE2_GGUF_LORA` 도) · NF4 면 `STAGE2_ADAPTER_DIR`.

## 결과 1 — exp09 회귀 (105명 · 735칸)

| | NF4 (저장) | GGUF Q5_K_M |
|---|---|---|
| 파싱 실패 · 잘림 · 앱 폴백(`validate_findings` None) | 0 · 0 · 0 | 0 · 0 · 0 |
| 판정 칸 일치 (원시 · 앱 검증 후) | — | **735/735 · 735/735** |
| 근거 집합 일치 (앱 검증 후) | — | 735/735 |
| 원시 출력 글자까지 같음 | — | 101/105 |
| exp09 일치율 (vs 외부 LLM) · 비기권 · κ | 0.8531 · 0.4706 · 0.6719 | **0.8531 · 0.4706 · 0.6719** |
| Qwen vs 규칙 | 0.9973 | 0.9973 |
| 1명 평균 생성 시간 | 23.4 s (10/27 GPU 서버 `/srv/kisia` · 다른 장치라 비교 안 함) | 5.17 s (RTX 3060) |

- score.py 지표는 `evidence_jaccard` 평균 · 시간 칸만 다르다(아래 A25). 저장된 `metrics_cfg_v2.json` 은 NF4 파일을 다시 채점해 같은 값이 나오는 것을 확인했다
- **판정이 다른 칸은 없다.** 원시 출력이 다른 4명:

| 인물 · 속성 | NF4 | GGUF | 앱에 보이는 차이 |
|---|---|---|---|
| B15 · family | narrowed 0.7 | narrowed **0.6** | 신뢰도만 (근거 4개 같음) |
| E12 · family | narrowed 0.7 | narrowed **0.6** | 신뢰도만 |
| E14 · family | narrowed 0.7 | narrowed **0.6** | 신뢰도만 |
| A25 · location | specified · 근거 `b15_s01`(「동네 시장」 본인) | specified · 근거 + `b10_s01`(「서울」 **타인**) | 없음 — 타인 스팬은 `validate_findings` 가 지운다 |

## 결과 2 — 종단 (freeze-W11 11계정 · 빠른 결과 먼저)

분석기(`/scan/{user_ref}?progressive=true`) · Veilo 3100(별도 DB · `seed_sns.py --reset` · 115명 3,092편) · 1단 v2(`C1_CHECKPOINT_DIR`) · 계정마다 1회(첫 계정 워밍업 1회 뒤) · 앞 계정의 정밀 판정이 끝난 뒤 다음 계정. 초 단위 · 시각은 POST 시작부터.

| 계정 | 글 | 빠른 결과 NF4 · GGUF | 정밀 판정 도착 NF4 | GGUF | 판정 칸 NF4 = GGUF |
|---|---:|---|---:|---:|---|
| u_8c53e7b89615 (메인) | 30 | 8.01 · 8.05 | 63.25 | 20.42 | 7/7 |
| u_00ceeab4df70 (예비) | 30 | 8.80 · 8.89 | 63.38 | 21.36 | 7/7 |
| u_40ef42660c42 | 18 | 5.41 · 5.42 | 55.38 | 16.55 | 7/7 |
| u_5985f6f8353e | 30 | 26.61 · 26.73 | 81.04 | 39.21 | 7/7 |
| u_231b2f8e3757 | 30 | 8.47 · 8.48 | 63.25 | 21.00 | 7/7 |
| u_72ce87717c0c | 30 | 8.37 · 8.35 | 58.82 | 19.95 | 7/7 |
| u_bf3d2191e215 | 20 | 5.83 · 5.84 | 53.46 | 16.44 | 7/7 |
| u_084835c6a489 | 30 | 21.64 · 21.45 | 76.69 | 33.80 | 7/7 |
| u_0dfab5acbae0 | 20 | 5.45 · 5.31 | 53.66 | 15.92 | 7/7 |
| u_99e3940e063f | 30 | 9.17 · 9.05 | 64.29 | 21.69 | 7/7 |
| u_c9c1dd0d52c9 | 30 | 7.28 · 7.22 | 62.13 | 19.63 | **6/7** |
| **중앙값** | | 8.37 · 8.35 | **63.25** | **20.42** | 76/77 |

- 정밀 판정 몫(도착 − 빠른 결과) 중앙값: NF4 **54.6초** → GGUF **12.4초**. 가장 긴 계정 81.0 → 39.2초(1단 CPU 가 긴 계정)
- 빠른 결과 · 위험도 · 추천은 두 엔진에서 같다(11/11 · 위험도는 freeze-W11 표와 같음). 근거 목록은 77/77 같다
- 다른 1칸 — u_c9c1dd0d52c9(C20) commute: NF4 `weak_signal`(= 규칙) · GGUF `narrowed`. 근거는 둘 다 C20_b03 한 편의 「지하철로」 · 「출근한」 · 「퇴근길」(사진 캡션) — 모두 본인 · inferential. v2 판정 기준(inferential 만 · 글 1편 → weak_signal)으로는 **GGUF 가 틀렸다**. 사전 실측(앱 11계정 76/77)과 같은 칸
- 기동: 분석기 `/api/engine-mode` 응답까지 GGUF 18.1초(1단 적재 + GGUF 해시 + llama-server 적재 5초) · NF4 21.1초
- 외부 연결: 실행 중 llama-server 프로세스의 TCP 를 20초간 0.2초마다 모았다 — `127.0.0.1:8092` 대기와 분석기(127.0.0.1)와의 연결뿐. 분석기 프로세스를 강제 종료(`Stop-Process -Force`)하자 llama-server 도 3초 안에 꺼졌다(Job)
- freeze-W11 의 「모델 68.7초」는 한 번에 응답하는 점검(2회차)이라 이 표의 「정밀 판정 도착」과 재는 구간이 조금 다르다 — 비교는 같은 하네스로 잰 NF4 열과 한다

## 결과 3 — 115계정 전수 (Veilo 3100 전체 · 805칸)

결과 2 와 같은 하네스(progressive 점검 → 정밀 판정 폴링 · 계정마다 1회 · 첫 계정 워밍업 1회)로 Veilo DB 의 계정 전체를 돌렸다.
엔진별로 분석기를 따로 띄워 GGUF(15:48~16:36) → NF4(16:36~18:52) 순서 · 같은 Veilo DB(`seed_sns.py --reset` · 115명 3,092편).

```bash
python experiments/exp45-stage2-gguf/run_validate115.py --base http://127.0.0.1:8100 --sns-db <Veilo DB> --label gguf --out <저장소 밖>/validate115_gguf.jsonl
python experiments/exp45-stage2-gguf/run_validate115.py --base http://127.0.0.1:8100 --sns-db <Veilo DB> --label nf4  --out <저장소 밖>/validate115_nf4.jsonl
python experiments/exp45-stage2-gguf/compare115.py --nf4 <...nf4.jsonl> --gguf <...gguf.jsonl> --sns-db <Veilo DB> --out experiments/exp45-stage2-gguf/results/validate115.json
```

| | NF4 | GGUF Q5_K_M |
|---|---|---|
| 정밀 판정 받음(done) · 폴백 · 실패 | 115 · 0 · 0 | 115 · 0 · 0 |
| 빠른 결과 중앙값 | 9.42 s | 8.77 s |
| **정밀 판정 도착 중앙값** · 최대 | **67.22 s** · 129.7 s | **21.10 s** · 82.8 s |
| 정밀 판정 몫(도착 − 빠른 결과) 중앙값 | 57.06 s | 12.14 s |
| 모델 판정 ≠ 규칙 판정(805칸 중) | 15 | 21 |

| 비교 (115계정 · 805칸) | 일치 |
|---|---|
| **판정 칸(verdict)** | **797/805** (99.0%) |
| 근거 span 집합 | 796/805 |
| 신뢰도 · 범위(granularity) | 774/805 · 805/805 |
| 칸 전체(판정 · 근거 · 신뢰도 · 범위 · cross_post) | 767/805 |
| 위험도 · 추천(해시) · 빠른 결과 판정 | 115/115 · 115/115 · 115/115 |

판정이 다른 8칸 — 「규칙」은 같은 v2 판정 기준(본인 스팬 · explicit → specified · implicit → narrowed · inferential 글 2편 이상 → narrowed · 1편 → weak_signal)을 그대로 구현한 rules-v1 의 판정이다.

| 인물 · 속성 | 규칙 | NF4 | GGUF | 근거 | 기준상 맞는 쪽 |
|---|---|---|---|---|---|
| A04 · sex | weak_signal | weak_signal 0.4 | narrowed 0.7 | 같음(1개) | NF4 |
| A11 · age | specified | **abstain** (근거 없음) | specified 0.9 | GGUF 만 `A11_b03_s01` | **GGUF** |
| A13 · occupation | specified | specified 0.9 | narrowed 0.7 | 같음(3개) | NF4 |
| B04 · income | narrowed | narrowed 0.7 | weak_signal 0.4 | 같음(2개 · 글 1편) | NF4 |
| C02 · family | weak_signal | weak_signal 0.4 | narrowed 0.6 | 같음(1개) | NF4 |
| C20 · commute | weak_signal | weak_signal 0.4 | narrowed 0.6 | 같음(글 1편 3개) | NF4 (결과 2 와 같은 칸) |
| D11 · income | narrowed | narrowed 0.7 | weak_signal 0.4 | 같음(1개) | NF4 |
| D21 · sex | narrowed | narrowed 0.7 | **abstain** (근거 없음) | NF4 만 2개 | NF4 |

- 8칸 중 7칸은 GGUF 가 기준에서 벗어났다(NF4 = 규칙). 1칸(A11 age)은 NF4 가 근거를 놓쳐 기권했다
- 판정은 같고 근거만 다른 칸 7개 — 6개는 NF4 쪽 근거가 1개 더 많고(A23 age · A23 location · B03 location · D11 family · D14 location · S01b occupation), 1개는 GGUF 쪽(D10 occupation)
- 위험도 · 추천은 `infer.analyze` 가 판정과 무관하게 스팬으로 계산한다 — 두 실행의 1단 · 규칙 경로가 같았다는 확인이다(엔진 비교 아님)
- 「기준상 맞는 쪽」은 규칙 판정과 같은 쪽으로 정했다. 스팬 등급(level)을 칸마다 따로 열어 보지는 않았다 — 근거가 같고 판정만 다른 6칸은 같은 근거에서 기준이 한 답만 내므로 규칙과 같은 쪽이 맞다. 다만 모델 입력은 글 수 상한(cap)으로 줄인 것이고 규칙은 전체로 판정한다

## 결과 4 — 원인과 해결(Q8 + LoRA 분리)

결과 3 의 8칸이 왜 갈렸는지 가설을 하나씩 지우고, 원인을 없앤 판을 앱에 넣어 115계정을 다시 돌렸다. 요약 수치는 [results/diag_cause.json](results/diag_cause.json)(진단) · [results/validate115_q8lora.json](results/validate115_q8lora.json)(종단).

### 진단 — 입력 · 템플릿 · 디코딩 · 비결정성이 아니라 가중치

진단 하네스는 115계정의 2단 모델 입력(가명화 스팬 목록 · 출력 상한)을 앱 경로(Veilo DB 사본 → 1단 → `build_user_prompt(cap=True)`)로 **한 번 만들어 고정**하고, 엔진만 바꿔 같은 입력을 넣었다. 저장소 밖 진단 스크립트이고 결과 요약만 옮겼다.

| 가설 | 확인 | 결과 |
|---|---|---|
| 입력 · chat 템플릿이 다르다 | HF 토크나이저 `apply_chat_template` ↔ llama-server 토큰화(9계정) | 글자 · 토큰 id 9/9 같음 — **아니다** |
| 디코딩 설정 · 비결정성 | greedy(temperature 0 · top_k 1 · `/props` 기록) · 같은 입력 반복(11계정 · NF4 3회 · Q5 merge 2회) | 반복끼리 출력 토큰이 11/11 같다 — **아니다** |
| merge 뒤 재양자화가 어댑터 몫을 깎았다 | 어댑터 몫 ‖BA·α/r‖ / ‖W‖ · merge 판과 베이스만 양자화한 판의 차를 어댑터 방향에 사영(36 텐서 · `weight_retention.py`) | 어댑터 몫은 ‖W‖ 의 **0.79%**. merge 뒤 남은 몫 bf16 99.7% · Q8_0 99.4% · **Q5_K_M 81.3%** · 어댑터 대비 잡음 bf16 0.22 · Q8_0 0.98 · Q5_K_M 4.35 — **원인** |

### 사다리 — merge 를 안 하면 Q8_0 에서 NF4 와 같아진다

같은 고정 입력. 「merge」는 dequant 베이스 + 어댑터를 합친 뒤 양자화(결과 1~3 의 판), 「LoRA 분리」는 dequant 베이스만 양자화하고 어댑터는 LoRA GGUF(f32)로 `--lora` 실행.

| 판 | 11계정 출력이 NF4 와 토큰까지 같음¹ | 33계정 토큰까지 같음² | 115계정 판정 칸 = NF4 | 근거 = NF4 | 모델 ≠ 규칙 | 생성 중앙 · tok/s |
|---|---|---|---|---|---|---|
| merge · bf16 | 10/11 | — | — | — | — | — |
| LoRA 분리 · bf16 베이스 | **11/11** | — | — | — | — | — |
| merge · Q5_K_M (결과 1~3) | 0/7 | 20/33 | 797/805 | 796/805 | 21 | 12.25 s · 52.8 |
| LoRA 분리 · Q5_K_M 베이스 | 5/6 | — | — | — | — | — |
| merge · Q8_0 | 9/11 | 30/33 | 802/805 | 803/805 | 16 | 15.82 s · 40.6 |
| **LoRA 분리 · Q8_0 베이스 (앱)** | **11/11** | **32/33** | **804/805** | **804/805** | **14** | **17.47 s · 36.5** |
| NF4 (기준 · bitsandbytes) | — | — | — | — | 15 | 61.4 s³ |

1. Q5 merge 판이 NF4 와 판정이 달랐던 8계정 + 대조 3계정 — Q5 merge 판에 불리하게 고른 표본이다. Q5 두 줄은 기록된 계정만(7 · 6)
2. 위 11 + 대조 21 + B08. LoRA Q8 이 갈린 1계정(B08)은 그 자리에서 **NF4 의 두 후보 로짓 차가 0.0** 이다 — NF4 자신에게도 동전 던지기인 자리다. NF4 판정 토큰 로짓 차는 중앙 9.6 · 0.5 미만은 231자리 중 3
3. NF4 는 11계정 × 3회 고정 입력 생성 중앙(같은 PC)

- LoRA 분리는 merge 의 손실(재양자화가 어댑터 몫을 깎음)을 없앤다. 남는 오차는 베이스 Q8_0 양자화뿐이고, 어댑터는 학습 때처럼 「풀린 베이스 + f32 LoRA」로 더해진다
- 대가는 속도다 — Q5 merge 보다 생성이 약 1.4배 느리다(12.3 → 17.5 s). NF4(약 61 s)보다는 약 3.5배 빠르다
- Q5_K_M 베이스 + LoRA 는 6계정 중 1계정이 갈려 115 전수로 가지 않았다

### 앱 종단 115계정 — Q8 + LoRA 분리 (결과 3 과 같은 하네스)

11/4 23:01~11/5 00:02 · 분석기(`STAGE2_ENGINE=gguf` · `STAGE2_GGUF`=베이스 Q8_0 · `STAGE2_GGUF_LORA`=LoRA f32 · llama-server 127.0.0.1:8193) · Veilo 3100(결과 3 과 같은 DB 파일 · 그 뒤 수정 없음) · 첫 계정 워밍업 1회 뒤 계정마다 1회. **NF4 는 다시 돌리지 않고 결과 3 의 NF4 실행(11/4 16:36~18:52)과 비교했다.**

```bash
python experiments/exp45-stage2-gguf/run_validate115.py --base http://127.0.0.1:8100 --sns-db <Veilo DB> --label q8lora --out <저장소 밖>/validate115_q8lora.jsonl
python experiments/exp45-stage2-gguf/compare115.py --nf4 <...nf4.jsonl> --gguf <...q8lora.jsonl> --sns-db <Veilo DB> --out experiments/exp45-stage2-gguf/results/validate115_q8lora.json
```

| | NF4 (결과 3) | GGUF Q5 merge (결과 3 · 기각) | **GGUF Q8 + LoRA (앱)** |
|---|---|---|---|
| 정밀 판정 받음(done) · 폴백 · 실패 | 115 · 0 · 0 | 115 · 0 · 0 | **115 · 0 · 0** · `model_version` 전부 `qwen3-4b-qlora-v2-gguf-q8-lora` |
| 빠른 결과 중앙값 | 9.42 s | 8.77 s | 9.81 s |
| **정밀 판정 도착 중앙값** · 최대 | 67.22 s · 129.7 s | 21.10 s · 82.8 s | **27.11 s** · 87.8 s |
| 정밀 판정 몫(도착 − 빠른 결과) 중앙값 | 57.06 s | 12.14 s | **17.08 s** |
| 판정 칸 = NF4 (805칸) | — | 797 | **804** |
| 근거 span 집합 = NF4 | — | 796 | **804** |
| 신뢰도 · 범위 = NF4 | — | 774 · 805 | **803 · 805** |
| 칸 전체(판정 · 근거 · 신뢰도 · 범위 · cross_post) = NF4 | — | 767 | **802** |
| 위험도 · 추천(해시) · 빠른 결과 판정 = NF4 | — | 115 · 115 · 115 | 115 · 115 · 115 |
| 모델 판정 ≠ 규칙 판정 | 15 | 21 | **14** |

- **다른 1칸 — B08 commute**: 규칙 `weak_signal` · NF4 `narrowed` 0.6 · Q8+LoRA `weak_signal` 0.4 · 근거는 둘 다 같은 글 1편의 스팬 2개. v2 판정 기준(inferential 만 · 글 1편 → weak_signal)으로는 **Q8+LoRA 가 맞고 NF4 가 벗어났다**. 고정 입력 하네스에서 NF4 의 그 자리 로짓 차가 0.0 이었던 칸이다
- 판정이 같고 근거만 다른 1칸 — A15 occupation(narrowed): NF4 쪽 근거가 1개 더 많다(`A15_b15_s03`)
- 결과 3 에서 Q5 merge 가 기준을 벗어난 7칸(A04 sex · A13 occupation · B04 income · C02 family · C20 commute · D11 income · D21 sex)과 NF4 가 근거를 놓친 A11 age 는 **모두 NF4 와 같아졌다**(A11 은 NF4 와 같게 abstain)
- 고정 입력 하네스(804/805 · 다른 칸 B08 commute)와 앱 종단이 **같은 칸 · 같은 수**로 나왔다 — 앱 경로(1단 · 가명화 · 상한 · 검증)가 진단과 같은 입력을 만든다는 확인이기도 하다
- 시간은 엔진 하나씩 따로 띄워 잰 1회 값이다. 정밀 판정 몫 중앙 17.1 s 는 고정 입력 생성 중앙 17.5 s 와 맞는다

## 해석

> 지금 앱의 결론은 아래 **마지막 항목(결과 4)** 이다. 앞의 네 항목은 기각한 Q5 merge 판(결과 1~3)의 해석으로 남겨 둔다.

- (결과 1~3 · Q5 merge · 기각) 판정 회귀는 없다 — 735칸 · exp09 지표가 NF4 와 같다. 다른 것은 신뢰도 0.1 차이 3칸과 검증에서 지워지는 근거 1개다
- (결과 2 · Q5 merge · 기각) 앱 11계정에서는 u_c9c1dd0d52c9 의 commute 1칸이 다르다(사전 실측과 같은 칸). 규칙 · NF4 와 다른 쪽은 GGUF 이고, 판정 기준상 GGUF 가 틀렸다
- (결과 2 · Q5 merge · 기각) 사용자가 정밀 판정을 기다리는 시간은 계정당 약 1분 → 약 20초(중앙 63.3 → 20.4초)로 준다. Q8 + LoRA 는 115계정 중앙 67.2 → 27.1초(결과 4). 빠른 결과(약 8초)는 1단 CPU 몫이라 엔진과 무관하다
- (11/4 결과 3 시점) **115계정 전수(결과 3)에서는 판정 칸 797/805 — 같지 않다.** 다른 8칸 중 7칸에서 GGUF 가 v2 기준(= 규칙)을 벗어났고, 모델 ≠ 규칙 칸이 NF4 15 → GGUF 21 로 는다. 「NF4 와 같은 판정」을 근거로 GGUF 를 기본값으로 올릴 수는 없다. 올린다면 정밀 판정 대기 67 → 21초(중앙)와 이 7칸의 기준 이탈을 맞바꾸는 결정이다(위험도 · 추천 · 빠른 결과는 영향 없음)
- **결과 4 이후: 원인은 merge 뒤 재양자화였고, 베이스 Q8_0 + LoRA f32 분리로 115계정 판정 804/805 · 근거 804/805 가 됐다.** 남은 1칸(B08 commute)은 NF4 자신이 동전 던지기인 자리이고, 기준상 GGUF 쪽이 맞다. 모델 ≠ 규칙 칸도 NF4 15 → 14 로 늘지 않는다. 대가는 Q5 merge 보다 정밀 판정 몫이 약 5초 늘어난 것이다(중앙 12.1 → 17.1 s · NF4 57.1 s)

## 한계

- NF4 exp09 는 10/27 GPU 서버 실행을 비교 기준으로 썼다. 판정은 장치와 무관한 greedy 이지만 NF4 커널(bitsandbytes)과 llama.cpp 커널은 수치가 다르다 — 이 735칸 · 11계정 · exp22b 30계정 밖의 입력에서 판정이 갈릴 수 있다(앱 11계정 중 1칸이 그 예)
- 판정 일치는 코퍼스 v0 가상 인물에서만 쟀다. 실제 글 분포는 보지 않았다
- 종단 시간은 PC 한 대 · 계정당 1회(워밍업 1회 뒤)다
- llama.cpp 바이너리 · CUDA 런타임은 저장소 밖이다. 다른 PC 는 같은 b12090 zip 을 받아 해시를 확인해야 한다
- 결과 4 의 진단 하네스(고정 입력 생성 · 로짓 비교)는 저장소 밖 스크립트다. 저장소에는 가중치를 만드는 절차(`dq_base.py` · `build_gguf_lora.cmd`)와 원인 분석(`weight_retention.py`)만 옮겼다
- 베이스 Q8_0 은 한 번만 만들었다(같은 절차로 다시 만들어 해시가 같은지 보지 않았다). LoRA f32 는 11/4 다시 변환해 해시까지 같았다
- 결과 4 의 NF4 비교 기준은 결과 3 의 NF4 실행 1회다 — NF4 를 이번에 다시 돌리지 않았다
