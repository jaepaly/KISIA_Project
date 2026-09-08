# 핸드오프 — 원티드 AI Championship 2026 데모 (2026-09-08 새벽 기준)

> 세션이 끊겨도 여기서 이어간다. 상세 경위는 [LOG.md](LOG.md), 화면·수치·통합 계획은 [README.md](README.md).
> 브랜치 `D/demo/championship-spike` · **로컬 전용, push·PR 금지** · PM 단독 · 팀 로드맵 영향 0.

## 일정

| 날짜 | 무엇 |
|---|---|
| ~9/12 | 남은 다듬기(아래) · KISIA AWS 계정 대기 |
| 9/13~ (다음 주) | **AWS 배포** — 두 프로세스 + 환경변수. 접수용 링크 확보 |
| **9/18** | **접수 마감** (배포 링크 제출) |
| 9/20 | 제출 마감 |
| ~10/17 | 본 프로젝트 자원 갈아끼우기 (B 1단 · C 기여도 · D 2단) — README 「통합 계획」 |
| **10/17** | 데모데이 |

## 지금 상태 — 링크로 낼 수 있는 기준선

```bash
pip install -r apps/sns/requirements.txt -r apps/demo/requirements.txt
export PYTHONIOENCODING=utf-8 PYTHONPATH=src
python apps/demo/seed.py --reset       # 5명 + 체험 계정(GUEST)
python apps/demo/app.py                # 파도풀 API  :8000
python apps/demo/sns_ext.py            # 우리뜰      :3000  ← 심사위원이 여는 곳
python -m pytest apps/demo/test_demo.py apps/sns/test_export.py -q    # 22 passed
python apps/demo/probe.py --diff       # 5명 k 회귀 — 「변화 없음」이어야 정상
```

- 첫 화면(`/`)에 **첫 방문 카드** + 「▶ 3분 체험 시작」 → **9단계 투어**가 시연 순서대로 데려간다 (마당일기 → 내 글 점검 → 421 →
  깔때기 → 위치태그 끄기 → 421→111,069 → 글쓰기 → 예문·체험 계정·점검 → 색칠된 표현). 발표 대본이 곧 이 9단계.
- 정본 수치(`probe.baseline.json`, 위치태그 ON/OFF): **D05 421/111,069** · D01 36,061/434,408 · E20 1,231/17,433 · C02 899/14,574 ·
  **D06 5/199,109**. (D11·D17 은 9/8 에 E20·C02 로 교체 — 시골 노년 중복·태그 효과 약함.) D05 가 메인, D06 이 두 번째 시연감.
- 리라이트: 색칠된 표현 클릭 → 팝오버 — **넓히기 사다리**(진영읍 → 김해시 → 경남, 단마다 실제 k) → 지우기 → **그대로 두기**.
  바닥이 다른 글이면 「⤷ 다른 글 N편의 「기흥」이 남아」 + 「그것까지 치우면 → k」 + 태그 끄기 버튼.
- 외부 LLM 은 Claude API, 기본 꺼짐. 켜면 리라이트 후보가 실제 생성으로 바뀐다 (`DEMO_EXTERNAL_REWRITE=true` + `ANTHROPIC_API_KEY`).
- 1단 탐지는 규칙 스탑갭. 화면에 명시. `C1_MODEL_PATH` 로 B 모델 교체 가능.

## 오늘(9/7~8) 커밋 — 최신이 위

```
93c553e docs  통합 계획 표 + probe.py 회귀
98164c9 feat  첫 방문 카드 + 9단계 투어 · 형광 기본 ON · 툴팁
d7bf19b feat  체험 계정(글 0편) 기본 작성자 + 기존 글 바닥 안내줄
030f634 fix   바닥 근거를 «같은 값 묶음» 으로 — 치워도 안 바뀌면 상자 안 냄
b86aae4 feat  「그것까지 치우면 → N명」 + 팝오버에서 위치태그 끄기
1fa70de feat  넓혀도 k 안 변하는 이유 「⤷ 다른 글의 …」
f70abdd feat  넓히기 사다리(단마다 실제 k) + 그대로 두기
c9e950e docs  LOG.md 시작
003d84a fix   심사위원 문장 8개 오탐 4부류 (열·둘째날·여행 글·손님이·9호선 후보)
256e8d6 fix   연속 지명 합치기 · 동명 읍면동은 맥락 없이 확정 안 함
2f88c3b feat  에디터 리라이트 팝오버 + 조사 맞춤(fit_particle)
343e568 feat  2단 레이아웃 · 모바일 탭바 · urittle.js 효과 · 🛟→🌊
9aecf28 refactor 지명 정규식 하나로 — 스캔 6s → 0.7s
d83004c fix   지명 오탐 + 구 있는 시 인구 0 — 4명이 k=1 이던 원인
913de9c feat  외부 리라이트 OpenAI → Claude API
```

## 다음에 할 일 (우선순위)

1. **배포** (AWS 오면 즉시) — 한 인스턴스, `PADOPOOL_URL`·`SNS_URL`·`DEMO_EXTERNAL_REWRITE=true`·`ANTHROPIC_API_KEY`.
   `data/interim/sns.db` 는 배포 뒤 `seed.py --reset` 으로 만든다. 배포 링크로 투어 9단계를 한 번 끝까지 돌려 본다 (휴대폰도).
2. **Claude 켠 뒤 리라이트 품질 재점검** — 규칙 후보가 어색하던 자리(월급·시급·연금 명사 하나짜리, 「면사무소 앞에서…」 긴 절).
   `LOG 9/7` 의 심사위원 문장 8개를 다시 돌린다.
3. **투어 문구·순서 손보기** — 사용자가 직접 돌려 본 뒤 어색한 말풍선 수정. `urittle.js` 의 `TOUR` 배열.
4. **시연 대본에 D06 장면** — 「위치태그 하나가 20만 → 5명」. README 표 참고.
5. 첫 `git merge main` (다음 주) → `probe.py --diff` → 바뀐 숫자 README·LOG 에. B 진행 보고 `C1_MODEL_PATH` 시도.
6. 접수 서류(제출 폼 텍스트) — 첫 방문 카드 문구 + README 「경계」 절이 재료.

## 알려진 것 / 안 건드리는 것

- 기존 글이 더 좁은 곳을 이미 말하면 사다리가 평평하다(D01 3,136). 맞는 계산이고 안내줄이 뜬다. 시연은 D05·체험 계정으로.
- 법정동(역삼동 등)은 사전에 없어 안 잡힌다 — 본 프로젝트 C 논점 (#115).
- 못 잡는 표현은 모델 몫. **잘못 잡는** 것만 고친다(클래스 단위). 개별 표현 규칙 추가 금지.
- B 모델이 오면 합치기·여행·시제·타인 귀속 후처리를 모델 경로에도 붙여야 한다 (지금은 규칙 경로에만).
- 자동화 브라우저(숨김 탭)에선 애니메이션이 멈춘 것처럼 보인다 — 실제 창은 정상. 카운트업은 `document.hidden` 이면 최종값.
- 루트 `README.md`(팀 공용)는 안 건드린다. 데모 문서는 전부 `apps/demo/` 안.

## 문서 위치

- `apps/demo/README.md` — 띄우기 · 시연 장면 · 경계 · 실측표 · **통합 계획** · 화면 구성 · 파일
- `apps/demo/LOG.md` — 날짜별 결정·발견(**→ 본 프로젝트** 표시)·남은 것
- `apps/demo/probe.baseline.json` — 화면 숫자의 정본
- `docs/mentor-log.md` MF-011 — 대회 참가 결정 경위 (팀 공용, 수정 금지)
