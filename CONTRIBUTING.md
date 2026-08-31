# 협업 규칙

> 처음이면 먼저: `bash scripts/bootstrap.sh` → [docs/RULES-DO-NOT.md](docs/RULES-DO-NOT.md) → [docs/roles/](docs/roles/) 내 자리 매뉴얼

---

## 0. 왜 규칙이 있나

이 프로젝트는 **매주 활동보고서를 제출하고, 8주차에 진행률을, 10주차에 달성도를 숫자로 써야 한다.** 그 원자료가 전부 git에서 나온다.

> **외울 한 문장: 그 주에 머지된 PR이 없으면 주간활동보고서의 증빙이 빈다.**

규칙을 늘리는 대신 이 문장 하나를 지킨다.

---

## 1. 시작하기

```bash
git clone https://github.com/jaepaly/KISIA_Project.git
cd KISIA_Project
bash scripts/bootstrap.sh
```

`bootstrap.sh` 가 하는 일: 훅 활성화 · 커밋 신원 확인 · `.env` 생성.

**커밋 이름·메일을 설정했으면 PM에게 알린다.** `.mailmap` 에 등록해야 기여 집계가 한 사람으로 잡힌다. 등록 안 하면 GitHub 웹 편집·로컬·학교 계정이 뒤섞여 **한 사람이 3~4명으로 갈라진다.**

---

## 2. 브랜치

```
<역할>/<컴포넌트>/<슬러그>

A/c5/persona-gen-v1
B/c1/koelectra-finetune
E/c7/sns-scaffold
PM/submit/w02-plan
```

- `main` 단일 브랜치, **직접 push 금지**
- 브랜치 수명 **5일 이내**. 길어지면 쪼갠다

---

## 3. 커밋

```
<type>(<scope>): 주간보고에 그대로 실릴 문장

본문에 "무엇이 달라졌는지"를 숫자와 함께
```

| type | 쓰임 |
|---|---|
| `feat` | 기능 추가 |
| `fix` | 버그 수정 |
| `data` | 코퍼스·라벨·사전 변경 |
| **`exp`** | **실험 실행·결과** — 이 프로젝트의 산출물은 코드보다 실험 결과다 |
| `docs` | 문서 |
| `chore` | 설정·빌드 |
| `refactor` | 리팩터링 |
| `test` | 테스트 |
| `submit` | KISIA 제출물 |

`scope` 는 `c1`~`c7` 컴포넌트 또는 자유.

```
exp(c1): KoELECTRA-base 파인튜닝 1차 — 스팬 F1 명시 .84 / 암묵 .58 [MF-012]
data(c5): 골드셋 282 → 610 스팬, blind 200 포함
submit: W01 주제선정서
```

**`exp` 를 따로 두는 이유**: `git log --grep='^exp'` 한 줄이 8주차 「학습·테스트 진행 내용」이 된다.

**`Co-authored-by:` 는 필수다.** 페어 작업이 한 사람으로만 잡히면 「팀원별 구분」이 실제와 어긋난다.

```
Co-authored-by: 이름 <메일>
```

**커밋 분포도 증빙이다.** 제출 전날 40커밋은 증빙이 아니라 반증이다. **주 3회 이상 분산 푸시.**

---

## 4. 리뷰

| 경로 | 승인 | 왜 |
|---|---|---|
| `docs/contracts/`, `data/dict/` | **2명** | 여러 역할이 함께 쓰는 계약. 혼자 못 바꾼다 |
| `submissions/` | **PM 단독** | 제출물 편집권 독점 (OT 체크 5번을 구조로 강제) |
| `src/kopl/c*/` 자기 컴포넌트 | 1명 | |
| `docs/`, `experiments/` | 셀프머지 허용 | |

- **24시간 무응답 시 PM 승인 머지** — 리뷰 대기로 일정이 밀리지 않게
- **Squash merge 기본**

### ⚠️ 소유자가 한 명뿐인 경로는 리뷰어가 **자동으로 안 붙는다**

CODEOWNERS 에 **여러 명**이 걸린 경로(`docs/contracts/`, `data/dict/`)는 PR 을 열면 GitHub 이 알아서 리뷰어를 요청한다. 그런데 catch-all `*  @jaepaly` 에만 걸리는 경로는 **소유자가 PM 한 명**이고, GitHub 은 **작성자 본인에게는 리뷰를 요청하지 않는다.** 그래서 요청이 하나도 안 생긴다.

그러면 대시보드에 「리뷰어를 지정해주세요」로 뜬다. 버그가 아니라 맞는 안내다.

