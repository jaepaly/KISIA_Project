# 기동 · 외부 요청 재검증 — W12 2단 GGUF 경로 (Q8_0 베이스 + LoRA 분리)

> 근거: [DEC-017](../decisions.md) · [freeze-W11](freeze-W11.md) 과 같은 확인을 2단 GGUF 경로로 다시 했다. freeze-W11 · [network-zero-W08](network-zero-W08.md) 은 NF4 · 규칙 경로 기록이라 그대로 둔다
> 확인: 2026-11-05 00:02~00:13 · D · 로컬 Windows 10 · **RTX 3060** · 브랜치 `PM/app/progressive-stage2` 코드 커밋 `54de0cf`
> 실행: 촬영과 같은 기동 스크립트(저장소 밖)로 Veilo(`apps/sns` · 3000) + 분석기(`apps/analyzer` · 8000) + 촬영용 프록시(8080 `/check`)를 같은 PC 에서 · `ENGINE_MODE=real` · `STAGE2_MODE=auto` · `STAGE2_ENGINE=gguf` · `STAGE2_GGUF`=베이스 `stage2v2-dqonly-Q8_0.gguf` · `STAGE2_GGUF_LORA`=`stage2v2-lora-f32.gguf` · 1단 v2 체크포인트(`C1_CHECKPOINT_DIR`) · `HF_HUB_OFFLINE=1` · `ALLOW_EXTERNAL_LLM` 기본(false)
> Veilo DB 는 코퍼스에서 시딩한 DB(`seed_sns.py` · 115명) · 시딩된 가상 계정만 썼다 · 가중치 해시 · llama.cpp 빌드는 [models/registry.md](../../models/registry.md)

## 결과 — 깨진 곳 없음 · 외부 요청 0 · 위험도 · 사람 수 · 추천이 freeze-W11 과 같음

freeze-W11 과 같은 11계정(메인 `3교대인생` 포함). 계정마다 두 경로로 점검했다.

- (a) **촬영 경로** — 프록시 `POST /check/scan/{user_ref}?progressive=true` → 빠른 결과(규칙) 먼저 → `GET /check/api/stage2-followup` 으로 정밀 판정 도착까지
- (b) **한 번에 응답** — 분석기 `POST /scan/{user_ref}` → 스키마 · 하이라이트 · 근거 검사

| 확인 | 결과 |
|---|---|
| 기동 — 스크립트 시작 → 분석기 `/api/engine-mode` 응답 | **32.0초** · `mode: real` · 1단 규칙 켜짐 · 그때 llama-server(127.0.0.1:8092) 대기 중 |
| llama-server 명령줄 | `llama-server.exe -m stage2v2-dqonly-Q8_0.gguf --lora stage2v2-lora-f32.gguf -c 4096 -np 1 -ngl 99 --host 127.0.0.1 --port 8092 --no-webui` · 부모 프로세스 = 분석기 |
| 정밀 판정 (a) | **11/11 done** · 폴백 0 · `model_version` 전부 `qwen3-4b-qlora-v2-gguf-q8-lora` |
| 한 번에 응답 (b) `model_version` · `external_llm_used` | 11/11 `qwen3-4b-qlora-v2-gguf-q8-lora` · false |
| `stage2-io` `Stage2Output` | 오류 0 |
| 근거 하이라이트 — 스팬 `text` = 채널 원문[`start`:`end`] | **어긋남 0 / 368** |
| 2단 판정 근거 ⊆ 진단 스팬 | 165/165 |
| (a) 정밀 판정 = (b) 판정 (7항목) | 11/11 계정 · 77/77 칸 |
| 위험도 · 사람 수(k) · 추천 조치 수 · 조치 뒤 위험도 = freeze-W11 | **11/11** (아래 표) |

- 스팬 368 · 근거 165 는 freeze-W11 의 모델 2단 수와 같다
- 판정 칸을 NF4 와 직접 맞대지는 않았다(이번 실행은 GGUF 만). NF4 대비 판정은 115계정 비교([exp45 결과 4](../../experiments/exp45-stage2-gguf/README.md) · 804/805)가 덮는다 — 그 비교에서 다른 1칸(B08 commute)은 이 11계정 밖이다

### 계정별 — freeze-W11 과 대조

