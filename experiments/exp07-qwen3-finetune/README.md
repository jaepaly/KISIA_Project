# exp-007: Qwen3-4B QLoRA 파인튜닝 착수

## 무엇을 왜 재는가

- **배경**: DEC-004 로 2단 베이스가 `Qwen3-4B` 로 확정됐다. exp05 는 **프롬프트만으로** 잰 것이고, 두 모델 다 **함정(`subject: other`)을 본인 속성의 근거로 썼다** (4B 도 34명 중 22명). 프롬프트로는 안 잡히는 동작이라 학습 1순위 목표다 ([`models/registry.md`](../../models/registry.md) 「W4 학습 1순위」).
- **이번 주(W4) 질문**: 3060 8GB 에서 QLoRA 학습 잡이 **끝까지 도는가** — epoch 1 · exit 0 · 체크포인트. 성능은 W5 부터 본다.
- **대응 지표**: `D-stage2.md` §7 「Qwen3 vs 외부 AI 일치율 ≥ 0.8」의 전제. 학습이 안 돌면 이 지표를 잴 모델이 없다.

## 설정

| 항목 | 값 |
|---|---|
| 측정일 | **2026-09-07** (환경·VRAM 실측) |
| 데이터 버전 | — (2단 학습 라벨은 이번 주 D 가 만든다, [#124](../../../../issues/124) ②) |
| 모델 | `Qwen/Qwen3-4B` (HF safetensors · bf16 원본) — ollama 의 `qwen3:4b` 와 같은 가중치, 형식만 다르다 |
| 양자화 | NF4 · double quant · compute bf16 |
| LoRA | r=16 · α=32 · `q_proj k_proj v_proj o_proj` · dropout 0.05 |
| 하드웨어 | RTX 3060 8GB (Ampere sm_86) |
| **환경** | Python 3.11.15 · torch 2.11.0+cu128 · transformers 5.15.1 · peft 0.20.0 · bitsandbytes 0.50.1 · accelerate 1.14.0 — venv `~/venvs/kisia` |
| 시드 | 20260907 |

> `trl` 은 쓰지 않는다. `requirements.txt` 에 없고, 팀 전원 재설치를 요구하는 의존성을 W4 에 추가할 이유가 아직 없다. 학습 스크립트는 `transformers.Trainer` 로 쓴다. 필요해지면 그때 핀을 박아 넣는다.

## 실행

```bash
# 1) 가중치 (한 번만, ~8GB)
~/venvs/kisia/Scripts/hf download Qwen/Qwen3-4B

# 2) 로드 + LoRA + 학습 스텝 1회 — VRAM 실측
~/venvs/kisia/Scripts/python experiments/exp07-qwen3-finetune/smoke_load.py --seq-len 1024
```

## 결과

`results/smoke_load_seq*_r16.json` · batch 1 · r=16 · 더미 토큰 · fwd+bwd 1회

| seq | 로드 후 VRAM | 스텝 피크 VRAM | 스텝 시간 | 판정 |
|---:|---:|---:|---:|---|
| 512 | 2.68 GB | **3.92 GB** | 2.6 s | ○ |
| 1024 | 2.68 GB | **5.12 GB** | 4.9 s | ○ — **3060 의 실질 상한** |
| 2048 | 2.68 GB | 8 GB 초과 | 10분+ 미종료 | ✗ 공유메모리로 넘쳐 PCIe 왕복. 중단했다 |

학습 파라미터 11,796,480 / 4,034,264,576 (**0.292%**).

## 해석

**seq 1024 · batch 1 로 학습 잡이 들어간다.** 피크 5.1GB 이고 옵티마이저(PagedAdamW8bit · 11.8M 파라미터)는 100MB 안쪽이라 3GB 가 남는다. 유효 배치는 gradient accumulation 으로 채운다. 2048 은 B 의 5070 12GB 또는 클라우드 몫이다 (`setup-python.md` §5 「W6 폴백 경로」).

**같은 코드로 처음엔 seq 1024 가 OOM 났다 (14GB).** 원인 둘, 둘 다 코드 한 줄이다.

| 원인 | 왜 | 조치 |
|---|---|---|
| `model.train()` 을 안 불렀다 | `from_pretrained` 는 eval 모드로 돌려주고, transformers 는 **train 모드에서만 gradient checkpointing 을 적용한다.** 활성값이 36층 전부 쌓였다 | 스텝 전에 `model.train()`. 이것만으로 seq 1024 가 14GB → 5.1GB |
| `prepare_model_for_kbit_training` | 양자화되지 않은 파라미터(임베딩 389M · lm_head 와 tie)를 **fp32 로 올린다** → +0.8GB. 12GB 카드에서는 무해하지만 8GB 에서는 아깝다 | 쓰지 않는다. `gradient_checkpointing_enable(use_reentrant=False)` + `enable_input_require_grads()` 를 직접 건다 |

`D-stage2.md` W4 실무 §2 의 스니펫이 첫 번째 함정을 그대로 갖고 있어 같이 고쳤다.

## 한계

- 이번 주는 **환경과 VRAM 만** 본다. 학습 라벨이 아직 없어 손실 수치는 더미 배치의 것이고 의미가 없다.
- 어댑터 가중치·`checkpoint-*/` 는 커밋하지 않는다 (`.gitignore`). `models/registry.md` 에 경로·학습일·설정만 적는다.
