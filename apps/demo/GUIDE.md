# 파도풀 데모 — 처음 보는 사람을 위한 안내 (E 용)

> 원티드 AI Championship 2026 에 낼 데모다. **정본 아님** — 정본은 E 의 W5 분석 웹앱이고, 이건 PM 이 대회용으로 먼저 만든 스파이크다.
> 살펴보고 배우고, 고칠 점이 보이면 고치면 된다. 채택할지 말지는 E 가 정한다. 본 프로젝트 일정이 먼저다.
>
> 문서 순서: 이 문서 → [README.md](README.md)(경계·수치·통합 계획) → [HANDOFF.md](HANDOFF.md)(지금 상태·다음 할 일) → [LOG.md](LOG.md)(왜 그렇게 했나).

## 1. 띄우기 — 10분

전제: **Python 3.11** ([docs/setup-python.md](../../docs/setup-python.md) 그대로). 저장소 루트에서, 브랜치 `D/demo/championship-spike`.

```bash
git fetch && git switch D/demo/championship-spike
pip install -r apps/sns/requirements.txt -r apps/demo/requirements.txt

# git-bash
export PYTHONIOENCODING=utf-8 PYTHONPATH=src
# PowerShell 이면:  $env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH='src'

python apps/demo/seed.py --reset          # 코퍼스 인물 5명 + 체험 계정 → data/interim/sns.db (서버가 떠 있어도 됨)
python apps/demo/app.py                   # 터미널 1 — 파도풀 API      http://localhost:8000
python apps/demo/sns_ext.py               # 터미널 2 — 우리뜰(플랫폼)  http://localhost:3000  ← 여기를 연다
```

정상 확인:
```bash
python -m pytest apps/demo/test_demo.py apps/sns/test_export.py -q   # 22 passed
python apps/demo/probe.py --diff                                     # 「변화 없음」
```

막히면: `ModuleNotFoundError: kopl` → `PYTHONPATH=src` 빠짐 · 한글 깨짐 → `PYTHONIOENCODING=utf-8` · 3000 포트 사용 중 → `SNS_PORT=3001`.

## 2. 무엇을 보면 좋나 — 15분

1. **http://localhost:3000/ 에서 「▶ 3분 체험 시작」** 을 누르고 11단계를 끝까지 따라간다. 이게 심사위원이 보는 경로이자 발표 대본이다.
2. 다시 **마당일기 → 내 글 점검** 으로 가서 천천히 본다 — 요약(421명) → 어떻게 좁혀지나(깔때기 줄에 마우스를 올리면 근거 문장이 켜진다) → 근거 → 조치. 위치태그를 끄고 421 → 111,069 를 본다.
3. **느린 기록** 계정도 본다 — 위치태그 하나가 199,109 → 5명. 두 번째 시연감.
4. **글쓰기** 에서 체험 계정으로 아무 글이나 쓰고 「파도풀로 점검」 → 색칠된 표현을 눌러 팝오버(넓히기 사다리 · 그대로 두기)를 본다.
5. 휴대폰이나 창을 640px 이하로 줄여 본다 — 하단 탭바로 바뀐다.

보면서 **어색한 것을 적어 두면** 그게 곧 할 일이다. 문구·순서·색·설명 부족·"이건 왜 이렇지" 전부.

## 3. 코드 지도 — 어디를 고치면 무엇이 바뀌나

