# exp-044: 2단 v2 를 llama.cpp GGUF 로 — 판정 회귀 · 종단 시간

> **제출 이후 후보.** 11/1 동결 · 11/2 측정 · 제출 수치는 NF4 경로(`qwen3-4b-qlora-v2`) 그대로다. 이 실험은 그 수치를 바꾸지 않는다.

## 무엇을 왜 재는가

2단(Qwen3-4B NF4 + v2 어댑터 `c045d353…`)은 RTX 3060 에서 약 12 tok/s 라 계정 하나에 약 55초가 걸린다(freeze-W11 · 점검 중앙 68.7초).
같은 판정을 더 빨리 낼 수 있는지 본다. 질문은 둘이다.

1. **판정이 같은가** — exp09 의 2단 v2 실행(105명 · 239편 · 735칸)을 GGUF 엔진으로 다시 돌려 NF4 저장 결과와 칸마다 비교한다
2. **사용자가 기다리는 시간이 얼마나 주나** — 「빠른 결과 먼저」(progressive) 분석기로 freeze-W11 의 11계정을 점검해 빠른 결과 · 정밀 판정 도착 시각을 잰다

## 가중치 — 왜 「dequant NF4 → merge」인가

| 후보 | 결과 (exp22b 30계정 · 저장소 밖 사전 실측) |
|---|---|
| 원본 bf16 베이스 + 어댑터 merge → Q4/Q5/Q8 | 판정 칸 204~206/210 · M1 0.97~0.98 — **기각** |
| **NF4 베이스를 bf16 으로 dequant + 어댑터 merge → Q5_K_M** | 판정 칸 **210/210** · M1 1.000 · M3 .998 · M5 .995 (NF4 와 같다) · 약 59 tok/s |
| 같은 방식 Q8_0 · Q4_K_M | 209/210 · 더 느리거나(Q8) 칸이 다르다 |

QLoRA 어댑터는 NF4 를 푼 가중치 위에서 학습됐다. 원본 bf16 에 merge 하면 어댑터가 본 적 없는 베이스가 된다 — 그래서 앱(`Stage2Model`)이 실제로 계산하는 값(NF4 dequant + LoRA)을 bf16 으로 만든 뒤 양자화한다.

## 설정

| 항목 | 값 |
|---|---|
| 측정일 | 2026-11-04 |
| 코드 | 브랜치 `PM/app/progressive-stage2` · `Stage2GGUF`(src/kopl/c4_stage2/infer.py) |
| GGUF | `stage2v2-dq-Q5_K_M.gguf` 2,889,513,408 B · SHA-256 `7eb87c50b988d0d735e9d74b8af4c1c23e100a7a2c3f68120e991c489c3eb5b7` (infer.py `GGUF_SHA256` · 저장소 밖) |
| 중간 산출물 | dequant-merge bf16 GGUF `30cc2f84e2e44b5f…` (8.05 GB · 저장소 밖) |
| llama.cpp | **b12090** — `llama-b12090-bin-win-cuda-13.4-x64.zip` SHA-256 `27d678fa55396cd90c7a4e74b24342593c73a3aadd33576435db092ca6fdcd7b` · `cudart-llama-bin-win-cuda-13.4-x64.zip` `738f8c251ac22b70…` · `llama-server.exe` `7026e5e3e5cf3d92…` · convert 는 같은 태그 소스 `convert_hf_to_gguf.py` (gguf 0.19.0) |
| merge 환경 | torch 2.12.1+cu130 · transformers 5.12.1 · peft 0.21.0 · bitsandbytes 0.50.2 |
| 디코딩 | `/completion` · 프롬프트는 `infer.chat_prompt`(Qwen3 템플릿 · thinking 끔 · `apply_chat_template` 과 글자까지 같음 — test_gguf) · temperature 0 · top_k 1 · seed 0 · `n_predict = output_budget(entries)` · `-c 4096 -np 1 -ngl 99` |
| 하드웨어 | RTX 3060 8GB · AMD 12스레드 · Windows 10 |
| NF4 비교 기준 | exp09 `qwen_cfg_v2.jsonl` — 어댑터 `c045d353…` · 10/27 재측정(`qwen_cfg_v2_meta.json` · GPU 서버 `/srv/kisia`) · 파일 SHA-256 `92efe374b4e7c201…`. **NF4 는 다시 돌리지 않았다** |

