# 골드셋 — 사람이 검수한 정답표

**W3 산출.** 600~700 스팬을 다섯 명이 나눠 만든다.

```
data/corpus/v0/gold/A_spans.jsonl     이은선 — blind 100 + 검수분
data/corpus/v0/gold/B_spans.jsonl     최진필 — 검수 130~150
data/corpus/v0/gold/C_spans.jsonl     신정현 — blind 100 + 검수분
data/corpus/v0/gold/D_spans.jsonl     박재현 — 검수 130~150
data/corpus/v0/gold/E_spans.jsonl     이지희 — 검수 130~150
```

한 줄에 스팬 하나. JSONL 이다.

---

## 레코드 형식 — `label-schema` §8-1

```json
{"span_id": "S01_b07_s02", "text_id": "body", "start": 12, "end": 17, "text": "신갈저수지", "type": "LOC_FACILITY", "level": "inferential", "subject": "self"}
```

**붙는 필드는 이 8개까지.** 더 넣지 않는다.

| 필드 | 무엇 |
|---|---|
| `span_id` | **안정 식별자.** `<인물>_<글>_s<번호>` — D 의 판정 근거가 이 값을 가리킨다 |
| `text_id` | offset 의 기준 텍스트. `title` · `body` · `photo_caption:N` · `profile_bio` 넷 (§5-3) |
| `start` `end` | ⚠️ **문자 offset.** 바이트나 토큰 인덱스가 아니다 |
| `text` | 그 구간의 문자열. `start`/`end` 가 맞는지 눈으로 확인하는 용도 |
| `type` | `LOC_FACILITY` `AGE` `JOB` `FAMILY` `COMMUTE` … |
| `level` | `explicit` / `implicit` / `inferential` (§4-1) |
| `subject` | `self` / `other` / `unknown` (§4-2) |

---

## ⚠️ 자주 틀리는 것 넷

### ① 겹치는 스팬은 금지 — 최장 우선

BIO 표기가 겹침을 표현하지 못한다. 「집 근처 신갈저수지」에서 하나를 고른다면 **긴 쪽**이다.

```
✗  (0,4) 집 근처  +  (5,10) 신갈저수지     서로 겹치지 않으면 둘 다 OK
✗  (0,10) 집 근처 신갈저수지  +  (5,10) 신갈저수지   ← 겹친다. 긴 쪽만
```

### ② `level` 은 **표기 형식과 무관**하다

`explicit` 은 「값이 그대로 적힘 · 단독으로 값이 나온다」이다. **한글 수사도 `explicit`** 이다.

```
explicit       마흔여덟 · 34살 · 2호선
implicit       완성차 공장 출장 · 원두 발주       ← 단독으로 업종이 거의 확정
inferential    신갈저수지 · 집 근처               ← 다른 스팬과 묶여야 좁혀진다
```

> 「시험이 일주일 남았다」에는 **나이 값이 없다.** 이건 `explicit` 이 아니라 `inferential` 이다.

### ③ `subject` 는 **그 스팬의 주체**이지 글 전체의 시점이 아니다

「처남이 광교 살아서 거기 저수지에서 봤다」에서 광교에 사는 사람은 처남이다 → `subject: "other"`. **글의 나머지가 내 이야기여도 그렇다.**

### ④ 밈과 세대 신호는 **스팬으로 잡지 않는다** (§7)

글 단위 플래그로 간다.

| 무엇 | 어디로 |
|---|---|
| 밈·유행어 (손민수 · 정병 · 에바) | `flags.meme_hits` |
| 세대 신호 (「무릎이 예전 같지 않네요」) | `flags.gen_signal` |

**스팬에 넣으면 라벨러끼리 갈린다.** 그리고 B 의 암묵 F1 목표치가 IAA 에 묶여 있어서, 갈리는 항목을 넣으면 **목표치까지 같이 깎인다.**

---

## blind 200 — A·C 만

**교사 라벨을 보지 않고** 처음부터 매긴다. A·C 각 100 스팬.

교사 LLM 이 만든 라벨로 학습시키고 교사 라벨로 평가하면 **순환 논리**가 된다. 그 고리를 끊는 유일한 수단이 정답을 안 보고 매긴 라벨이다.

그리고 **A·C 가 같은 글 20편**을 각자 매긴다(IAA 파일럿). 두 사람의 일치도가 **B 의 암묵 F1 목표치의 상한**이 된다 — 사람끼리 0.7 로 갈리는 것을 모델에게 0.9 로 요구할 수 없다.

blind 분은 파일 안에서 구분한다.

```json
{"span_id": "...", "...": "...", "blind": true}
```

---

## 커밋

```
data(c5): 골드셋 140 스팬 검수 (B_spans.jsonl)
```

⚠️ **실데이터 금지.** 여기 들어가는 글은 전부 `data/corpus/v0/posts/` 의 합성 글이다. 실제 블로그에서 가져온 문장은 한 줄도 넣지 않는다.