```bash
gh pr edit <번호> --add-reviewer <계정>
```

`docs/mentor-log.md` 처럼 **PM 기록**이라 리뷰가 필요 없는 문서도 있다. 그럴 때는 지정하지 않고 그대로 머지해도 된다 — 판단해서 쓴다.

> CODEOWNERS 가 **걸린** 경로에는 `--reviewer` 를 쓰지 않는다(중복 요청이 되어 승인 하나가 하나만 지운다). **안 걸린** 경로에만 쓴다.

### ⚠️ 답이 필요하면 리뷰를 **재요청**한다. 코멘트만으로는 부족하다

리뷰를 한 번 내면 **GitHub 이 그 사람을 요청 목록에서 뺀다.** 그래서 그 뒤에 코멘트로 질문을 남기면

- 알림은 간다 — 알림함에 쌓이는 **흐름**이다
- **대시보드에는 안 뜬다** — 대시보드는 「지금 누구 차례인가」라는 **상태**를 본다

**그 사람 화면에서 그 PR 이 사라진 상태다.** 답을 기다리는 줄 모른다.

**PR 페이지 오른쪽 Reviewers 옆의 🔄(재요청) 버튼**을 누르면 다시 요청 목록에 들어가고, 대시보드의 「내 승인을 기다리는 PR」에 다시 뜬다.

```bash
# 명령으로 하려면
gh api --method POST repos/jaepaly/KISIA_Project/pulls/<번호>/requested_reviewers   -f "reviewers[]=<계정>"
```

> **왜 코드로 못 고치나** — 「내가 질문했고 답을 기다리는 중」은 기계가 판별할 수 없다. 코멘트가 질문인지 감사 인사인지 구분되지 않는다. **대시보드는 상태를 보고 대화는 알림이 맡는다.** 그 경계를 사람이 재요청으로 이어준다.

⚠️ **재촉이 아니다.** 재요청과 함께 「급하지 않다 · 내일 보셔도 된다」를 코멘트로 같이 남긴다. 상태를 되살리는 것과 재촉하는 것은 다르다.

