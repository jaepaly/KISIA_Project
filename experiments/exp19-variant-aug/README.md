# exp19-variant-aug: 1단 학습용 변이 글 300편 (#310 2번)

## 1. 왜

코퍼스 밖 평가셋(exp17, #311)에서 1단 재학습+규칙은 본인 단서 85.7%, 교사(Opus 4.8)는 92.4%를 찾는다. 교사 라벨의 질은 병목이 아니다(exp18). **코퍼스(gpt-5.6-sol 3,092편)에 거의 없는 표현을 1단이 못 배운 것**이 남은 차이다 — #241(숫자 나이·반말 어미 0건), 구어체 약점(버스 1/3 · 상가 1/3 · 직업명 7/12 · 배우자 1/2).

## 2. 무엇을 만들었나

| | |
|---|---|
| 글 | **300편** (`AUG1_0001`~`0300`) · 학습 전용 · persona `AUG1` |
| 생성기 | 코퍼스와 같은 `gpt-5.6-sol`(codex CLI) — 생성기를 고정해야 「변이를 넣은 효과」만 따로 본다 |
| 단서 | 539개 지정 — 숫자 나이 · 한글 수사 · 반말 어미 · 금액 · 시·구 · 동 · 역·공원·시장 · 직업명 · 가족 · 배우자 · 노선·버스 · 타인 함정 · 숫자 함정 53편 |
| 라벨 | 교사 Opus 4.8 탐지본(코퍼스 교사와 같음 · KISIA 키) + 교사가 놓친 심은 단서 보충(2건) · 숫자 함정을 AGE 로 잡은 교사 라벨 제거(2건) · 겹침은 코퍼스 관례(긴 스팬 우선, label-schema §6) |
| 결과 | `data/corpus/aug/v1/AUG1_spans.jsonl` — 스팬 639개 · 위치·겹침 오류 0 |

**평가셋과의 겹침 방지**: exp17 에 심은 표현(「나이 48에」 「수원 영통구」 …)과 정답 스팬(「동탄」 「48에」 …)이 학습 글에 나오지 않게 값을 따로 골랐고(`specs.py` 단언), 생성된 본문도 다시 검사했다 — 유출 0편.

## 3. 학습에 넣는 법 (B)

`prepare_bio.py` 에 **`--extra-gold-dir`** 를 추가했다 — 분할(train/test)에 없는 글을 **학습에만** 더한다. 추가 글의 post_id 가 기존 분할과 겹치면 멈춘다.

```bash
python experiments/exp06-finetune/prepare_bio.py --include-unreviewed --extra-gold-dir data/corpus/aug/v1 --out-dir <새 폴더>
```

비교 (#310 3번): 기존 재학습(`w7_teacher_lr1e-5_diagnostic` 설정) vs **같은 설정 + 변이 글** 두 조합.

## 4. 과적합 주의 — 판정 기준

- 변이 글은 exp17 과 **값**은 겹치지 않지만 **변이 종류**는 같은 설계에서 나왔다. exp17 로 재면 오르는 게 당연해 일반화를 과대평가한다
- 그래서 효과 판정은 **새로 만들 최종 평가셋(exp17b · 우리가 노리지 않은 변이 포함 · 한 번만 채점)** 으로 한다. exp17 은 개발용
- 기존 test 239편 · blind 에서 떨어지지 않는지도 같이 본다 — 코퍼스 성능을 해치지 않는다는 근거

## 5. 한계

- 생성기가 코퍼스와 같은 GPT 라 문체 다양성은 크게 늘지 않는다 — 늘리는 건 **표현 종류**다
- 라벨은 교사 라벨(사람 검수 없음) — 코퍼스 미검수 2,281편과 같은 지위. 교사의 기존 잡음(「친구가」를 LOC_ADMIN 으로 등)도 같다
- 300편은 코퍼스 학습 글(2,612편)의 약 11%

## 6. 재현

```bash
export PYTHONIOENCODING=utf-8
python experiments/exp19-variant-aug/specs.py                                         # 분포
PYTHONPATH=src python experiments/exp19-variant-aug/generate.py --shard k --shards 4   # k=0..3 동시에, 끝나면 --merge
PYTHONPATH="src;experiments/exp19-variant-aug" python experiments/exp19-variant-aug/label_aug.py --env <KISIA .env>
```