## 실행

```bash
# 0) 가중치 만들기 (한 번 · GPU) — 산출물은 저장소에 넣지 않는다 (.gitignore *.safetensors · *.gguf)
python experiments/exp44-stage2-gguf/merge_dq.py --adapter <v2 어댑터> --out <merged 폴더>
experiments\exp44-stage2-gguf\build_gguf.cmd <merged 폴더> <출력 폴더>      # LLAMA_SRC · LLAMA_BIN · CONVERT_PY 지정 · 끝에 SHA-256

# 1) exp09 회귀 — 엔진만 GGUF, 입력 · 상한은 run_config.py --config v2 그대로
export PYTHONIOENCODING=utf-8 PYTHONPATH="src;." STAGE2_GGUF=<...Q5_K_M.gguf> LLAMA_SERVER=<...llama-server.exe>
python experiments/exp44-stage2-gguf/run_exp09.py                 # → exp09 data/qwen_cfg_v2_gguf.jsonl (커밋 안 함)
python experiments/exp44-stage2-gguf/compare.py                   # → results/compare_exp09.json
python experiments/exp09-external-agreement/score.py --qwen-file qwen_cfg_v2_gguf.jsonl --out metrics_cfg_v2_gguf.json   # → results/metrics_exp09_gguf.json 로 옮김

# 2) 종단 — Veilo(3100 · 별도 DB 를 seed_sns.py --reset 으로) + 분석기(8100) 를 띄운 뒤
python experiments/exp44-stage2-gguf/run_e2e.py --base http://127.0.0.1:8100 --label gguf --out results/e2e_gguf.json
```

분석기 환경: `ENGINE_MODE=real STAGE2_MODE=auto C1_CHECKPOINT_DIR=<1단 v2> SNS_BASE_URL=http://localhost:3100` + GGUF 면 `STAGE2_ENGINE=gguf STAGE2_GGUF LLAMA_SERVER` · NF4 면 `STAGE2_ADAPTER_DIR`.

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

## 해석

- 판정 회귀는 없다 — 735칸 · exp09 지표가 NF4 와 같다. 다른 것은 신뢰도 0.1 차이 3칸과 검증에서 지워지는 근거 1개다
- 앱 11계정에서는 u_c9c1dd0d52c9 의 commute 1칸이 다르다(사전 실측과 같은 칸). 규칙 · NF4 와 다른 쪽은 GGUF 이고, 판정 기준상 GGUF 가 틀렸다
- 사용자가 정밀 판정을 기다리는 시간은 계정당 약 1분 → 약 20초(중앙 63.3 → 20.4초)로 준다. 빠른 결과(약 8초)는 1단 CPU 몫이라 엔진과 무관하다

## 한계

- NF4 exp09 는 10/27 GPU 서버 실행을 비교 기준으로 썼다. 판정은 장치와 무관한 greedy 이지만 NF4 커널(bitsandbytes)과 llama.cpp 커널은 수치가 다르다 — 이 735칸 · 11계정 · exp22b 30계정 밖의 입력에서 판정이 갈릴 수 있다(앱 11계정 중 1칸이 그 예)
- 판정 일치는 코퍼스 v0 가상 인물에서만 쟀다. 실제 글 분포는 보지 않았다
- 종단 시간은 PC 한 대 · 계정당 1회(워밍업 1회 뒤)다
- llama.cpp 바이너리 · CUDA 런타임은 저장소 밖이다. 다른 PC 는 같은 b12090 zip 을 받아 해시를 확인해야 한다