⚠️ **CODEOWNERS 가 걸린 경로에는 `gh pr create --reviewer` 를 쓰지 않는다.** 자동 요청과 겹쳐 같은 사람이 두 번 들어가고, 승인해도 하나만 소멸해 목록에 남는다 (실측 2026-08-27, #63).

---

## 5. 이슈와 라벨

라벨: `role/A~E` `comp/c1~c7` `week/W01~W12` `type/exp` `type/data` `type/deliverable` `mentor/feedback` `blocked` `contract`

생성: `bash scripts/setup_labels.sh` (gh CLI 필요)

> ⭐ **`mentor/feedback` 이 핵심이다.** 멘토 발언을 이슈로 등록하고 반영 PR에서 `Closes #NN` 으로 닫으면 **close 자체가 반영 증빙**이 되고 시각·커밋 링크까지 남는다. Discord는 스크롤이 밀려 증빙이 못 된다.
>
> 등록 후 [docs/mentor-log.md](docs/mentor-log.md) 원장에도 같은 `[MF-NNN]` 으로 추가한다.

---

## 6. 매주 반복

| 요일 | 누가 | 무엇 |
|---|---|---|
| **월 10:00** | 전원 | 킥오프 30분 — ①지난주 멘토 피드백 미완료 항목 ②이번주 목표 배정 |
| 화 | 전원 | 비동기 블로커 체크. **진척 보고 금지, 막힌 것만** |
| **수 23:59** | 팀원 5인 | 개별 보고 5줄 제출 (아래) |
| 목 오전~오후 | PM | 취합·편집 → 초안 v0. **부실한 원고는 대필하지 말고 반려** |
| **목 20:00** | 전원+멘토 | **정기 멘토링** (W1 확정). **기록자 1명 지정** (PM 아님 — PM은 진행) |
| 금 오전 | PM·담당자 | 피드백 반영 → 최종본 |
| 금 마감 전 | PM | 서명 → 제출 → **제출 화면 캡처 보관** |
| 금 마감 후 | PM | `bash scripts/weekly_report.sh` · `bash scripts/tag_week.sh wNN` |

**정기 멘토링은 목요일 20:00 고정이다** — W1 멘토링(2026-08-20)에서 합의했고, 제출된 1주차 활동보고서 「멘토링 내용」에 기재되어 멘토 확인까지 받았다. 변경하려면 멘토 합의가 다시 필요하다.

**개별 보고 마감이 수요일인 이유** — 멘토링이 목요일 저녁이므로 그 전에 취합이 끝나야 멘토에게 보여줄 초안이 있다. 산출물 주차든 아니든 **모든 주차가 수요일 마감**이며, 예외 규칙은 없다.

**산출물 주차(W2·W4·W8·W10·W11·W12)는 2회전을 전제로 한다.** 양식의 「멘토 검토 의견」이 피드백뿐 아니라 *반영 내용*까지 요구하므로 한 번의 멘토링으로는 부족하다. **전주 목요일 멘토링에 초안을 미리 올리고, 당주 목요일에 최종 검토를 받는다.**

### 개별 보고 — 이 5줄 고정 (자유서술 금지)

```
1. 이번주 내 목표(월요일에 배정된 것):
2. 실제로 한 일:
3. 달라진 것 (before → after, 숫자 포함):
4. 증빙 링크 (커밋/PR/이슈/캡처 파일명):
5. 막힌 것 + 필요한 지원 (없으면 "없음"):
```

**부실한 원고는 PM이 대필하지 않고 반려한다.**

---

## 7. 증빙 3종 (매주 고정)

1. `docs/evidence/W-NN/git-summary.md` — `scripts/weekly_report.sh` 가 생성
2. Contributors 그래프 캡처 — **기간 지정, 날짜가 보이게**
3. Projects 「이번주」 뷰 캡처 — Group by Role

파일명: `W03_B_학습로그_20260904.png`

**주차 태그가 가장 강한 증빙이다.** 제출 직후 `bash scripts/tag_week.sh w03` 을 돌리면 compare URL이 나온다. 심사자가 클릭 한 번으로 그 주에 바뀐 전부와 커밋한 사람을 본다 — 캡처보다 강하고 3초 걸린다.

---

## 8. 실험 기록

```
experiments/<exp-id>/
├─ README.md          무엇을 왜 재는가
├─ config.yaml        재현에 필요한 설정
└─ results/
   └─ metrics.json    ← 이것만 커밋. 원본 로그·플롯은 제외
```

**모든 성능 수치에 측정일 · 데이터 버전 · 모델 버전을 붙인다.** 없으면 10주 뒤에 그 숫자가 무엇이었는지 복원할 수 없다.

---

## 8-1. `src/kopl/` 에 새 파일을 만들 때 — import 형태 ⚠️

**같은 결함이 2026-08-31 하루에 세 번 났다** ([#126](../../pull/126) · [#134](../../pull/134) · [#138](../../pull/138)).

```
$ python -m kopl.c5_corpus.generate --persona ... --provider echo
ModuleNotFoundError: No module named 'prompts'
```

`-m` 으로 돌리면 `sys.path[0]` 이 **저장소 루트**라, 같은 디렉터리의 형제 모듈을 평면 import 로 못 찾는다. 반대로 파일을 직접(`python generate.py`) 돌리면 패키지 문맥이 없어 상대 import 가 죽는다. **우리는 둘 다 쓴다** — README 는 `-m`, 각 파일 docstring 은 직접 실행이다.

**그래서 형제 모듈은 이렇게 부른다.**

```python
try:
    from . import prompts
    from .llm import LLMClient, LLMError
except ImportError:      # python <file>.py 로 직접 실행할 때
    import prompts
    from llm import LLMClient, LLMError
```

**확인은 두 경로 다 한다.**

```bash
export PYTHONIOENCODING=utf-8
python -m kopl.<pkg>.<module> --help
cd src/kopl/<pkg> && python <module>.py --help
```

> 표준 라이브러리와 외부 패키지는 그냥 `import` 한다. 이 규칙은 **같은 디렉터리의 형제 모듈**에만 해당한다.

---

## 9. 커밋하면 안 되는 것

[docs/RULES-DO-NOT.md](docs/RULES-DO-NOT.md) 를 읽는다. 요약하면:

- 실데이터 (`data/raw/`, `data/consented/`)
- 키·토큰 (`.env`, `*.pem`, `*.key`)
- 모델 가중치 (`models/registry.md` 에 포인터만)
- **서명·날인된 제출물** — 팀원 실명과 자필 서명이 히스토리에 영구히 남는다
- 5MB 초과 파일

훅과 CI가 막지만, **막히면 우회하지 말고 왜 막혔는지 본다.** `--no-verify` 를 쓸 일이 있으면 PM에게 먼저 묻는다.

---

## 10. 용어

표기가 문서마다 흔들리면 17~18개 문서에 반복 기입될 때 전부 어긋난다. [docs/glossary.md](docs/glossary.md) 를 따른다.
