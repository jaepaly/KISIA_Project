# 인터페이스 계약 만드는 법 (E 실무)

> 계약 4종을 **월요일에 껍데기, 목요일에 확정**까지 가져가는 절차.
> 배경과 왜 이게 중요한지는 [E-system.md §3](../E-system.md).

---

## 0. 30초 요약

```
월  빈 스키마 4개 + 예시 4개를 만들어 커밋       (내용은 비어도 된다)
월화 B·C·D와 30분씩 1:1 — 질문지 순서대로 채운다  (그 자리에서 파일을 고친다)
수  PR 올리고 셋에게 리뷰 요청                   (이견은 코멘트로)
목  머지 🔒 + CODEOWNERS 게이트가 켜졌는지 확인
```

**미정으로 두는 것이 제일 나쁘다.** 상대가 "아직 모르겠다"고 하면 내가 기본값을 박고, "이의 없으면 목요일에 이걸로 간다"고 통보한다.

---

## 1. JSON Schema가 뭔가

**"이 JSON은 이런 모양이어야 한다"를 JSON으로 적어둔 것**이다. 적어두면 사람이 눈으로 확인하는 대신 **명령어 한 줄로 검사**할 수 있다.

가장 작은 예 — "post_id는 문자열이고 반드시 있어야 한다":

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["post_id"],
  "properties": {
    "post_id": { "type": "string" }
  }
}
```

### 쓰는 키워드는 8개뿐이다

| 키워드 | 뜻 | 예 |
|---|---|---|
| `type` | 자료형 | `"string"` `"integer"` `"number"` `"boolean"` `"object"` `"array"` `"null"` |
| `required` | **반드시 있어야 하는 필드 목록** | `["post_id", "spans"]` |
| `properties` | 필드별 규칙 | 위 예시 |
| `additionalProperties` | 목록에 없는 필드를 허용할지 | **`false`를 권한다** (오타난 필드가 조용히 통과하는 걸 막는다) |
| `enum` | 값이 이 중 하나 | `["explicit","implicit","inferential"]` |
| `items` | 배열 원소의 규칙 | `{"$ref": "#/$defs/span"}` |
| `$defs` + `$ref` | 반복되는 구조를 한 번만 정의하고 재사용 | 아래 span |
| `description` | 사람이 읽을 설명 | **여기에 단위와 부호를 적는다** ⭐ |

`minimum` `maximum` `pattern` `const` 정도가 더 있고, 그 이상은 이번 프로젝트에서 필요 없다.

> ⚠️ **`description`을 비워두지 않는다.** 계약이 깨지는 지점은 자료형이 아니라 *"이 숫자가 0~1인지 0~100인지"*, *"음수가 어느 쪽인지"* 다. 자료형은 검사기가 잡아주지만 의미는 안 잡아준다.

### 검사하는 법

```bash
pip install check-jsonschema

check-jsonschema \
  --schemafile docs/contracts/span.schema.json \
  docs/contracts/examples/span.example.json
