# exp43-self-only-k: k · 위험도 조건을 본인(self) 스팬으로만 — 관계 불명(unknown)을 뺀다

**왜** (10/26 · PM): 실제 블로그 120편을 정독해 대조했더니 k 조건 약 20개 중 사실은 5개 정도였다. 그중 나이 조건 3개
(아이 나이 · 떡국 관용구 · 숙소 광고의 대상 연령)는 1단 subject 가 `unknown` 이었고 2단 나이 판정도 기권(abstain)이었는데
k 에는 글쓴이 나이 조건으로 들어갔다. 2단(`c4_stage2.rules.findings_from_spans` · 2단 학습 타깃)은 **본인 스팬만** 세는데
c2(`clues.span_to_condition`)는 unknown 을 신뢰도 ×0.5 로 넣어서, 같은 스팬을 두 경로가 다르게 골랐다.
×0.5 는 k 의 비율 감쇠에만 듣고 해상도 기반 `risk_total` 에는 그대로 더해졌다.
원문 · 스팬 글자는 저장소에 두지 않는다 — 코드 · 테스트의 예는 지은 것이다.

## 1. 바꾼 것

| 어디 | 전 | 후 |
|---|---|---|
| `clues.span_to_condition` | self · unknown(×0.5) → 조건, other → 없음 | **self 만** 조건. unknown · other 는 None. 허용 밖 subject 는 전처럼 ValueError |
| `clues.build_conditions` REL_WORK → 통근 조건 | `subject != "other"` | `subject == "self"` |
| `clues.build_conditions` 거주 표지(REL_HOME) 승격 | unknown 위치 조건을 `unknown_loc` 로 빼고 승격 | unknown 이 조건을 안 만드니 목록이 필요 없다 — 승격 대상은 전부 본인 위치 |
| `k_engine.conditions_from_posts` 사전 밖 지명 해석기 | other 만 건너뜀 · unknown ×0.5 | **self 만** |

배우자 호칭(SEX → 기혼 family 조건)도 SEX 스팬이 조건이 될 때만 붙으므로 unknown 이면 같이 빠진다.

**같은 경로**: 앱(`apps/analyzer/engines/c23.conditions` · `contribution` · `per_post_k` · `projected_k`), 2단 추천 엔진의 현재 위험
(`c4_stage2.infer._app_conditions`), 하류 러너(`experiments/bench/d_risk_action.app_engine`)가 모두 `conditions_from_posts` →
`build_conditions` → `span_to_condition` 하나를 탄다. `apps/analyzer` 는 고치지 않았다.

**계약**: `docs/contracts/` 는 unknown 을 조건에 넣으라고 정하지 않는다(`specificity.schema.json` condition 의 `confidence` 는
「로컬 탐지기가 해당 조건을 추출한 신뢰도」뿐). `stage2-io` findings 판정 기준이 「본인(subject=self) 스팬만」이다 — 이번 변경으로 c2 가 그쪽에 맞춰진다.

**예전 설계와 다른 점**: exp38(통근 교통 말 없으면 unknown) · exp42 R2④ · R4(주인 없는 아기 나이 · 지명 나열 → unknown)는
「버리지 않고 unknown(점선)으로 낮추면 엔진이 절반으로 센다」를 전제로 했다. 이제 엔진은 unknown 을 세지 않는다.
화면 하이라이트(점선)는 그대로 남는다 — 1단 스팬은 바뀌지 않는다.

### 2단 기권과 직접 묶지 않은 이유

서버 순서가 `conditions → specificity(k) → contribution(위험도) → stage2(risk_current=위험도)` 이고, 2단 추천 엔진도 안에서 같은
c2 조건으로 현재 위험을 다시 잰다. k 를 2단 판정에 묶으려면 서버 순서를 바꿔야 한다(apps/analyzer — 다른 작업과 겹침).
대신 dev 에서 **2단 기권 ↔ k 조건 유무가 어긋나는 칸**을 셌다(§2-3) — self-only 만으로 남는 어긋남은 구조적인 12칸뿐이다.

## 2. dev 측정 (test 아님)

- 일치 판정: 같은 글 · 같은 채널 · 같은 유형 · IoU ≥ 0.5 · 일대일(IoU 큰 쌍부터 — exp41 `match` 와 같다)
- 입력: 하류 러너 10/26 dev 실행(`runs/dev_v2_both_20261026` · 저장소 밖)과 **같은** 1단 v2 dev 예측 2,837편 · 115명
  (sha256 `f9914ae5…` · test 255편 제외는 `d_risk_action.read_preds` 가 강제). 골드는 test 밖 최상위 골드만(94명 · gold/blind 안 읽음)
