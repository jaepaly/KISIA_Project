# AGENTS.md — AI 도구 작업 지침

이 저장소에서 AI 도구(Codex·Claude·Cursor 등)로 작업할 때의 규범이다.
**프로젝트가 무엇인지는 여기 없다** — [README.md](README.md)(이번 주 정본)와 [docs/](docs/)를 먼저 읽는다.

## 문서 위계 — 어긋나면 누가 이기나

1. **README.md** — 이번 주 할 일의 정본. 완료 기준이 roadmap 과 달라 보이면 **README 가 이긴다** (roadmap §3 에 명시된 규칙)
2. **docs/contracts/** 6종 — W2 에 고정된 계약. 바꾸려면 반드시 PR (코드오너 리뷰)
3. **docs/roles/** 매뉴얼 — 12주 관점. 주차 상세가 README 와 다르면 README
4. 매뉴얼끼리 어긋나면 **계약 → README → 매뉴얼** 순으로 정본을 찾고, 어긋남 자체를 고쳐서 올린다

## 작업 규범 — 사람에 관한 것

- **팀원 실수는 지적만 하고 넘기지 않는다.** 고칠 수 있으면 고쳐서 PR 을 열고 「확인해보니 이런 부분만 수정하면 좋을 것 같아 이렇게 수정했음. 리뷰해보고 괜찮으면 승인해줘」 형식으로 쓴다. 설계 판단이 섞이면 되돌리기 쉽게 만들고 그 지점을 PR 에 명시한다. **한 명만 승인해도 머지한다**고 밝혀 대기를 줄인다.
- **이슈는 담당자(assignee)를 반드시 건다.** 본문 `cc @누구` 는 알림 한 번뿐이고 대기열에 안 남는다. 결정이 필요한 이슈면 결정할 사람 전원을 걸고, 본문이 길면 **결정할 것만 짧은 코멘트로 따로** 올린다. 선택지는 (가)/(나)로 좁히고 추천을 밝힌다.
- **GitHub 글은 자세히 쓴다.** 팀원들은 AI 없이 읽는다. 바뀐 것 · 할 일 · 확인 방법(명령어) · 선택지를 명시한다.
- **역할↔계정 매핑은 `.github/CODEOWNERS` 가 정본이다.** A=nuewsun · B=philotti · C=jhyun114 · D=jaepaly · E=zihhhhh. A 와 C 를 반대로 외우기 쉽다 — 태그 전에 경로로 확인한다.
- 본문을 수정해도 알림이 안 간다. 잘못 태그했으면 **정정 코멘트를 따로** 단다.

## 머지 규칙

- **문서(README·docs/roles·안내 README 류)는 PR 없이 main 에 직접 커밋한다.**
- **코드·데이터·계약은 PR.** 리뷰어를 걸고 한 명 승인 머지를 명시한다.
- ⚠️ **PR 에 CODEOWNERS 경로가 섞이면 자동으로 리뷰 요청이 나가고, 머지 후엔 취소할 수 없다.** `docs/contracts/` · `docs/persona-design.md` · `src/kopl/*` 가 그 경로다. 문서 작업 중 이 경로를 건드리게 되면 **커밋을 분리**한다.
- 커밋 메시지는 `<type>(<scope>): 설명` — [CONTRIBUTING.md](CONTRIBUTING.md).
- `--no-verify` 금지. 훅에 막히면 우회하지 말고 왜 막혔는지 본다.

## 남의 파일을 고칠 때

- **JSON 을 파싱해 재직렬화하지 않는다.** 서식이 통째로 바뀌어 실제 변경이 묻힌다(실측 222줄 vs 28줄). **문자열 치환으로 필요한 곳만** 바꾸고 `git diff --shortstat` 으로 확인한다.
- **문서 예시 값에 전역 치환 금지.** 같은 값이 자리마다 다른 뜻으로 쓰인다(예: `ground_truth` 의 「중구」는 행정 사실, `scoring_keywords` 의 「중구」는 사람들이 실제로 쓰는 말). 위치별로 문맥을 보고 고친다.

## 커밋 전 검증 루틴

```bash
export PYTHONIOENCODING=utf-8 PYTHONPATH=src

# 인물 JSON 을 건드렸으면 (필수)
python -m kopl.c5_corpus.validate --cards data/realism/cards data/corpus/v0/personas/*.json

# 코퍼스 단위 진단 (인물 JSON 만 읽는다 — 생성 글은 안 본다)
python scripts/corpus_audit.py

# c1 / c2 를 건드렸으면
python -m kopl.c1_span.test_span
python -m kopl.c2_specificity.test_engine
python -m kopl.c2_specificity.test_geo_resolution   # 지금 3/18 이 정상 — #115 구현 대기

# 계약 예시 JSON 을 바꿨으면 반드시 스키마 대조
check-jsonschema --schemafile docs/contracts/<해당>.schema.json <파일>
```

문서를 바꿨으면 **상대 링크 깊이**를 확인한다 — GitHub 상대 링크는 파일 위치 기준이다.
`README.md` 는 `../../issues/N`, `docs/*.md` 는 `../../../issues/N`, `docs/roles/*.md` 는 `../../../../issues/N`.

## 자주 틀리는 계약 포인트 (정본: docs/contracts/)

- **채점 주 지표는 partial match — `type` 일치 + IoU ≥ 0.5.** exact 는 참고치다 (label-schema §2)
- **blind 200 은 C 단독이고 교사 라벨보다 앞이다.** C 는 교사 라벨 검수를 하지 않는다 (A-data.md §5)
- 골드셋 파일명은 **인물 단위** `data/corpus/v0/gold/<persona_id>_spans.jsonl`. blind 는 `gold/blind/` 디렉터리로 가른다 — 스팬에 `blind` 필드를 만들지 않는다(§8-1 은 8필드까지)
- `record_type` post/profile 은 **`post_id`/`persona_id` 상호 배제**다 — post 레코드에 `persona_id` 를 넣으면 스키마에서 튕긴다
- 사용자 식별자는 **`user_ref`** (`^u_[0-9a-f]{8,}$`). `user_id`·`author_id` 는 계약에 없다
- 등급: 「마흔여덟」은 **explicit**(한글 수사도 explicit). 「무릎이 예전 같지 않네요」는 스팬이 아니라 `flags.gen_signal`
- 텍스트 채널 4개: `title` · `body` · `photo_caption:N`(콜론) · `profile_bio`(사용자 단위)
- **생성 금지 계열**: claude/anthropic(교사와 순환), qwen(2단 학습 대상) — `src/kopl/c5_corpus/llm.py` `BLOCKED_GENERATION`

## 절대 금지 (전문: docs/RULES-DO-NOT.md)

- `data/raw/` · `data/consented/` 접근 금지. **실데이터(실제 블로그·SNS 글) 커밋 금지** — 지인 글도, 공개 글도
- **키·토큰을 커밋하지 않는다.** ⚠️ Claude Code 게이트웨이 키는 **KISIA 가 관리하는 팀 공유 키 하나**다 — 하나가 새면 다섯 명이 전부 멈추고 재발급을 요청해야 한다. 이 저장소는 public 이고 git 히스토리는 지워도 남는다.
  - 자격증명은 `.claude/settings.local.json`(gitignore 가 막는다) 또는 `~/.claude/settings.json` 에만 둔다
  - `.claude/settings.json`(공용, 커밋됨)에는 **모델 별칭만** 넣는다. `ANTHROPIC_AUTH_TOKEN`·`ANTHROPIC_BASE_URL` 을 넣지 않는다
  - 키 값을 이슈·PR·채널·커밋 메시지에 붙여넣지 않는다. 전달은 남지 않는 경로로
- 인물·글에 학력·학교·전공·정치성향·건강·지적 수준 단서 금지 (검증기가 잡는다)
- k≤2 인 인구 칸에 가상 인물을 두지 않는다 — 실존 2명 중 하나로 오인될 수 있다

## 환경 함정 (Windows)

- 파이썬 출력이 깨지면 `PYTHONIOENCODING=utf-8` 을 빼먹은 것이다
- git-bash 의 `/tmp` 와 Windows Python 의 임시 경로가 **다르다** — 파일 전달이 조용히 실패한다. 명시적 경로를 쓴다
- bash heredoc 안에서 `\\` 가 접혀 JSON·정규식이 깨진다 — 파이썬에서 `chr(92)` 나 자리표시자 치환으로 우회한다
- `gh` 명령 인자에 백틱·괄호가 섞이면 셸이 깨진다 — 본문은 `--body-file` 로 넘긴다
- `$(...)` 는 끝 개행을 지운다

## 주간 루틴 (PM)

- 주차 마감 시 `bash scripts/tag_week.sh w0N` — compare 링크가 캡처보다 강한 증빙이다
- 주간활동보고서 글자 수: **활동 내용 650자 · 멘토링 400자 미만 (공백 포함)** — 넘치면 잘려서 제출된다
- 제출물 원고는 저장소에 올리지 않는다 — PM 로컬에서 관리
