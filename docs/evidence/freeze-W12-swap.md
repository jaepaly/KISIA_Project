# 기동 · 115계정 재검증 — W12 1단 교체 (수정 KoELECTRA + 2단 GGUF)

> ⚠️ **골격이다 (11/5).** 〔③ 대기〕 칸은 EC2 측정이 끝나면 채운다. 채우기 전에는 이 문서를 증빙으로 인용하지 않는다
>
> 근거: [DEC-018](../decisions.md) 채택 조건 ③ · [freeze-W12-gguf](freeze-W12-gguf.md) 와 같은 확인을 1단을 바꾼 구성으로 다시 한다. freeze-W12-gguf · [freeze-W11](freeze-W11.md) 은 1단 v2 기록이라 그대로 둔다
> 확인: 2026-11-05 〔③ 대기: 시각〕 · D · **멘토 EC2 (NVIDIA L4)** · 저장소 커밋 〔③ 대기: 커밋〕
> 실행: Veilo(`apps/sns` · 3000) + 분석기(`apps/analyzer` · 8000) + 촬영용 프록시(8080 `/check`)를 같은 인스턴스에서 실행한다 · `ENGINE_MODE=real` · `STAGE2_MODE=auto` · `STAGE2_ENGINE=gguf` · `STAGE2_GGUF`=베이스 `stage2v2-dqonly-Q8_0.gguf` · `STAGE2_GGUF_LORA`=`stage2v2-lora-f32.gguf` · **`C1_CHECKPOINT_DIR`=수정 KoELECTRA `repaired_3060/checkpoint-epoch-20`** · `C1_RULES` 켬 · `HF_HUB_OFFLINE=1` · `ALLOW_EXTERNAL_LLM` 기본(false)
> Veilo DB 는 코퍼스에서 시딩한 DB(`seed_sns.py` · 115명)다 · 시딩된 가상 계정만 쓴다 · 가중치 해시는 아래 표와 [models/registry.md](../../models/registry.md)

## 구성 — 체크포인트 해시

| 구성 요소 | 파일 | SHA-256 | 인스턴스에서 확인 |
|---|---|---|---|
| 1단 (수정 KoELECTRA) | `repaired_3060/checkpoint-epoch-20/model.safetensors` | `039de28698090579c9c4bf7e02130077df9ad82427a2f82d5b0bbcc103d4ef7c` | 〔③ 대기〕 |
| 2단 베이스 GGUF | `stage2v2-dqonly-Q8_0.gguf` | `f4982df0149f89e7300314d0f1a5d20dc34b6b5d7d0c6e03a754c30431a575b0` | 〔③ 대기〕 |
| 2단 LoRA GGUF | `stage2v2-lora-f32.gguf` | `ae0104d45f7359af3484ff0585840ffd1432951519ff2f0fc19de8b2d07eb74d` | 〔③ 대기〕 |
| llama.cpp | b12090 (인스턴스 빌드 · 〔③ 대기: 바이너리 출처〕) | 〔③ 대기〕 | 〔③ 대기〕 |
| 분석기 `/api/engine-mode` 의 1단 체크포인트 | — | — | 〔③ 대기: 응답에 `repaired_3060/checkpoint-epoch-20` 표시〕 |

## 결과 — 채택 조건 ③ (115계정 앱 전체 경로)

DEC-018 ③ 기준(사전 등록 · 11/5): **오류 0 · 2단 폴백 0 · 스키마 오류 0.** 하나라도 넘으면 DEC-018 은 Rejected 가 되고 1단 v2 를 유지한다.

| 확인 | 기준 | 결과 |
|---|---|---|
| 계정 수 | 115 | 〔③ 대기〕 |
| 분석기 오류 (HTTP 5xx · 예외) | 0 | 〔③ 대기〕 |
| 2단 정밀 판정 done · 폴백 | 115/115 · 0 | 〔③ 대기〕 |
| `model_version` (2단) | 전부 `qwen3-4b-qlora-v2-gguf-q8-lora` | 〔③ 대기〕 |
| 계약 스키마 오류 (`ScanResult` · `Stage2Output`) | 0 | 〔③ 대기〕 |
| 근거 하이라이트 — 스팬 `text` = 채널 원문[`start`:`end`] | 어긋남 0 | 〔③ 대기〕 |
| 2단 판정 근거 ⊆ 진단 스팬 | 전부 | 〔③ 대기〕 |
| `external_llm_used` | 전부 false | 〔③ 대기〕 |
| 빠른 결과 · 정밀 판정 도착 중앙값 | 참고 (L4) | 〔③ 대기〕 |

### 메인 · 예비 계정 — 1단 v2 구성(freeze-W12-gguf)과 대조

1단이 바뀌면 스팬 · 위험도 · k · 추천이 **달라질 수 있다.** 같을 것을 기대하는 표가 아니라, 촬영 대본 · 자막에 쓸 숫자를 새로 정하는 표다.

| 계정 | 스팬 (v2 → 수정) | 위험도 | k | 추천 조치 | 조치 뒤 |
|---|---|---|---|---|---|
| **u_8c53e7b89615 (메인 · 3교대인생)** | 41 → 〔③ 대기〕 | 61.43 → 〔③ 대기〕 | 302.97 → 〔③ 대기〕 | 1 (−25.0) → 〔③ 대기〕 | 36.43 → 〔③ 대기〕 |
| u_00ceeab4df70 (예비 · 옥동묵향당) | 35 → 〔③ 대기〕 | 63.57 → 〔③ 대기〕 | 11.78 → 〔③ 대기〕 | 3 → 〔③ 대기〕 | 32.14 → 〔③ 대기〕 |

- 115계정 전체에서 v2 대비 바뀐 계정 수 · 위험도 차이 분포: 〔③ 대기〕

## 외부 요청 0

〔③ 대기〕 — freeze-W12-gguf 와 같은 방식(psutil · 0.2초 간격 · 우리가 띄운 프로세스만)을 쓴다. 이번 실행 장소는 EC2 이므로 「외부 주소」는 인스턴스 밖 주소를 말한다. 촬영용 터널(cloudflared)로 나가는 연결은 분석과 따로 분리해 적는다.

## 한계

- 인스턴스 한 대(멘토 EC2 · L4)에서 확인했다. 로컬 PC(RTX 3060) 결과는 freeze-W12-gguf(1단 v2)뿐이다
- 1단 교체의 정확도 근거와 한계(공식 정답(C) 기준 하락 포함)는 이 문서가 아니라 [DEC-018](../decisions.md) · [models/registry.md](../../models/registry.md) 에 있다
- 〔③ 대기: 측정 뒤 추가할 한계〕
