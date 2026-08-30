# 생성된 글

**W3 산출.** A·B·C·D 가 각자 계정으로 자기 인물을 돌린다.

```
data/corpus/v0/posts/<인물ID>.jsonl     예: B06.jsonl
```

한 줄에 레코드 하나. **인물당 글 15~30편 + 프로필 1건**이 나온다.

---

## 돌리는 법

```bash
pip install -e .        # 한 번만. 안 하면 ModuleNotFoundError: No module named 'kopl'

# ① 배선 확인 — 키 없이, 더미 텍스트
python -m kopl.c5_corpus.generate \
  --persona data/corpus/v0/personas/B06.json \
  --out /tmp/dryrun --provider echo

# ② 실제 생성
python -m kopl.c5_corpus.generate \
  --persona data/corpus/v0/personas/B*.json \
  --out data/corpus/v0/posts \
  --cards data/realism/cards \
  --provider cli --cli-cmd "codex exec -" \
  --sleep 5
```

**중간에 끊겨도 다시 돌리면 이어서 한다** — 이미 뽑은 `post_id` 는 건너뛴다.

| 옵션 | 언제 |
|---|---|
| `--sample 5` | 인물당 5편만 — 시범 |
| `--sleep 5` | 호출 간 대기. 무료 티어 RPM 회피 |
| `--skip-invalid` | 검증 ERROR 인물을 건너뛰고 계속 |
| `--max-tokens` | 사고 토큰 쓰는 모델은 넉넉히. **잘리면 저장하지 않는다** |

---

## 레코드 두 종류 — `record_type`

⚠️ **프로필은 글이 아니다.** 계정에 붙는 사용자 단위 채널이라 인물마다 레코드가 하나 더 나온다.

### `record_type: "post"`

```json
{"post_id": "B06_b03", "persona_id": "B06", "record_type": "post",
 "title": "...", "body": "...", "photo_captions": {"photo_caption:0": "..."},
 "kind": "clue", "negative_control": false, "clues": [...],
 "gen_model": "...", "prompt_version": "p1.0", "generated_at": "..."}
```

### `record_type: "profile"`

```json
{"post_id": "B06_profile", "persona_id": "B06", "record_type": "profile",
 "profile_bio": "...", "nickname": "...", "clues": [...]}
```

`profile_bio` 는 **모델이 만들지 않는다.** 인물 JSON 의 `account.profile_intro` 를 그대로 내보낸다.

---

## 돌린 뒤 반드시

```bash
python scripts/corpus_audit.py
```

⚠️ **이 스크립트는 인물 JSON 만 읽는다. 생성된 글은 보지 않는다.**

8번 「도달률」이 보는 것은 *설계한 단서가 생성기까지 전달되는가*이지 *생성된 글에 실제로 들어갔는가*가 아니다. 앞의 것은 코드 구조의 문제라 한 번 고치면 계속 0 이다([#112](../../../../../../pull/112) 이전에는 185건 중 57건이 사라지고 있었다).

**글에 단서가 실제로 들어갔는지는 사람이 읽어야 한다.**

| 무엇을 보나 | 어떻게 |
|---|---|
| 단서가 생성기까지 갔나 | `corpus_audit.py` 8번 — 소실 0 이어야 한다 |
| **단서가 글에 실제로 들어갔나** | **사람이 표본을 읽는다** |
| **사람이 쓴 글로 보이나** | **리얼리즘 검수 10편** (`A-data.md` §3 6항목) |

⭐ 생성 뒤 **자기 인물 중 3편을 열어 `clue_plan` 과 대조한다.** 지정한 채널(`title`·`body`·`photo_caption:N`)에 단서가 들어갔는지, 지정하지 않은 신상이 새지 않았는지 본다. 어긋나면 프롬프트 문제라 PM 에게 알린다 — 3,000편을 다 뽑은 뒤에 알면 늦는다.

---

## 커밋

```
data(c5): 인물 15명 글 생성 (B06~B20 · 320편)
```

⚠️ **실데이터 금지.** 여기 들어가는 것은 전부 합성이다. `synthetic: true` 가 아닌 레코드는 훅이 막는다.
