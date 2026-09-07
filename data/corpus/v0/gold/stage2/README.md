# 2단 학습 라벨 — 종합 판정·리라이트 (초안 v0.1 · 2026-09-07 · D)

> **[#124](../../../../../issues/124) ② — D 가 만들고 A 는 형식만 검토한다.** 킥오프 ⑤(B 의 파인튜닝 데이터와 겹치는 포맷) 의 답도 이 문서다.
> 아직 **제안**이다. A·B 확인 뒤 `0.1.0` 으로 올린다.

```
data/corpus/v0/gold/stage2/<persona_id>.json     인물 1명 = 학습 예시 1건의 원본
scripts/build_stage2_labels.py                   인물 JSON → 이 파일 (결정적 · seed 없음)
```

**출력 계약은 새로 만들지 않는다.** `target` 은 [`stage2-io.schema.json`](../../../../../docs/contracts/stage2-io.schema.json) 의 `Stage2Output.findings` 와 `rewrites` 를 **그대로** 쓴다. 학습 라벨이 계약과 다른 모양이면 학습된 모델이 계약과 다른 모양을 낸다.

---

## 1. 왜 스팬 라벨과 별개인가

A 의 교사 라벨(`*_spans.jsonl`)은 **글 하나 안의 구간**이고 B 의 1단이 그걸 BIO 로 배운다. 2단은 **한 사람의 글 묶음**을 받아 「7속성 중 무엇이 특정 가능한가」를 내는 자리라 단위가 다르다 — 스팬 라벨을 아무리 쌓아도 「이 사람은 거주지가 좁혀진다 · 근거는 b03 과 b15」라는 문장은 나오지 않는다.

**교사 라벨 원본은 아직 저장소에 없다** (2026-09-07 기준 `gold/` 에는 blind·IAA 배정표만 있다). 그래서 v0 은 **인물 설계(`clue_plan`)에서 결정적으로 유도한다.** 합성 코퍼스라 정답을 설계자가 이미 적어놨다 — 교사 LLM 이 다시 추측할 이유가 없다.

---

## 2. 입력 — 모델이 보는 것

```jsonc
"input": {
  "user_ref": "u_<sha256(persona_id)[:8]>",       // E 의 make_user_ref 와 같은 규칙
  "profile": { "spans": [ /* text_id: profile_bio */ ] } | null,
  "posts": [
    { "post_id": "D05_b03",
      "spans": [
        { "span_id": "D05_b03_s01", "text_id": "body",
          "text": "면사무소 앞에서 기다렸는디 버스가 한 시간에 한 대 라 그냥 걸어왔다",
          "type": "LOC_ADMIN", "level": "inferential", "subject": "self" }
      ] }
  ]
}
```

| 필드 | 어디서 | 비고 |
|---|---|---|
| `span_id` | `<인물>_<글>_s<NN>` · 프로필은 `<인물>_profile_s<NN>` | `gold/README.md` 표기 그대로. **모델은 이 값을 복사만 한다** — 추론 시엔 B 가 준 id 가 들어온다 |
| `text` | `clue_plan[].clue` | ⚠️ **offset(`start`·`end`) 이 없다.** 생성기가 단서 문장을 45% 바꿔 써서(876건 중 395건 불일치) 설계 문장으로는 자리를 못 찍는다. 2단은 offset 을 읽지 않으므로 학습에 지장 없다 |
| `type` | `clue_plan[].attr` → §3-2 대표 유형 | age→AGE · sex→SEX · location→LOC_ADMIN · occupation→JOB · family→FAM · commute→COMMUTE · income→INCOME. exp05 와 같다. 실제 B 출력은 LOC_FACILITY·REL_HOME 등으로 갈리는데 v0 은 그 구분이 없다 |
| `level` `subject` | `clue_plan` 그대로 | |
| `ambiguous` `note` `attr` | **넣지 않는다** | note 에는 함정 표지가 들어 있다. 모델이 그걸 보면 시험이 아니다 |

**글은 `clue_plan` 에 단서가 있는 것만 담는다.** noise·ambient 글은 v0 입력에 없다 — 계약의 「triage 를 통과한 글만 온다」와 같은 모양이다.

**가명화 텍스트(`TextSegment.pseudonymized`) 가 없다.** 가명화기가 W5 산출이라 지금은 만들 수 없다. v1 에서 넣는다 (§7).

---

## 3. 타깃 — 모델이 내야 하는 것

```jsonc
"target": {
  "findings": {                 // 7 키 전부. 없는 속성도 abstain 으로 명시한다
    "location": { "verdict": "narrowed", "confidence": 0.6, "cross_post": true,
                  "evidence": [ { "post_id": "D05_b03", "span_id": "D05_b03_s01" },
                                { "post_id": "D05_b15", "span_id": "D05_b15_s02" } ] },
    "sex":      { "verdict": "abstain", "confidence": 0.1, "cross_post": false, "evidence": [] },
    // age · occupation · family · commute · income
  },
  "rewrites": [
    { "post_id": "D05_b14", "span_id": "D05_b14_s01", "suggestion": "내 나이가 이만하면 아직 다닐 만 하다" }
  ]
}
```

### 3-1. `findings` 유도 규칙 — 속성마다, 결정적

**후보 = 그 속성의 단서 중 `subject: self` 이고 함정이 아닌 것.**

| 제외 | 왜 |
|---|---|
| `subject: other` · `unknown` | 남의 정보. 계약 제약 7 |
| `note` 에 `통로=` 가 있는 단서 — **`subject: self` 여도** | 출신지·과거거주·과거근무지·방문지·이사(미래) 는 본인 얘기지만 **현 거주지가 아니다** (`persona-design.md` §4-4-1). 이 표지는 입력에 없으므로 **모델은 시제·장소 성격으로 걸러내는 것을 배워야 한다** — exp05 에서 4B 도 34명 중 22명이 못 한 일이고 QLoRA 의 1순위 목표다 |

실측(2026-09-07 · 인물 115명): `clue_plan` 967건 중 함정 133건, **그중 `subject: self` 가 29건** — 과거거주 14 · 출신지 10 · 방문지 3 · 과거근무지 1 · 이사 1. `subject` 만 보는 규칙이면 이 29건이 전부 거주지 근거로 들어간다. D05 에서 시험했을 때 실제로 `b17` 「예전에 광주 살 때는」이 `location: specified` 를 만들었다.

후보에서 판정:

| 조건 | `verdict` | `confidence` |
|---|---|---|
| 후보 없음 | `abstain` | 0.10 |
| `explicit` 하나 이상 | `specified` | 0.90 |
| `implicit` 하나 이상 | `narrowed` | 0.70 |
| `inferential` 이 **서로 다른 글 2편 이상** | `narrowed` | 0.60 |
| `inferential` 하나 | `weak_signal` | 0.40 |

- `ambiguous: true` 인 단서는 **한 등급 낮춰** 센다 (explicit→implicit 취급 …). 귀속 표지가 없어 라벨러도 갈리는 문장이다
- `evidence` = 후보 전부 (`post_id` + `span_id`). 프로필 단서는 `post_id: null`
- `cross_post` = evidence 의 글이 2편 이상
- `granularity` · `relation` 은 **v0 에서 내지 않는다** (계약상 선택 필드). 등급→해상도 매핑은 C 의 k 와 맞춰야 해서 혼자 못 정한다

**confidence 가 등급별 상수인 것은 의도다.** v0 의 목표는 「기권·근거 선택·함정 배제」이고 신뢰도 보정은 W7 일치율 측정 뒤에 본다.

### 3-2. `rewrites` — 여기만 교사 LLM 이 쓴다

대상: **후보 단서 전부**(self · 비함정). 함정과 타인 정보는 우리 사용자의 재식별 단서가 아니라 고치지 않는다.

- `suggestion` 은 **단서 구간만** 바꾼 문장 (`D-stage2.md` §9). 원문 `text` 와 같은 길이대, ≤200자
- 지명·시설·숫자 → 일반 명사 (신갈저수지→동네 저수지 · 마흔여덟→나이가 좀 있다). **말투·방언·어미는 그대로** — 방언은 `dialect_hits` 레이어 몫이고 여기서 지우면 글이 죽는다
- 교사 모델은 `label.py` 규칙을 따른다: **생성 모델과 계열이 달라야 한다.** 코퍼스 `gen_model` 이 `gpt-*` 라 Claude 또는 Gemini
- 합성 데이터라 외부 전송 가능. `ALLOW_EXTERNAL_LLM` 기본값은 건드리지 않고 스크립트 인자로만 켠다
- `semantic_similarity` · `residual_risk` 는 비운다 — 측정치는 W7 리라이트 평가에서

---

## 4. 학습 직렬화

```
system    판정 규칙 (exp05 SYSTEM 을 잇는다 — verdict 4단 정의 · other 제외 · 값 금지 · 기권 정상)
user      input JSON
assistant target JSON        ← 손실은 여기만
```

- **`Stage2Output` 전체를 시키지 않는다.** `recommendation` 은 C 의 `delta` 가 W5 에 나와야 만들 수 있고, `provenance` 는 코드가 채운다. exp05 가 `findings` 만 떼어 쓴 이유와 같다
- 토큰 예산: 3060 상한이 seq 1024 ([exp07](../../../../../experiments/exp07-qwen3-finetune/)). 단서 11건 인물이 입력 ~600 토큰 · 타깃 ~400 토큰 — 들어간다. 넘는 인물은 글 단위로 잘라 예시를 나눈다
- 추론 시 `think=false` + 스키마 강제 (exp05 조건과 동일)

---

## 5. 증강 — 글 부분집합

인물 115명 = 예시 115건이면 SFT 에 모자란다. **타깃이 규칙으로 유도되므로 입력을 바꾸면 타깃이 따라온다.**

```
인물 1명 → 글 부분집합 k개 (k=8, 크기 1~전체, seed 20260907)
        → 각 부분집합에 §3-1 을 다시 적용
```

- 글을 빼면 `narrowed`→`weak_signal`→`abstain` 으로 내려간다 — **기권과 `cross_post` 를 같은 인물 안에서 대조로 배운다**
- 함정 글만 남긴 부분집합은 `location: abstain` 이 정답이 된다 — 함정 배제를 직접 가르치는 예시
- C 의 LOO(글 하나 빼기)와 같은 조작이다. W5 에 C 의 `delta` 가 나오면 같은 부분집합에 `recommendation` 을 붙일 수 있다

약 115 × 9 ≈ 1,000건. 부분집합은 `results/` 가 아니라 학습 시점에 만들고 seed 만 기록한다.

---

## 6. 분할 — A 와 같은 경계

- **인물 단위**로 나눈다. 같은 인물의 부분집합이 train/test 에 갈리면 누수다
- A 의 W4 train/test 분할(`A-data.md` W4 §5, 누수 검사 포함)과 **같은 인물 경계**를 쓴다. 1단·2단이 같은 인물을 학습·평가해야 W7 일치율이 한 표본 위에서 나온다
- blind 배정 인물(100명)을 통째로 빼지는 않는다 — blind 는 1단 탐지 평가용이고 2단 판정과 겹치지 않는다

---

## 7. v0 이 못 하는 것 → v1

| 없는 것 | 왜 지금 안 되나 | 언제 |
|---|---|---|
| offset · 실제 `type` 분포 | 교사 스팬 라벨이 없다 | A 의 `*_spans.jsonl` 이 들어오면 **입력 스팬을 그걸로 교체한다.** B 의 BIO 학습 데이터와 **같은 파일**이 소스가 된다 — 이게 ⑤ 「겹치는 포맷」의 답이다 |
| 가명화 텍스트 | 가명화기 W5 | `TextSegment.pseudonymized` 를 입력에 추가. 스팬만 보는 v0 과 텍스트도 보는 v1 을 **같은 타깃**으로 비교할 수 있다 |
| ambient 4편의 분포 신호 | `ambient_plan` 에 스팬이 없다 | 교사 라벨이 ambient 글에서 무엇을 잡는지 본 뒤 |
| `recommendation` | C 의 `delta` W5 | §5 의 부분집합 위에 얹는다 |
| `granularity` · `relation` | C 의 k 등급과 맞춰야 한다 | W5 C 와 |

---

## 8. 확인 받을 것

- **A** — §2·§3 형식. 특히 「`note` 의 `통로=` 를 함정 판별에 쓴다」가 인물 작성 규칙과 어긋나지 않는지 (`validate.py` 가 이미 같은 정규식을 쓴다)
- **B** — §7 첫 줄. 교사 스팬이 들어오면 1단·2단이 같은 `*_spans.jsonl` 을 읽는 구조로 가도 되는지 · `type` 대표 매핑이 B 의 유형 분포와 크게 다르면 알려달라
- **C** — §3-1 의 `granularity` 보류. W5 에 k 등급과 함께 정한다

이견 없으면 `build_stage2_labels.py` 를 만들어 115명 유도 → 통계(속성별 verdict 분포 · 함정 배제 건수) 를 이 문서에 붙인다.
