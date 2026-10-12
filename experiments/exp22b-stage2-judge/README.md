# exp22b-stage2-judge: 2단 v1 · v2 판정 — exp22 를 다시 (출력 상한 고친 뒤) · **한 번만 채점**

## 1. 왜 다시 하나

[exp22](../exp22-stage2-judge/README.md) 는 **판정 불가**로 끝났다 — v1 · v2 모두 30계정 중 23개가 앱의 출력 상한(`infer.output_budget`)에서 답변이 잘려 규칙으로 떨어졌다 (§6). 상한을 실제 근거 크기로 고쳤고(#346), exp22 는 이미 열었으므로 **고친 뒤의 수치는 exp22 로 주장하지 않는다**. 같은 설계의 새 셋으로 다시 판정한다.

## 2. 규칙 — exp22 §2 그대로 (2026-10-12 · 데이터를 만들기 전)

지표(M1~M5) · 정답 두 가지 · 채점하는 출력 두 가지 · **교체 기준 1~6** · 지키는 것 모두 [exp22 §2](../exp22-stage2-judge/README.md) 와 같다. 다른 점만:

| | exp22 | exp22b |
|---|---|---|
| 출력 상한 | 옛 `output_budget(스팬 수)` (근거당 17토큰 가정) | **고친 `output_budget(entries)`** (#346 · ID 길이로 계산 · 최대 2048) — 두 구성 같다 |
| seed | 20261013 | **20261015** (다른 계정 · 다른 조건 배치) |
| 계정 / 글 ID | `G22_01` / `G22_01_p13` | **`H01` / `H01_b07`** — 앱(Veilo)의 글 ID 와 같은 길이 |
| 남의 정보 | 「오빠는 은행원이고」(「오빠」가 성별 단서 · 설계 실수) | **「지인은 은행원이고」** |
| 표현 은행 | `BANK` | 같다 — 2단은 가명 토큰만 보므로 표현 값은 2단 판정에 들어가지 않는다. 1단 입력을 만드는 데만 쓴다 |

exp22 에서 본 것은 집계 지표와 잘림 원인뿐이고, 그 결과로 2단 구성(프롬프트 · 입력 상한 · 어댑터)은 바꾸지 않았다. 바꾼 것은 두 구성에 똑같이 적용되는 출력 상한 버그 하나다.

## 3. 실행

```bash
export PYTHONIOENCODING=utf-8 PYTHONPATH="src;." HF_HUB_OFFLINE=1
python experiments/exp22b-stage2-judge/specs.py                    # 분포 · 겹침
python -u experiments/exp22b-stage2-judge/generate.py --env .env    # Gemini (GEMINI_API_KEY 는 환경변수)
python experiments/exp22b-stage2-judge/review.py                    # 전수 검토 기록
ENGINE_MODE=real C1_CHECKPOINT_DIR=<v2 폴더> python experiments/exp22b-stage2-judge/run_stage1.py
python experiments/exp22b-stage2-judge/run_stage2.py --config v1 --adapter <v1 보관본>
python experiments/exp22b-stage2-judge/run_stage2.py --config v2
python experiments/exp22b-stage2-judge/score.py
```

## 4. 생성 · 전수 검토 (2026-10-12, D) — 고정

`data/accounts.jsonl` SHA-256 (LF) = `50213cdbd0a407f90651459fee9fbdc4bc8e33e9d61c68c9229933ca45a57c8d`

- 생성: 30계정 × 24편 = 720편 · 다시 쓴 글 1
- 검토: 1단 · 2단을 돌리지 않고 원문만 — 심은 표현 545개가 든 문장 전부 · N 칸은 키워드 표시. 주 지표(M1~M5)에는 영향 없고 참고 지표만 뺀다 (`review.py`)

| 무엇 | 수 | 내용 |
|---|---:|---|
| 심은 표현 제외 | 23 | 드라마 장면 · 방문지(「부천 중동 다녀왔다」 「울산 삼산동 들러서 숙소」) · 시간 표현(「새벽 첫차 다니는 시간」) · 예전 일 · 가정 · 남의 정보(「올해 쉰둘 먹은 우리 아빠」 「쌍둥이 키우는 친구」) |
| 칸 제외 | 19 | 「은퇴한 지 3년째」인데 출근 · 일하는 글이 섞인 H03 · H20 · H22 · H24 의 직업 · 통근 · 소득(Gemini 모순) · 계정 전체가 「내가 옛날에 …」인 H28 의 7칸 |
| N 칸 표시 | 18 / 53 | 심지 않은 곳에 그 속성 단서일 수 있는 말 |

## 5. 결과

(판정 뒤 채운다)
