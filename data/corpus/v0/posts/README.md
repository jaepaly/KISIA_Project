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

**8번 항목이 도달률을 본다.** 설계한 단서가 전부 생성기에 도달했는지 확인한다.

```
설계 276건 → 도달 276건 (소실 0)
```

> W2 까지는 185건 중 57건(31%)이 조용히 사라지고 있었다([#112](../../../../../../pull/112)). 지금은 **0 이어야 한다.** 0 이 아니면 그대로 두지 말고 PM 에게 알린다.

---

## 커밋

```
data(c5): 인물 15명 글 생성 (B06~B20 · 320편)
```

⚠️ **실데이터 금지.** 여기 들어가는 것은 전부 합성이다. `synthetic: true` 가 아닌 레코드는 훅이 막는다.