```
apps/demo/
  sns_ext.py              우리뜰 실행기. apps/sns 를 import 해 화면·라우트를 덧씌운다 (apps/sns 는 안 고친다)
  templates/sns_ext/      우리뜰 화면 전부 — base(셸·탭바) · _rail(오른쪽 레일) · list · profile_ext · post_ext · new_ext(에디터+팝오버) · edit_post · check(점검)
  static/urittle.css      우리뜰 디자인 (종이 톤). 반응형 분기 1023/640px
  static/urittle.js       효과 — 리빌·카운트업·링·깔때기 막대·hover 연결·레일 위젯·「더 보기」·점검 탭·근거 접기·후보 칩·투어(TOUR 배열)·처음부터(/demo/reset)
  app.py                  파도풀 API (:8000) — /api/scan · /api/check. DB 없음, 저장 없음
  engine/detect.py        1단 탐지 — 규칙 스탑갭 (B 모델이 오면 C1_MODEL_PATH 로 교체)
  engine/specificity.py   깔때기 — C 의 kopl.c2_specificity 위에서 k
  engine/recommend.py     조치 3종 · 리라이트 후보 · 넓히기 사다리 · 조사 맞춤
  seed.py                 코퍼스 → sns.db 시딩 (E 의 정식 스크립트가 나오면 이걸로 교체)
  data/comments.json      글별 댓글 (손으로 씀) · probe.baseline.json  화면 숫자의 정본
```

- 문구·레이아웃·효과 → `templates/sns_ext/*` · `urittle.css` · `urittle.js`. 서버 재시작 필요(템플릿 캐시). 정적 파일은 새로고침만.
- 투어 문구·순서 → `urittle.js` 의 `TOUR` 배열.
- 숫자가 바뀌는 수정(engine/) → 반드시 `probe.py --diff` 로 어느 인물의 k 가 왜 바뀌었는지 설명할 수 있어야 한다.

## 4. 깨지면 안 되는 것

1. `pytest apps/demo/test_demo.py apps/sns/test_export.py` **22 passed** 와 `probe.py --diff` **변화 없음** — 커밋 전에.
2. **경계** — 파도풀(app.py)은 저장하지 않고 우리뜰의 글을 바꾸지 않는다. 비공개·위치태그·본문 수정 버튼은 전부 우리뜰(sns_ext) 라우트다. 테스트가 이걸 검사한다.
3. **규칙 탐지기는 «클래스» 만 고친다.** 「이 단어도 잡아야 하는데」 식의 개별 표현 추가는 하지 않는다 — 9/28 KoELECTRA 로 통째 교체된다. *잘못 잡는* 것(오탐)만, 그것도 한 부류를 닫는 규칙으로.
4. `apps/sns/` 는 E 소유다 — 고쳐도 되지만, 고치면 데모가 아니라 본 프로젝트 변경이니 main 으로 가는 PR 로.
5. API 키·실명·실데이터는 커밋하지 않는다. 인물·글·댓글은 전부 합성이다.

## 5. 시작하기 좋은 일 (순서 없음, 시한 없음)

- 투어 11단계 말풍선 문구 다듬기 — 처음 보는 사람 눈으로
- 실제 휴대폰으로 열어 보고 깨지는 곳 기록
- `seed.py` 를 E 의 정식 시딩 스크립트로 교체 (W4 과제와 겹친다 — 체험 계정 GUEST 만 남기면 된다)
- `sns_ext.py` 가 덧씌운 것(위치태그 끄기 · 본문 수정 · 에디터 점검)을 `apps/sns` 정식 기능으로 옮길지 판단 — 통합 계획 표의 E 줄
- `DEMO_EXTERNAL_REWRITE=true` + `ANTHROPIC_API_KEY` 로 Claude 리라이트를 켜고 후보 품질 훑기 (키는 각자 환경변수로)
- 심사자 문장 8개(LOG 9/7)를 에디터에 넣어 보고 어색한 것 적기

## 6. 작업 방식

- 작은 수정은 `D/demo/championship-spike` 에 직접 커밋. 큰 변경은 `E/demo/<이름>` 브랜치 → **데모 브랜치로 PR** (main 아님). main 으로는 대회 뒤에 정리해서 올린다.
- 커밋 메시지는 팀 규칙 그대로(`feat(demo): …`). 훅이 검사한다.
- 한 일·발견·결정은 **LOG.md 에 날짜와 이름을 달아** 적는다. 본 프로젝트로 가져갈 발견은 「→ 본 프로젝트(파트)」 표시.
- 숫자를 바꿨으면 `probe.py --save` 로 baseline 갱신하고 README 실측표도 맞춘다.
- 막히거나 판단이 필요하면 이슈나 DM. 혼자 오래 붙들 필요 없다.
