# exp-009: Qwen3 v1 vs 외부 LLM 속성 적중 일치율

## 무엇을 왜 재는가

「외부 전송 0」 주장의 근거다 — 로컬 Qwen3 v1 이 외부 LLM 과 같은 판정을 내리면 사용자 글을 밖으로 보내지 않아도 된다 ([D-stage2.md](../../docs/roles/D-stage2.md) §7). 대응 지표는 roadmap §5 G1 **[목표] Qwen3 vs 외부 LLM 속성 적중 일치율 ≥ 0.8**.

- exp04(Claude vs GPT 교차모델)와 다른 지표다 — 그쪽은 임계값이 없다
- #264 의 verdict 90% 는 dev 규칙 타깃과의 비교라 이것도 아니다

**이 실험이 재는 것은 「같은 골드 스팬을 받았을 때 두 모델의 판정이 일치하는가」다.** 두 모델이 글에서 독립적으로 위험을 찾아내는지를 보는 것이 아니다 (스팬은 고정).

## 정의

| 항목 | 정의 |
|---|---|
| **본 지표** | 7속성 × 105명 = **735칸**, 4종 verdict(specified · narrowed · weak_signal · abstain)의 **micro 정확 일치율**. 파싱 실패 = 불일치 |
| 「적중」을 verdict 로 보는 이유 | 계약 `Finding` 에 속성 **값**이 없다 (`stage2-io.schema.json` · `models/registry.md` 「5/7 은 값 적중이라 입증 불가」) |
| `granularity` | 평가하지 않음 — **고정된 체크포인트가 이 필드를 학습하지 않았다** (`make_sft_v1.py` `findings_from_spans`) |
| 대상 글 | 1단 test 평가와 **같은 239편** (clue 159 = blind 검수본 · noise 80 = 검수 골드 · 옛 IAA 16편 제외 — exp06 `evaluate_test.py` 선정 규칙) → 인물 105명 |
| 입력 형태 | **v1 SFT 추론 입력** `{user_ref, profile: null, posts: [{post_id, spans}]}` · 가명화 스팬. 계약 `Stage2Input` 이 아니다 — 이 어댑터가 학습한 형태 |
| 채널 | **body 스팬만** (319개). v1 이 body 만 학습했다. title 25 · photo_caption 14 스팬은 양쪽·규칙 타깃 모두에서 뺐다 |
| 프롬프트 | 양쪽 모두 **Qwen 이 실제 학습한 system 프롬프트** (`v1_train.jsonl` 첫 예시 · `manifest.json` `system_prompt_sha256`) |
| 규칙 타깃 | `make_sft_v1.findings_from_spans()` — Qwen 학습 타깃을 만든 규칙. 3자 비교용 |

## 설정

| 항목 | 값 |
|---|---|
| 측정일 | 2026-09-28 |
| 데이터 버전 | 코퍼스 v0 (v1 동결 d4cf8cb) · test split #244 · 해시는 `data/manifest.json` |
| 로컬 모델 | Qwen/Qwen3-4B 4bit nf4 + `exp08-stage2-sft/results/adapter` (DEC-009 epoch 3 · v1_train 252) — 어댑터 SHA-256 은 `manifest.json` |
| 로컬 디코딩 | greedy · `max_new_tokens` 700 · 생성 후 첫 `{` ~ 마지막 `}` 파싱 (제약 디코딩 없음) |
| 외부 모델 | `claude-sonnet-4-6` · Claude CLI 2.1.283 `claude -p --tools "" --setting-sources "" --json-schema` (스키마 강제) |
| 외부 경로 | **KISIA 팀 게이트웨이 키** (`--env-file` 로 `ANTHROPIC_API_KEY`·`ANTHROPIC_BASE_URL` 만 넘김). 빈 `CLAUDE_CONFIG_DIR` 로 격리 — 격리하지 않으면 PC 의 개인 claude.ai 로그인이 키보다 우선한다 (실측). 시작 시 `authMethod == api_key` 가 아니면 멈춘다 |
| 하드웨어 | RTX 3060 8GB (로컬) · 외부 호스팅 (Claude) |
| 재시도 | 없음 — 실패는 `invalid` |
| 부트스트랩 | 인물 단위 cluster · 2,000회 · seed 20260928 |

## 실행

```bash
export PYTHONIOENCODING=utf-8
python experiments/exp09-external-agreement/build_inputs.py        # inputs.jsonl · manifest.json · pilot_ids.json
python experiments/exp09-external-agreement/run_external.py --pilot --env-file <팀 게이트웨이 .env>  # 5명 파일럿
python experiments/exp09-external-agreement/run_qwen.py --pilot
python experiments/exp09-external-agreement/score.py --pilot
python experiments/exp09-external-agreement/run_external.py --env-file <팀 게이트웨이 .env>  # 105명 (중단되면 다시 실행 — 끝난 인물은 건너뛴다)
python experiments/exp09-external-agreement/run_qwen.py
python experiments/exp09-external-agreement/score.py                # results/metrics.json
python -m pytest -q experiments/exp09-external-agreement/test_score.py
```

`data/*.jsonl` 은 커밋하지 않는다 (재생성 가능 · `.gitignore`). `manifest.json` 과 `results/` 만 추적한다.

## 결과 (2026-09-28 · 105명 · 735칸)

### 본 지표