- 2단 모델은 다시 돌리지 않았다 — 위험도 · k 는 1단 스팬만으로 계산되고 2단 출력을 입력으로 쓰지 않는다.
  2단 기권 대조는 저장된 `stage2_preds.jsonl`(모델 · 규칙)을 읽었다
- 전(03a1482 · main)은 저장된 기준선과 똑같이 재현됐다(ρ 0.8476 · MAE 4.80)

```bash
export PYTHONIOENCODING=utf-8 PYTHONPATH=src
python experiments/exp43-self-only-k/measure.py dump --preds <dev spans jsonl> --out <저장소 밖>/before.json   # main 에서
python experiments/exp43-self-only-k/measure.py dump --preds <dev spans jsonl> --out <저장소 밖>/after.json    # 이 브랜치에서
python experiments/exp43-self-only-k/measure.py compare --before … --after … --out experiments/exp43-self-only-k/results/summary.json
python experiments/exp43-self-only-k/measure.py consistency --before … --after … --stage2-model <run>/downstream/stage2/stage2_preds.jsonl \
    --stage2-rules <run>/downstream_rules/stage2/stage2_preds.jsonl --out experiments/exp43-self-only-k/results/stage2_consistency.json
```

### 2-1. 위험도 · k ([results/summary.json](results/summary.json))

| | 전 | 후 |
|---|---|---|
| 예측 위험 vs 골드 위험 Spearman ρ (94명) | 0.8476 | **0.8395** |
| MAE | 4.80 | **4.85** |
| 예측 위험 평균 / 골드 위험 평균 | 45.46 / 43.08 | 45.46 / **42.83** |
| k 등급(예측 · 115명) | ACCEPTABLE 114 · HIGH 1 | 같음 (바뀐 사람 0 · k 값이 바뀐 사람 0) |
| k 등급 예측↔골드 일치 | 0.9787 | 0.9787 |
| 조건이 바뀐 사람 — 예측 / 골드 | — | **24명 / 13명** |
| 위험이 바뀐 사람 — 예측 / 골드 | — | **0명 / 3명** |
| 나이 축 조건 수 — 예측 / 골드 | 135 / 105 | **135 / 103** |
| 통근 축 조건 수 — 예측 / 골드 | 500 / 262 | **463** / 262 |
| 가족 · 위치 · 직업 · 소득 조건(골드) | 382 · 502 · 301 · 53 | 376 · 497 · 298 · 52 |

- 예측 쪽은 unknown 이 COMMUTE 37개뿐이었고(1단 dev 예측에 AGE unknown 0), 그 사람들은 이미 본인 통근 조건이 있어
  **예측 위험 · k 는 한 명도 안 바뀌었다**. 조건 목록만 24명에서 줄었다
- ρ · MAE 가 조금 나빠진 것은 **골드 쪽** 변화다 — 골드 스팬의 unknown 17개(FAM 6 · LOC_ADMIN 5 · JOB 3 · AGE 2 · INCOME 1)가
  빠져 13명의 골드 조건이 줄었고 그중 3명의 골드 위험이 내려갔다(평균 43.08 → 42.83). 예측 쪽은 unknown 이 통근뿐이라
  위험이 그대로다. 전후 모두 같은 규칙을 양쪽에 적용한 비교다
- dev 는 k 가 거의 다 ACCEPTABLE 이라 k 등급 변화로는 이 변경을 볼 수 없다. k 가 움직이는 것은 실제 블로그 쪽이다(§3)

### 2-2. 통근 축 점검 (코드 변경 없음)

| | 수 | 골드와 맞음 | 비율 |
|---|---|---|---|
| 예측 COMMUTE self 스팬 (골드 있는 글) | 281 | 137 (골드 self 136) | **0.488** |
| 예측 COMMUTE unknown 스팬 — 이번에 빠진 것 | 31 | 0 | **0.0** |
| REL_WORK → 통근 조건이 생긴 글 | 110 | 골드 REL_WORK self 있음 81 | 0.736 |
| 예측에 통근 조건이 있는 사람 | 81 / 94 | 그중 골드에도 통근 조건 72 | 0.889 (사람 단위 · 축 유무만) |