| 계정 | 스팬 | 위험도 | k | 추천 조치 | 조치 뒤 | 빠른 결과 | 정밀 판정 도착 | 한 번에 응답 |
|---|---|---|---|---|---|---|---|---|
| **u_8c53e7b89615 (메인 · 3교대인생)** | 41 | **61.43** | **302.97** | 1 (−25.0) | **36.43** | 9.9초 | 27.5초 | 26.1초 |
| u_00ceeab4df70 (예비 · 옥동묵향당) | 35 | 63.57 | 11.78 | 3 | 32.14 | 9.4 | 27.3 | 26.9 |
| u_40ef42660c42 | 19 | 35.00 | 3,054 | 0 | 35.00 | 5.7 | 21.7 | 20.9 |
| u_5985f6f8353e | 56 | 42.14 | 11,048 | 1 | 27.86 | 28.2 | 45.7 | 45.1 |
| u_231b2f8e3757 | 52 | 44.29 | 7,046 | 1 | 35.71 | 8.8 | 26.4 | 25.8 |
| u_72ce87717c0c | 23 | 53.57 | 843 | 1 | 39.29 | 8.8 | 25.2 | 23.9 |
| u_bf3d2191e215 | 26 | 34.29 | 998,810 | 0 | 34.29 | 6.2 | 20.7 | 21.2 |
| u_084835c6a489 | 25 | 32.14 | 209,359 | 0 | 32.14 | 23.2 | 39.8 | 39.6 |
| u_0dfab5acbae0 | 16 | 46.43 | 1,723 | 1 | 32.14 | 5.8 | 20.1 | 19.8 |
| u_99e3940e063f | 44 | 61.43 | 537 | 1 | 37.86 | 9.7 | 27.0 | 25.8 |
| u_c9c1dd0d52c9 | 31 | 49.29 | 563,839 | 1 | 35.00 | 7.6 | 24.3 | 24.0 |

- 스팬 · 위험도 · k · 추천 조치 수 · 조치 뒤 위험도가 freeze-W11 표와 **모두 같다**. 메인 계정 61.43 → 36.43 · 약 303명 · 조치 −25.0(freeze-W11 「비공개 3편」)도 같다 — 2단 엔진은 위험도 · 추천을 바꾸지 않는다
- 중앙값 — 빠른 결과 **8.8초** · 정밀 판정 도착 **26.4초** · 한 번에 응답 25.8초. freeze-W11 모델 2단 점검 중앙 68.7초(NF4)와 같은 PC 다. 계정당 1회 · 첫 계정 워밍업 없이 잰 값이다
- u_5985f6f8353e · u_084835c6a489 는 빠른 결과부터 20초를 넘는다 — 1단(CPU) 몫이라 2단 엔진과 무관하다(freeze-W11 규칙 2단에서도 31.8 · 26.4초)

## 외부 요청 0 — 분석기 · Veilo · 프록시 · llama-server 가 연 TCP 연결

기동부터 11계정 × 2경로 점검이 끝날 때까지 시스템 TCP 연결을 0.2초마다 모으고(psutil), 우리가 띄운 프로세스(분석기 · Veilo · 프록시 · llama-server 와 그 자식)의 것만 골라 중복을 뺐다 — **174개**. freeze-W11 과 같은 방식이다(도구만 PowerShell → psutil).

| 원격 주소 | 무엇 |
|---|---|
| `127.0.0.1:8092` | 분석기 → llama-server (같은 PC) |
| `127.0.0.1:8000` · `127.0.0.1:8080` | 하네스 → 프록시 → 분석기 (같은 PC) |
| 그 밖의 `127.0.0.1:*` · `::1:*` | 분석기 → Veilo 내보내기 API · 프로세스 내부 소켓 쌍 (같은 PC) |
| (대기) | 3000 · 8000 · 8080 · 8092 대기 소켓 — 모두 `127.0.0.1` |

**외부 주소 연결: 0개.** llama-server 는 `127.0.0.1:8092` 에서만 대기했고, 연결 상대도 분석기(127.0.0.1)뿐이었다.

- 응답 22개 모두 `external_llm_used: false`
- **서버 실행(veilo.site)은 재지 않았다** — KISIA AWS 지원이 끝났다(10/26). 로컬 실행의 「외부 요청 0(localhost 제외)」만 이 증빙의 범위다

## 종료 — 분석기가 죽으면 llama-server 도 꺼진다

| 확인 | 결과 |
|---|---|
| 분석기 프로세스 강제 종료(kill) → llama-server 종료 | **0.44초** 뒤 꺼짐 (Windows Job · `infer.Stage2GGUF`) |
| 정리 뒤 3000 · 8000 · 8080 · 8092 대기 | 모두 비어 있음 |

## 한계

- PC 한 대(D · RTX 3060)에서 확인했다. 다른 PC 는 registry 의 가중치 · llama.cpp zip 해시를 먼저 맞춘다
- 기동 스크립트 · 하네스는 저장소 밖이다(freeze-W11 과 같다). 하네스 절차는 위 (a) · (b) · TCP 표본 · 강제 종료 그대로다
- 계정 11개 · 계정당 1회다. NF4 대비 판정 · 115계정 전체는 [exp45 결과 4](../../experiments/exp45-stage2-gguf/README.md)
- `STAGE2_ENGINE=gguf` 를 명시해 띄웠다. `STAGE2_ENGINE` 을 비웠을 때 두 파일이 있으면 GGUF 로 고르는 것(DEC-017)은 `src/kopl/c4_stage2/test_gguf.py` 가 덮는다
- 브라우저 네트워크 탭 캡처는 새로 찍지 않았다