| | 값 |
|---|---|
| **일치율 (Qwen vs Claude)** | **0.876** · 95% CI [0.859, 0.894] — **[목표] ≥ 0.8 충족** (CI 하한도 0.8 위) |
| Cohen's κ | 0.715 · CI [0.677, 0.752] |
| Gwet AC1 | 0.855 |
| 비기권 칸 일치율 (둘 중 하나라도 비기권) | **0.550** (202칸) |
| 「항상 기권」 기준선 (규칙 대비) | 0.732 |
| 파싱 성공률 | Qwen 1.00 · Claude 1.00 |
| evidence Jaccard (둘 다 비기권 184칸) | 0.966 |

### 3자 비교 — 누가 규칙에서 벗어나나

| | 일치율 | macro-F1 | MCC | 이진 F1 | 이진 특이도 |
|---|---|---|---|---|---|
| Qwen vs Claude | 0.876 | 0.712 | 0.729 | 0.680 | 0.908 |
| **Qwen vs 규칙** | **0.927** | 0.796 | 0.830 | 0.887 | 0.997 |
| Claude vs 규칙 | 0.853 | 0.635 | 0.689 | 0.604 | 0.993 |

McNemar (규칙 기준 정답 여부): Qwen 만 맞힌 칸 67 · Claude 만 맞힌 칸 13 · p < 0.001.

### 불일치 91칸의 구조 (행 = Qwen · 열 = Claude)

| | specified | narrowed | weak_signal | abstain |
|---|---|---|---|---|
| specified | 31 | 3 | 0 | 0 |
| narrowed | 6 | 30 | **60** | 1 |
| weak_signal | 1 | 3 | 50 | 1 |
| abstain | 0 | 1 | 15 | 533 |

**불일치 91칸 중 60칸(66%)이 「Qwen narrowed · Claude weak_signal」 한 칸**이다. 파일럿과 같은 패턴 — 암묵 단서만 있는 속성을 규칙(과 Qwen)은 narrowed 로, Claude 는 weak_signal 로 본다. 프롬프트에 두 등급의 경계가 정의돼 있지 않다.

### 층

| 층 | 칸 | 일치율 | κ | 비기권 일치 |
|---|---|---|---|---|
| SFT 에서 본 인물 (59명) | 413 | 0.852 | 0.710 | 0.567 |
| **처음 보는 인물 (46명)** | 322 | **0.907** | 0.712 | 0.508 |
| clue 글 있는 인물 | 700 | 0.873 | 0.712 | 0.546 |
| noise 만 있는 인물 | 35 | 0.943 | 0.806 | 0.667 |

처음 보는 인물에서 일치율이 더 높다 — 인물 중복이 수치를 부풀리지 않았다.

속성별: age 0.981 · commute 0.962 · income 0.952 · occupation 0.848 · sex 0.829 · location 0.810 · **family 0.752**

## 해석

1. **[목표] 0.8 은 넘었다** — 0.876, CI 하한 0.859. 파싱 실패도 없다.
2. **그러나 일치의 대부분은 「둘 다 기권」이다.** 비기권 칸만 보면 0.55 다. 중간점검에는 0.876 과 κ 0.715 · 비기권 0.55 를 **같이** 낸다.
3. **불일치는 Qwen 의 오류가 아니라 등급 정의 차이다.** Qwen 은 학습 규칙을 0.927 로 따르고(McNemar 67 vs 13), 불일치의 2/3 가 narrowed↔weak_signal 경계 한 곳에 몰려 있다. 「암묵 단서 1개 = narrowed」 라는 **우리 규칙이 외부 모델 감각보다 공격적**이라는 뜻이기도 하다 — 경계를 프롬프트·label-schema 에 명시할지, 규칙을 바꿀지는 별도 결정이다.
4. 로컬 1명당 26.6초 (RTX 3060 · 4bit) · 외부 18.4초.

## 파일럿 (5명 · 35칸 · 게이트웨이)

| | 값 |
|---|---|
| Qwen vs Claude 일치 | 32/35 = 0.914 |
| Qwen vs 규칙 | 35/35 |
| Claude vs 규칙 | 32/35 |
| 불일치 3건 | 전부 occupation **암묵 단서 1개 칸** — Qwen·규칙 `narrowed`, Claude `weak_signal` |

파일럿에서 본 불일치 유형이 본 실행 불일치의 2/3 를 차지했다 (위 결과).

## 한계

1. **공유 스팬 조건부.** 스팬을 골드로 고정했으므로 1단 탐지 오차가 빠져 있다. 실제 파이프라인 일치율은 이보다 낮을 수 있다
2. **abstain 이 다수다** — 규칙 타깃 735칸 중 538칸(73%). 「항상 기권」만 찍어도 규칙 대비 0.73 이다. 그래서 κ · Gwet AC1 · 비기권 칸 일치율을 같이 본다
3. **글 단위 holdout.** test 인물 105명 중 59명은 SFT 학습 데이터에 다른 글로 나왔다 — 본 인물 / 처음 보는 인물로 층을 나눠 보고한다
4. **교사 순환.** 골드 스팬의 교사 모델이 Claude 계열(`cli:claude-opus-4-8`)이고 noise 80편은 교사 보조 검수다. 외부 모델도 Claude 라 clue 포함 인물 / noise 만 있는 인물로 층을 나눠 보고한다. Qwen 의 verdict 타깃은 규칙으로 만든 것이라 Claude 의 판정을 배운 적은 없다
5. **디코딩 비대칭.** 외부는 스키마 강제, Qwen 은 자유 생성 후 파싱 — 파싱 성공률과 양쪽 유효 출력 조건부 일치율을 따로 낸다
6. Claude CLI 는 temperature 를 지정할 수 없다 (기본값) · 1회 실행
7. 첫 본 실행 일부(43명)가 개인 계정 경로로 돌아 폐기했다 (`data/external_personal.jsonl` · 채점 제외). 결과는 전부 게이트웨이 재실행분이다