```

통과하면 `ok`, 틀리면 **어느 필드가 왜 틀렸는지**를 찍어준다.

> **규칙: 스키마 1개당 예시 파일 1개를 반드시 같이 둔다.** (`docs/contracts/examples/*.example.json`)
> 스키마만 있고 예시가 없으면 아무도 안 읽는다. 사람들은 예시를 복사해서 쓴다.
> 예시가 있으면 위 명령이 CI에 그대로 들어가서, 나중에 누가 스키마를 잘못 고치면 자동으로 걸린다.

---

## 2. 무엇부터 정하나 — 순서가 정해져 있다

**나중에 바꾸기 어려운 것부터.** 어려운 순서는 이렇다.

| 순위 | 정할 것 | 왜 나중에 못 바꾸나 | 예 |
|---|---|---|---|
| 1 | **필드 이름** | 네 사람의 코드에 문자열로 박힌다. 바꾸면 전부 고쳐야 한다 | `residence` vs `location` |
| 2 | **좌표·단위 기준** | 이미 만든 데이터가 전부 무효가 된다 | 문자 offset vs 바이트 offset |
| 3 | **부호 방향** | 조용히 반대로 계산된다. 에러가 안 난다 ⚠️ | `delta = -18` vs `18` |
| 4 | **값 목록(enum)** | 학습 라벨이 이 목록에 묶인다 | 스팬 유형 9종 |
| 5 | null·빈 값 처리 | 늦게 정해도 고칠 수 있다 | "못 구했다"를 `null`로? `0`으로? |
| 6 | 선택 필드 추가 | **언제든 추가해도 된다** | `score` |

**6번은 나중에 해도 된다.** 그래서 1:1에서 시간이 모자라면 5·6을 버리고 1~4에 시간을 쓴다.

### ✗ 이렇게 정하면 안 되고 ○ 이렇게 정한다

| | ✗ | ○ |
|---|---|---|
| **필드 이름** | 문서마다 다르게 (`sex` / `gender`) | **한 곳을 원본으로 정하고 나머지는 복사** |
| **위치** | "글에서 몇 번째 글자쯤" | `start` = 파이썬 `str` 인덱스, `end`는 **미포함**, `body[start:end] == text` 가 항상 성립 |
| **위험도** | "위험도" | `risk` = **0~100 실수**, 높을수록 위험 |
| **기여도 부호** | "이 글의 기여도" | `delta` = **이 글을 비공개했을 때의 위험도 변화**. 내려가면 **음수** |
| **k값 없음** | `0` | **`null`.** 0은 "이 조건에 해당하는 사람이 없다"는 뜻이고 그건 위험도 최대로 읽힌다 ⚠️ |
| **등급** | `"매우 높음"` (한글) | 코드 값은 `"VERY_HIGH"`, **화면 문구는 E가 따로 매핑**한다 |

> ⭐ **마지막 줄이 중요하다.** 코드에 한글 문자열을 넣으면 나중에 문구를 다듬을 때마다 남의 코드가 깨진다. **값과 표기를 분리한다.**

### 지금 저장소에 이미 충돌이 있다 🔴

7속성의 필드 이름이 **두 가지로 공존한다.**

| 출처 | 표기 |
|---|---|
| [`docs/persona-design.md`](../../persona-design.md) §4-1 `ground_truth` | `age` `sex` `location` `occupation` `family` `commute` `income` |
| [`README.md`](../../../README.md) A 항목 페르소나 예시 | ~~`age` `gender` `residence` `job` …~~ → **W2에 위 표기로 정렬함** |

**목요일 전에 하나로 못 박는다.** 어느 쪽이든 상관없지만 **하나여야 한다.**

- 권장: **`persona-design` 쪽**(`age` `sex` `location` `occupation` `family` `commute` `income`)
  - A의 채점 정답(`ground_truth`)이 이 표기다 — **이미 돌아가는 쪽이 우선이다**
  - C의 특정성 축 이름(`AXES`)과 `specificity.schema.json` 초안이 이미 이 표기다([C-specificity.md §4](../C-specificity.md))
  - *"화면 문구에 쓰기 좋다"* 는 이유는 **바로 위 ✗/○ 표의 마지막 줄과 어긋난다** — 등급과 마찬가지로 **값과 표기를 분리**하고, 화면의 "거주지"는 E가 매핑한다
- README A 항목의 예시는 **W2에 이 표기로 정렬했다.** 남은 곳이 있으면 같이 고친다
- 정하면 `docs/decisions.md`에 `[DEC-002]`로 남긴다. 이 한 줄이 없으면 3주 뒤에 또 갈린다

---

## 3. 계약 4종 — 이걸 복사해서 시작한다

아래는 **초안**이다. 1:1에서 상대와 함께 고친다. 빈 파일에서 시작하는 것보다 틀린 초안을 고치는 쪽이 훨씬 빠르다.

### 3-1. `span.schema.json` — B 최진필

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "kopl/contracts/span.schema.json",
  "title": "1단 준식별자 탐지 출력",
  "type": "object",
  "required": ["schema_version", "post_id", "spans"],
  "additionalProperties": false,
  "properties": {
    "schema_version": { "const": "1.0" },
    "post_id": { "type": "string", "description": "예: S01_b07" },
    "model_version": {
      "type": "string",
      "description": "예: koelectra-base-v3-ft-20260921 / rule-v1 / presidio-2.2. RULES-DO-NOT #9(모든 수치에 모델 버전)을 출력 자체로 만족시킨다"
    },
    "spans": { "type": "array", "items": { "$ref": "#/$defs/span" } }
  },
  "$defs": {
    "span": {
      "type": "object",
      "required": ["start", "end", "text", "type", "level"],
      "additionalProperties": false,
      "properties": {
        "start": {
          "type": "integer", "minimum": 0,
          "description": "본문의 문자 offset. 파이썬 str 인덱스 기준 — 바이트도 토큰도 아니다"
        },
        "end": {
          "type": "integer", "minimum": 0,
          "description": "끝 offset, 미포함(exclusive). body[start:end] == text 가 항상 성립해야 한다"
        },
        "text": { "type": "string" },
        "type": {
          "type": "string",
          "$comment": "원본은 docs/contracts/label-schema.md (A·B 공동 소유). 여기는 복사본이다",
          "enum": ["LOC_ADMIN", "LOC_FACILITY", "AGE", "JOB", "FAMILY",
                   "COMMUTE", "TIME_PATTERN", "NICKNAME", "PII_EXPLICIT"]
        },
        "level": {
          "enum": ["explicit", "implicit", "inferential"],
          "description": "단서 등급. A의 코퍼스 라벨과 같은 값을 쓴다"
        },
        "score": {
          "type": "number", "minimum": 0, "maximum": 1,
          "description": "모델 신뢰도 0~1. 규칙 기반 도구는 생략 가능"
        }
      }
    }
  }
}
```

**⚠️ `type`의 enum은 여기서 정하는 게 아니다.** 원본은 A·B가 만드는 `label-schema.md`다. 같은 목록을 두 문서에 적으면 **반드시 어긋난다.** `$comment`로 원본 위치를 박아두고, 스키마를 고칠 때 원본도 같이 고친다.

**겹치는 스팬**: **금지 · 최장 우선.** 이건 취향이 아니라 **모델 구조에서 나오는 제약**이다 — BIO 태깅은 한 토큰에 라벨을 하나만 붙일 수 있어서 겹침을 애초에 표현하지 못한다([B-detector.md §2.2](../B-detector.md)). 계약이 겹침을 허용하면 **A의 코퍼스를 다시 라벨해야 한다.** 화면 하이라이트 걱정은 여기서 할 일이 아니다.

### 3-2. `specificity.schema.json` — C 신정현

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "kopl/contracts/specificity.schema.json",
  "title": "특정성(k-익명성 근사) 입출력",
  "type": "object",
  "required": ["schema_version", "query", "result"],
  "additionalProperties": false,
  "properties": {
    "schema_version": { "const": "1.0" },
    "query": {
      "type": "object",
      "required": ["attributes"],
      "properties": {
        "attributes": {
          "type": "object",
          "description": "조건 조합. 아는 것만 넣는다. 빈 객체면 전국 인구가 k가 된다",
          "additionalProperties": false,
          "properties": {
            "region_code": {
              "type": "string", "pattern": "^[0-9]{2,10}$",
              "description": "행정표준코드. 반드시 문자열 — 정수로 두면 앞자리 0이 죽는다"
            },
            "age_band": { "enum": ["10s","20s","30s","40s","50s","60s+"] },
            "sex":      { "enum": ["M","F"] }
          }
        }
      }
    },
    "result": {
      "type": "object",
      "required": ["k", "level", "basis"],
      "properties": {
        "k": {
          "type": ["number", "null"], "minimum": 0,
          "description": "추정 모집단 크기(명). 감쇠 곱의 결과라 정수가 아닐 수 있다(581.4). 산출 불가면 null — 0을 쓰지 않는다"
        },
        "level": {
          "enum": ["VERY_HIGH", "HIGH", "ACCEPTABLE", "UNKNOWN"],
          "description": "k<=2 VERY_HIGH / 3~4 HIGH / >=5 ACCEPTABLE / null UNKNOWN. 근거는 §13.1"
        },
        "basis": {
          "type": "object",
          "required": ["source", "as_of"],
          "properties": {
            "source": { "type": "string", "description": "예: 행안부 주민등록 인구통계" },
            "as_of":  { "type": "string", "description": "통계 기준일 YYYY-MM" }
          }
        }
      }
    }
  }
}
```

**`basis`를 빼지 않는다.** 화면에 *"이 동네는 12,345명"* 이라고 띄우려면 **언제 기준 무슨 통계인지**를 같이 보여야 한다. 심사에서 반드시 묻는다.

**`level` 매핑은 C가 아니라 계약이 소유한다.** k→등급 대응은 법적 근거가 붙은 값이므로([§13.1](../../plan.md)) 코드 여러 곳에 흩어지면 안 된다.

> 🔴 **C의 초안과 합쳐야 한다.** [C-specificity.md §9](../C-specificity.md)의 초안에는 위 초안에 **없는 필드가 다섯 개** 더 있다 — `risk`(0~100 서비스 점수) · `risk_by_axis`(7속성별) · `steps`(계산 과정) · `assumptions`(모집단·alpha) · `floor_applied`(하한 클램프 여부). 그리고 `engine_version` · `dict_version`도 온다.
>
> **이 초안만 머지하면 진단 화면을 못 만든다** — 7속성 표시(§5)와 *"이 숫자 어디서 나왔나"* 가 전부 저 필드에서 온다. 반대로 C의 초안은 `basis`가 없다. **1:1에서 하나로 합치고, 초안 두 개가 각자 살아남지 않게 한다.**
>
> 대신 **표기는 이쪽이 맞다** — 등급은 영문 상수(`ACCEPTABLE`), 조건의 해상도 단계는 `resolution`(계약에서 `level`은 이미 단서 등급·위험 등급 두 뜻으로 쓰인다). C의 초안이 이 표기로 정렬되어 있는지 확인한다.
>
> **`age_band` 값 목록도 1:1에서 맞춘다.** 위 초안은 10년 단위(`"40s"`)인데 C가 쓰는 주민등록 인구통계 교차표는 **5년 단위(`"40-44"` `"45-49"`)** 다([`c-public-data.md §5`](c-public-data.md) · 지명 사전 계약의 미결 항목). **인구를 조회하는 쪽 표기를 따른다** — 5년 단위는 10년으로 합칠 수 있지만 반대는 불가능하다.

### 3-3. `contribution.schema.json` — C 신정현

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "kopl/contracts/contribution.schema.json",
  "title": "글별 기여도 · 조치 후 재계산",
  "type": "object",
  "required": ["schema_version", "author_id", "baseline_risk", "posts"],
  "additionalProperties": false,
  "properties": {
    "schema_version": { "const": "1.0" },
    "author_id": { "type": "string" },
    "baseline_risk": {
      "type": "number", "minimum": 0, "maximum": 100,
      "description": "현재 상태의 재식별 위험도 0~100. 높을수록 위험"
    },
    "posts": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["post_id", "delta"],
        "additionalProperties": false,
        "properties": {
          "post_id": { "type": "string" },
          "delta": {
            "type": "number",
            "description": "이 글 하나를 비공개했을 때의 위험도 변화. 내려가면 음수. 예: -18.0"
          },
          "rank": { "type": "integer", "minimum": 1, "description": "|delta| 내림차순 순위" },
          "top_spans": {
            "type": "array", "items": { "type": "string" },
            "description": "이 글이 기여한 이유를 화면에 보여줄 근거 문구 (최대 3개)"
          }
        }
      }
    },
    "recompute": {
      "type": "object",
      "description": "조치를 가정했을 때의 재계산 결과. 조치 화면에서 쓴다",
      "required": ["removed_post_ids", "risk_after"],
      "properties": {
        "removed_post_ids": { "type": "array", "items": { "type": "string" } },
        "risk_after": { "type": "number", "minimum": 0, "maximum": 100 }
      }
    }
  }
}
```

**부호가 이 계약의 전부다.** `delta = -18`이 "18 내려간다"인지 "18 올라간다"인지 어긋나면 **에러 없이 반대로 추천**한다. `description`에 예시 숫자까지 적어두는 이유다.

**`top_spans`가 없으면 조치 화면을 못 만든다.** *"이 글 빼세요"*만 있고 이유가 없으면 사용자는 안 누른다. 1:1에서 이 필드를 반드시 요구한다.

> 🔴 **`recompute` 하나로는 부족하다 — 그리디 경로가 필요하다.** [C-specificity.md §6](../C-specificity.md)에 이유가 있다: 기여도 **상위 3개를 그냥 더하면 실제 감소량과 다르다.** 단서가 두 글에 중복되면 기대보다 크게 떨어지고, 둘이 있어야 좁혀지는 관계면 기대보다 작게 떨어진다. 그래서 추천은 *하나 빼고 → 다시 계산 → 다음을 빼고* 로 만든다.
>
> C의 초안에는 그 결과가 `greedy_path`(`[{remove, risk_after}, …]`)로 들어 있다. **`recompute`(한 번의 재계산)와 `greedy_path`(그 반복)를 둘 다 넣는다.** 화면의 *"이 글 3개 → 79.7 → 41"* 은 `greedy_path`의 마지막 값이지 `delta` 세 개의 합이 아니다 — **합으로 계산해서 띄우면 조용히 틀린 숫자가 나간다.**

### 3-4. `stage2-io.schema.json` — D 박재현

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "kopl/contracts/stage2-io.schema.json",
  "title": "2단 종합 판정 · 조치 추천 입출력",
  "type": "object",
  "required": ["schema_version", "input", "output"],
  "additionalProperties": false,
  "properties": {
    "schema_version": { "const": "1.0" },
    "input": {
      "type": "object",
      "required": ["author_id", "posts"],
      "properties": {
        "author_id": { "type": "string" },
        "posts": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["post_id", "pseudonymized_body", "spans"],
            "properties": {
              "post_id": { "type": "string" },
              "pseudonymized_body": {
                "type": "string",
                "description": "가명화된 본문. 원문(body)은 이 계약에 들어오지 않는다 — RULES-DO-NOT #2"
              },
              "spans": { "type": "array", "description": "span.schema.json 의 spans" }
            }
          }
        },
        "k_values": { "type": "array", "description": "specificity.schema.json 의 result 배열" }
      }
    },
    "output": {
      "type": "object",
      "required": ["findings", "recommendation"],
      "properties": {
        "findings": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["attr", "abstained"],
            "properties": {
              "attr": {
                "enum": ["age","sex","location","occupation","family","commute","income"],
                "$comment": "7속성 고정. 학력·전공·정치성향·건강은 이 목록에 없다 — RULES-DO-NOT #4"
              },
              "abstained": {
                "type": "boolean",
                "description": "근거가 약해 판정을 기권했는지. true면 verdict는 null"
              },
              "verdict": {
                "type": ["string", "null"],
                "description": "특정 가능 '범위'만 쓴다. 예: '동 단위로 특정 가능'. 신상 단정 금지 — RULES-DO-NOT #5"
              },
              "evidence_post_ids": { "type": "array", "items": { "type": "string" } },
              "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
            }
          }
        },
        "recommendation": {
          "type": "object",
          "required": ["target_risk", "actions", "expected_risk_after"],
          "properties": {
            "target_risk": { "type": "number", "description": "목표 위험도. 기본 40" },
            "expected_risk_after": { "type": "number" },
            "actions": {
              "type": "array",
              "items": {
                "type": "object",
                "required": ["type", "post_ids"],
                "properties": {
                  "type": { "enum": ["rewrite", "activity_meta", "private", "delete"] },
                  "post_ids": { "type": "array", "items": { "type": "string" } },
                  "rewrite_pairs": {
                    "type": "array",
                    "description": "type=rewrite 일 때만. {before, after} 쌍",
                    "items": {
                      "type": "object",
                      "properties": { "before": {"type":"string"}, "after": {"type":"string"} }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

### ⭐ 스키마가 팀 규칙을 강제하는 장치가 된다

위 파일에서 세 가지를 눈여겨본다.

| 스키마의 장치 | 강제되는 규칙 |
|---|---|
| `input.posts`에 `body`가 **없다**. `pseudonymized_body`만 있다 | [RULES #2](../../RULES-DO-NOT.md) — 2단에 원문을 넘기지 않는다 |
| `attr` enum에 **학력·건강·정치성향이 없다** | [RULES #4](../../RULES-DO-NOT.md) — 민감 속성 미추론 |
| `abstained` 필드가 **required**다 | [RULES #5](../../RULES-DO-NOT.md) — 근거 없으면 기권. 필드가 없으면 기권을 표현할 방법이 없다 |

**문서로 적어둔 규칙은 잊히고, 스키마에 박은 규칙은 검사기가 잡는다.** 계약을 이렇게 쓰는 것이 이 자리가 할 수 있는 가장 값싼 방어다.

### 빠뜨리기 쉬운 필드 4개

| 필드 | 없으면 |
|---|---|
| `schema_version` | 나중에 계약을 고쳤을 때 **어느 버전인지 알 수 없다.** 4종 전부에 넣는다 |
| `abstained` | 기권을 표현 못 한다. 우리 대조군 실측(신호 없는 글에서 7속성 중 6개 기권 — *선행 PoC 자체 측정*)을 화면에 못 보여준다 |
| `basis` (k의 출처·기준일) | *"이 숫자 어디서 나왔나"*에 답 못 한다 |
| `top_spans` / `evidence_post_ids` | 조치 화면에 **이유를 못 쓴다.** 근거 없는 추천은 안 눌린다 |

---

## 4. 1:1 어떻게 진행하나

**넷을 한 번에 모으지 않는다.** 모이면 자기 것만 말하다 끝나고, 남의 필드에는 아무도 의견을 안 낸다.

### 30분 타임박스

| 시간 | 할 일 |
|---|---|
| 0~5분 | **초안을 화면에 띄운다.** 설명하지 말고 보여준다 |
| 5~20분 | 아래 질문 목록을 **순서대로.** 답이 나오면 그 자리에서 파일을 고친다 |
| 20~25분 | **예시 JSON 1개를 같이 채운다.** 실제 값으로. 여기서 대부분의 오해가 드러난다 |
| 25~30분 | 미정 항목에 **내가 기본값을 박는다.** "이의 없으면 목요일에 이걸로 확정" |

> **회의록을 쓰지 않는다. 그 자리에서 스키마 파일을 고치고, 상대가 보는 앞에서 커밋한다.**
> 회의록은 아무도 다시 안 읽지만 파일은 코드가 읽는다.

### B 최진필 (span)

| # | 질문 | 왜 | 답이 없으면 이 기본값 |
|---|---|---|---|
| 1 | 위치를 **문자 offset**으로 할까 토큰 인덱스로 할까 | 토크나이저마다 다르다. 토큰 인덱스면 다른 모델로 못 바꾼다 | **문자 offset** (파이썬 str 기준) |
| 2 | `end`는 포함인가 미포함인가 | 한 글자씩 어긋나는 버그의 원인 1위 | **미포함.** `body[start:end] == text` |
| 3 | 겹치는 스팬을 허용하나 | BIO는 겹침을 표현하지 못한다. 허용하면 코퍼스를 다시 라벨해야 한다 | **금지 · 최장 우선** ([B-detector.md §2.2](../B-detector.md)) |
| 4 | 스팬 유형 목록은 몇 개이고 원본은 어디인가 | 두 곳에 적으면 어긋난다 | **`label-schema.md`가 원본.** 스키마는 복사본이고 `$comment`로 표기 |
| 5 | `score`를 항상 주나 | 규칙 기반 베이스라인은 신뢰도가 없다 | **선택 필드** |
| 6 | 글 1건씩 주나 여러 건 묶어서 주나 | 배치 처리 성능 | **1건씩.** 묶음은 배열로 감싸면 된다 |
| 7 | 모델 로드는 누가 하나 — 함수만 주나 서버로 주나 | 통합 방식이 갈린다 | **함수만.** 서버는 E가 감싼다 |

### C 신정현 (specificity · contribution)

| # | 질문 | 왜 | 답이 없으면 이 기본값 |
|---|---|---|---|
| 1 | k는 정수 하나인가, 등급까지 같이 주나 | 등급 매핑이 두 곳에 생기면 어긋난다 | **둘 다 준다.** 매핑 규칙은 계약 소유 |
| 2 | **k를 못 구하면 뭘 주나** | `0`으로 주면 위험도 최대로 읽힌다 ⚠️ | **`null` + `level: UNKNOWN`** |
| 3 | 조건 조합(나이×성별×지역)을 어떻게 표현하나 | 나중에 조건이 늘어난다 | **객체.** 있는 키만 넣는다 |
| 4 | 지명 키가 행정코드인가 문자열인가 | D의 가명화 사전과 같아야 한다 | **행정표준코드 문자열** (앞자리 0 보존) |
| 5 | **`delta` 부호가 어느 쪽인가** ⭐ | 반대면 에러 없이 반대로 추천한다 | **내려가면 음수** |
| 6 | 위험도 범위가 0~100인가 0~1인가 | 화면에 그대로 찍힌다 | **0~100 실수** |
| 7 | 조치 후 재계산을 함수로 부르나, 미리 다 계산해 주나 | 조치 화면의 반응 속도가 갈린다 | **함수 호출.** `removed_post_ids`를 넘기면 `risk_after`를 준다 |
| 8 | 기여도에 **이유**를 같이 주나 | 근거 없는 추천은 안 눌린다 | **`top_spans` 최대 3개** |

### D 박재현 (stage2-io)

| # | 질문 | 왜 | 답이 없으면 이 기본값 |
|---|---|---|---|
| 1 | 2단 입력에 **원문이 필요한가, 가명 텍스트만으로 되나** ⭐ | 원문이 필요하다고 하면 계층 분리가 흔들린다 | **가명 텍스트만.** 필요하다면 그 이유를 `decisions.md`에 남긴다 |
| 2 | 입력에 스팬과 k값을 다 주나 | 2단이 소형으로 충분하다는 가설의 전제다 | **둘 다 준다** (구조화 입력) |
| 3 | 출력의 7속성 필드 이름은 | 저장소에 두 표기가 공존했다 (§2) | **`sex`/`location`/`occupation`** — A의 `ground_truth`·C의 축 이름과 같은 표기. 화면 문구는 E가 매핑 |
| 4 | **기권을 어떻게 표현하나** | 필드가 없으면 기권을 못 한다 | **`abstained: true` + `verdict: null`** |
| 5 | `verdict` 문구를 누가 만드나 | 신상 단정 금지가 여기서 깨진다 | **모델이 만들되 "범위" 형태 고정.** 문구 목록을 D가 제한 |
| 6 | 신뢰도를 주나 | 투명성 의무와 방향이 맞는다 (§13.4) | **0~1 실수** |
| 7 | 추천 조합을 몇 개 주나 | 선택지가 많으면 선택 자체가 부담이다 (§2) | **1개(기본 추천) + 대안 최대 2개** |
| 8 | 리라이트 결과를 **문장 쌍**으로 주나 통글로 주나 | 화면에서 before/after를 나란히 보여야 한다 | **쌍.** `{before, after}` |
| 9 | 조치 실행(비공개 전환)을 2단이 하나 | 계층 경계 문제다 ([E-system.md §2](../E-system.md)) | **하지 않는다.** 추천까지가 몫 |

### 전원에게 공통으로 묻는 4가지

1. 이 함수의 **파이썬 시그니처**가 어떻게 되나 (`f(input: dict) -> dict`)
2. 실패하면 **예외를 던지나, 에러를 담은 dict를 주나** → 기본값: **예외.** E가 감싼다
3. 실행에 **모델 파일이 필요한가**, 경로는 어디로 받나 → `.env`의 `STAGE1_MODEL_PATH` / `STAGE2_MODEL_PATH`
4. **가짜 데이터로 먼저 붙여도 되나** → 항상 예. 붙이는 건 [e-integration.md](e-integration.md)

---

## 5. 수요일 — 회람

```bash
git checkout -b E/contracts/w02-schemas
git add docs/contracts/
git commit -m "feat(contracts): 모듈 인터페이스 계약 4종 초안 + 예시"
git push -u origin E/contracts/w02-schemas
```

PR 본문에 이 3줄만 적는다.

```markdown
## 확정된 것
- 스팬 위치: 문자 offset, end 미포함
- k 산출 불가: null (0 아님)
- delta 부호: 내려가면 음수

## 아직 갈리는 것 (코멘트 주세요)
- 7속성 필드 이름 — **`sex`/`location`/`occupation` 으로 통일**(A의 ground_truth·C의 축 이름 기준). 이의 없으면 [DEC-002]로 기록

## 목요일에 머지합니다. 이의는 수요일까지.
```

**"확정된 것"을 먼저 쓴다.** 전체를 다시 읽으라고 하면 아무도 안 읽는다.

---

## 6. 목요일 — 머지하고 게이트를 켠다 🔒

머지만으로는 계약이 게이트가 되지 않는다. **[`.github/CODEOWNERS`](../../../.github/CODEOWNERS)의 주석을 실제로 켜야 한다.**

```
/docs/contracts/          @jaepaly @<B핸들> @<C핸들> @<D핸들>
```

⚠️ **전제 2개** — 이게 안 되어 있으면 GitHub가 규칙 전체를 **조용히 무시한다.**

1. 네 사람이 저장소 **Collaborator로 초대·수락**되어 있어야 한다 (쓰기 권한 없는 계정은 리뷰어로 인식되지 않는다)
2. 적은 핸들이 **실제로 존재**해야 한다 (없는 계정을 적으면 그 줄이 아니라 파일 전체가 무효가 된다)

### 켜졌는지 확인하는 법 (2분)

`docs/contracts/` 안의 아무 파일에 공백 한 칸을 고쳐 PR을 하나 연다.

- **리뷰어가 자동으로 지정되면** → 켜졌다. PR을 닫는다
- **아무도 안 붙으면** → 안 켜졌다. PM에게 초대 상태를 확인한다

**이걸 확인하지 않으면 "계약이 고정되었다"가 사실이 아니다.** 완료 기준에 넣어둔 이유다.

---

## 7. 막히면

| 상황 | 대처 |
|---|---|
| 상대가 "아직 모르겠다"고 한다 | **내가 기본값을 박고 통보한다.** 위 질문 표의 마지막 칸이 그 기본값이다 |
| 상대가 필드를 20개 요구한다 | *"이번 주에 실제로 쓰는 것만"* 으로 자른다. **선택 필드는 나중에 추가해도 안 깨진다** |
| 두 사람이 다른 이름을 고집한다 | 동전을 던져서라도 정한다. **어느 쪽인지보다 하나인 것이 중요하다.** 정한 근거를 `decisions.md`에 남기면 논쟁이 끝난다 |
| 스키마 문법에서 막힌다 | `check-jsonschema`가 어느 줄이 틀렸는지 말해준다. 그래도 안 되면 **`$defs`를 지우고 펼쳐 쓴다** — 길어져도 동작한다 |
| 목요일까지 4종이 안 된다 | **`span`과 `stage2-io` 2종을 먼저 확정한다.** 이 둘이 3화면의 양 끝이다. 나머지는 금요일 |
| 계약을 고쳐야 할 일이 생겼다 | 숨기지 말고 바꾼다. `schema_version`을 `1.1`로 올리고 **무엇이 바뀌었는지 PR 본문에 한 줄.** 계약은 못 바꾸는 게 아니라 **몰래 못 바꾸는** 것이다 |