유형별 본인 스팬 정밀도(같은 정의)와 견주면 COMMUTE 0.488 이 가장 낮다 — LOC_ADMIN 0.782 · AGE 0.73 · SEX 0.73 · FAM 0.63 ·
REL_WORK 0.634 · LOC_FACILITY 0.551 · JOB 0.522 · REL_HOME 0.52 · INCOME 0.508. 골드가 반복 언급을 다 라벨하지 않아 모든 유형이
낮게 나오는 정의라 절대값보다 순서로 읽는다. 사람 단위 0.889 는 「예측에 통근 조건이 있는 사람 중 골드에도 있는 비율」이라
표현 하나하나가 맞았다는 뜻이 아니다.
의견: 합성 인물은 통근 단서를 설계해 넣어 글에 출퇴근 이야기가 많고, 그래서 「교통 말 = 통근」이 대체로 맞는다. 실제 블로그는 여행 ·
이동 이야기(비행기 · 택시 · 「차로 몇 시간」 꼴)가 많아 같은 말이 통근이 아니다. 블로그에서 통근 단서가 하나도 맞지 않은 것과
dev 0.488 의 차이는 이 때문이라고 본다(가설 — 실제 글의 통근 정밀도는 따로 재지 않았다).

### 2-3. 2단 기권 ↔ k 조건 ([results/stage2_consistency.json](results/stage2_consistency.json))

115명 × 7속성 = 805칸. 2단 모델과 규칙의 기권 여부를 (사람, 속성) 칸끼리 직접 견주면 다른 칸이 0이다
(판정이 다른 11칸은 기권이 아닌 등급끼리). 칸 목록은 결과 파일 `cells` 에 있다.

| 어긋남 | 전 | 후 | 이유 |
|---|---|---|---|
| 2단 기권인데 k 조건 있음 | 12 (통근 10 · 가족 2) | 12 | REL_WORK 가 c2 에선 통근 조건, 2단에선 직업 · 배우자 호칭이 c2 에선 기혼 조건 |
| 2단 판정했는데 k 조건 없음 | 25 (가족 19 · 직업 5 · 위치 1) | 25 | REL_HOME 이 2단에선 가족 · REL_WORK 만 있는 직업 · 사전에 없는 지명 |

dev 에서는 unknown 이 이미 본인 조건과 같은 축에만 있어 칸 수가 안 바뀌었다. 남은 12 · 25칸은 subject 가 아니라 **유형→축 대응이
c2 와 2단에서 다른** 것이다(바꾸려면 설계 판단 — 이 실험 밖).

## 3. 실제 블로그 4묶음 (읽기만 · 결과는 저장소 밖)

PM 이 허락받은 블로그 분석기 응답 4묶음의 스팬으로 바뀐 c2 를 오프라인으로 다시 돌렸다. 전은 저장된 응답의 k 와 똑같이 재현됐다.
결과 파일과 조건 값은 저장소 밖(`kisia-blog-demo/`)에만 있다.

| 묶음 | 나이 조건 전 → 후 | k 전 → 후 | 등급 | 2단 나이 |
|---|---|---|---|---|
| 1 (해외 판별 · 위치 제외) | 0 → 0 | 6,150,075 → 같음 | ACCEPTABLE | 기권 |
| 2 | 1 → **0** | 854,030 → **1,276,141** | ACCEPTABLE | 기권 |
| 3 | 2 → **0** | 854,030 → **1,276,141** | ACCEPTABLE | 기권 |
| 4 | 2 → **0** (위치 225 → 220) | 12.7 → **28.7** | ACCEPTABLE | 기권 |

나이 조건 5개가 모두 unknown 이었고 모두 빠졌다 — 이제 네 묶음 다 2단 나이 기권과 k 가 맞는다. 통근 조건(묶음마다 3~6개)은
전부 1단이 self 로 판정한 것이라 남는다 — 통근이 아닌 이동 · 여행 표현이 COMMUTE 로 잡힌 것은 1단 문제다.

## 4. 한계

- dev 에는 AGE unknown 예측이 없어, 이번 변경의 주 대상(남의 · 주인 없는 나이)은 dev 지표로 잴 수 없다 — 블로그 4묶음이 근거의 전부다
- unknown 중 실제로 글쓴이 것인 단서(문장만으로 판단 불가인데 사실은 본인)는 이제 k 에서 빠진다 — 그만큼 k 가 커진다(덜 위험하게 보인다).
  골드에서는 unknown 17개가 그런 후보이고, 이로 인해 골드 위험 평균이 0.25 내려갔다
- 앱 `c23.contribution` 의 글별 단서 목록(`clue_ids` · `top_spans`)은 여전히 `subject != "other"` 라 unknown 스팬을 보인다 —
  unknown 나이만 있는 글이면 위험 기여 0인데 그 스팬이 근거로 나간다(Codex 재현). 한 줄(`== "self"`)이면 맞춰지지만
  apps/analyzer 는 다른 작업과 겹쳐 이 변경에서 고치지 않았다. `scripts/gen_contribution_targets.py` 의 `clue_index` 는
  subject 를 아예 거르지 않는다(이번 변경 전부터)
- 예전 실험(exp10 · exp11 · exp25 · `scripts/gen_contribution_targets.py`)을 다시 돌리면 unknown 골드 스팬만큼 값이 달라질 수 있다
