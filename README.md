# 파도풀 — 공개 게시글 누적·결합에 따른 재식별 위험 자가진단 및 보호조치 추천 시스템

KISIA 2026 AI 보안기술개발 · 개인정보 트랙 3팀 · 2026-08-17 ~ 11-06 (12주) · 담당 멘토 권영길

> 흩어진 글이 쌓이고 서로 결합하면서 발생하는 재식별 위험을 진단하고,
> **가장 적은 부담으로 되돌릴 수 있는 조치를 추천**한다. 탐지는 **외부 전송 없이 이용자 기기에서** 수행한다.

---

> ## 📌 이 문서는 **이번 주에 할 일**만 다룬다
>
> | 찾는 것 | 문서 |
> |---|---|
> | **이번 주 내가 뭘 해야 하나** | **여기 (아래)** |
> | 내 역할 전체 (12주) | [docs/roles/](docs/roles/) |
> | 프로젝트가 뭔지 | [docs/overview.md](docs/overview.md) |
> | 계획 전문 | [docs/plan.md](docs/plan.md) |
> | 주차별 일정·게이트 | [docs/roadmap.md](docs/roadmap.md) |
> | 협업 규칙 (브랜치·커밋·리뷰) | [CONTRIBUTING.md](CONTRIBUTING.md) |
> | **골드셋 형식** | [docs/contracts/label-schema.md](docs/contracts/label-schema.md) §8 · §9 |
> | **절대 하면 안 되는 것** | [docs/RULES-DO-NOT.md](docs/RULES-DO-NOT.md) |
> | **팀 대시보드 (로컬)** | `python scripts/open_dashboard.py` — gh CLI 필요 ([설치](https://cli.github.com/)) · `gh auth login` 최초 1회 |

---

## 지금 상태

**W5 완전 종료, W6 진입 (추석 연휴 9/20~22)** — [compare/w04...w05](../../compare/w04...w05)

| 항목 | W5 끝 |
|---|---|
| 코퍼스 | **v1 동결** ✅ 115명 3,092편 · d4cf8cb · 9/9 |
| 골드셋 검수 | **417편 587스팬** ✅ + blind 159편 267스팬 (#229 · 9/14) |
| IAA | **2차 완료 ✅** overall 50.0% (explicit 51.9% · implicit 44.4% · inferential 20.0% · 9/17) |
| 1단 탐지 v1 | **koelectra-v1 확정 ✅** checkpoint-epoch-10 · test F1 0.2940 · p95 276ms (#263 · 9/18) |
| 2단 QLoRA | **3ep adapter v1 확정 ✅** dev_loss 0.0044 · verdict 90% (#264 · 9/18) |
| 기여도 엔진 | **LOO v1 ✅** loo.py · CI pass (#251 · 9/16) · `risk_total` PR #268 수정 대기 |
| 분석 웹앱 | **3화면 연결 ✅** ENGINE_MODE=mock 엔드투엔드 에러 없음 (#254 · 9/17) |
| 지명 사전 | UNKNOWN 18→2 ✅ · 픽스처 19/19 (#218) |
| 가명화·복원 | `anonymize()` + `restore()` ✅ 라운드트립 15종 (#243 · 9/14) |
| 설계서 | ✅ 제출 완료 9/10 |
| `w04` 태그 | ✅ 9/11 · `w05` 태그 — C 증류 타깃 PR 머지 후 |

| 역할 | 담당 | **이번 주 핵심** |
|---|---|---|
| **[A · 데이터 리드](docs/roles/A-data.md)** | 이은선 | 문서 정비 (decisions.md 최신화) — 비동기 |
| **[B · 1단 탐지](docs/roles/B-detector.md)** | 최진필 | E real.py 연결 준비 — 체크포인트·임계값 공유 |
| **[C · 특정성·누적](docs/roles/C-specificity.md)** | 신정현 | **증류 타깃 세트** — PR #268 clamp + span_to_condition() + gen_contribution_targets.py |
| **[D · 2단 추론·조치](docs/roles/D-stage2.md)** | 박재현 (PM) | 월 KISIA 줌 발표 · w05 태그 |
| **[E · 시스템·컴플라이언스](docs/roles/E-system.md)** | 이지희 | **활동 메타 필드** — 공개/비공개 토글 |

---

# W6 (9/21~9/27) — 각자 할 일

**제출물**: 주간활동보고서 (외부)
**단계**: **M2-c** · 근무일 3일 🔴 (추석 연휴 9/20~22 포함)

> ## 이번 주 한 문장 — **C가 증류 타깃을 완성해 w05 태그를 달고, E가 활동 메타 필드를 착수한다.**
>
> 로드맵 §3:
>
> W6은 추석 연휴(9/20~22)로 실 근무일이 수·목·금 3일뿐이다. B·D 학습 잡은 이미 확정(불필요)이므로 비동기 처리. 핵심은 C가 #261 결정을 구현해 증류 타깃을 완성하는 것, E가 W9 시연 필수 조건인 공개/비공개 토글을 착수하는 것이다. 내부 마감은 수요일로 당긴다.

---

## 0. 전원 공통 — 월 9/21 11:15 KISIA 줌 주간보고회

D(PM)이 W5 성과를 발표한다. 개인 5줄 보고를 **일요일 9/20 저녁까지** PM에게 보낸다.

```
1. 이번 주 내 목표:
2. 실제로 한 일:
3. 달라진 것 (before → after, 숫자):
4. 증빙 링크:
5. 막힌 것 + 필요한 지원:
```

**D가 발표할 W5 요약:**

| 역할 | W5 핵심 성과 |
|---|---|
| B | koelectra-v1 확정 · test F1 0.2940 · p95 276ms |
| D | Qwen3 3ep adapter v1 확정 · verdict 90% |
| C | LOO 기여도 엔진 v1 완성 · IAA 2차 50.0% |
| E | 분석 웹앱 3화면 연결 · 수동 업로드 경로 |
| A | 라벨 품질관리 · 네거티브 보강 · label-schema §4-1 나이 어미 경고 |

---

## W5 이월 항목

| 항목 | 담당 | 상태 |
|---|---|---|
| PR #268 `risk_total` clamp 수정 | C | **수정 대기** (CHANGES_REQUESTED 9/19) |
| #261 span_to_condition() 구현 | C | **W6 핵심** — clues.py → C3 어댑터 → 증류 타깃 PR |
| w05 태그 | D(PM) | C 증류 타깃 PR 머지 후 |
| 활동 메타 필드 | E | W5 스트레치 → **W6 본과제**로 격상 |

---

## 전원 공통 — 주간보고서 (수 9/24 23:59)

근무일이 3일뿐이라 내부 마감을 수요일로 당긴다. 원고는 드라이브 — PM(재현)에게 **수 23:59** 까지.

```
1. 이번 주 내 목표:
2. 실제로 한 일:
3. 달라진 것 (before → after, 숫자):
4. 증빙 링크:
5. 막힌 것 + 필요한 지원:
```

---

## 전원 공통 — 로컬 대시보드 실행

저장소가 9/14 비공개 전환 이후 GitHub Pages가 중단됐다. **gh CLI 스냅샷 기반**으로 로컬에서 동일한 대시보드를 열 수 있다.

### 1회 설정

```bash
# 1) gh CLI 설치 (없는 경우만)
#    Windows: winget install GitHub.cli
#    macOS:   brew install gh

# 2) GitHub 인증 (최초 1회)
gh auth login
# → GitHub.com / HTTPS / 브라우저 로그인 선택 후 완료
```

### 대시보드 열기

```bash
# 저장소 루트에서
python scripts/open_dashboard.py
```

`site/index.html`이 생성되고 브라우저가 자동으로 열린다.

> ⚠️ 브라우저에서 새로고침(F5)해도 데이터가 바뀌지 않는다. 최신 현황을 보려면 스크립트를 다시 실행해야 한다.

---

## A · 이은선 — 문서 정비 (비동기)

> 전체 매뉴얼 [docs/roles/A-data.md](docs/roles/A-data.md)

W6 A 역할은 연휴 비동기. 시간이 날 때 아래를 처리한다.

### decisions.md 최신화

W5에서 확정된 결정을 [docs/decisions.md](docs/decisions.md)에 추가한다.

- #261 스팬→condition 변환 규칙 (resolution 산정·subject·REL 처리) — 9/19
- #263 koelectra-v1 체크포인트 확정 (checkpoint-epoch-10·임계값 0.7)
- #264 Qwen3 3ep adapter v1 확정 (verdict 90%)

```bash
# 현재 마지막 DEC 번호 확인
grep "DEC-0" docs/decisions.md | tail -5
```

### (선택) howto/a-data.md — W7 대비

W7 A 역할: "exp8 축약판 지원". 필요한 라벨 추가 작업이 있는지 미리 파악한다.

### 완료 기준

- [ ] decisions.md — W5 결정 3건 추가

---

## B · 최진필 — E 실 엔진 연결 준비 (비동기)

> 전체 매뉴얼 [docs/roles/B-detector.md](docs/roles/B-detector.md) · [howto/b-finetune.md](docs/roles/howto/b-finetune.md)

### 현황

v1 체크포인트 확정 완료 (#263 · 9/18):
- 경로: `experiments/exp06-finetune/runs/v1_lr5e-5/checkpoint-epoch-10`
- 임계값: 0.7 · 내부 eval F1 0.4839 · test F1 0.2940 · p95 276ms
- 학습 잡 비동기 → **불필요 확정** (1ep=16.57초 · #262)

### E에게 infer.py 사용법 공유

E가 W6~7에 `engines/real.py`를 구현할 때 필요한 정보를 이슈 코멘트로 남긴다.

```
공유할 것:
- 체크포인트 경로: experiments/exp06-finetune/runs/v1_lr5e-5/checkpoint-epoch-10
- 임계값: 0.7
- 입력/출력 계약: docs/contracts/span.schema.json
- 예시 호출:
    python experiments/exp06-finetune/infer.py \
      --post '{"post_id":"test","body":"신갈저수지 조황입니다"}' \
      --threshold 0.7
```

W6~7 E real.py 연결 시 run 파일(체크포인트 외 학습 메타) 필요 여부는 공유 방법과 함께 결정한다.

### 완료 기준

- [ ] E에게 체크포인트 경로·임계값·infer.py 사용법 공유 (이슈 코멘트)

---

## C · 신정현 — 증류 타깃 세트

> 전체 매뉴얼 [docs/roles/C-specificity.md](docs/roles/C-specificity.md) · [howto/c-engine.md](docs/roles/howto/c-engine.md)

### ⭐ 이번 주 C 의 핵심 — 증류 타깃을 완성한다

이 PR이 머지되면 **w05 태그**를 단다. W6 전체가 여기에 집중된다.

### 수 — PR #268 clamp 수정 재제출

[CHANGES_REQUESTED 리뷰 (9/19)](../../pull/268#pullrequestreview-...) 내용: `engine.py:98` — `specificity.schema.json` 계약상 유효한 `resolution`(0~4)을 축별 표에 없는 값이라 `ValueError` 거부하는 버그.

수정:

```python
# engine.py — RESOLUTION[axis] 조회 전에 클램프
resolution = min(resolution, max(RESOLUTION[axis]))
level = RESOLUTION[axis][resolution]
```

sex는 0/1만 있으므로 resolution 2→1 클램프. 0 미만·4 초과·비정수 거부는 그대로.

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_c2_risk.py -v
# 25개 통과 확인
```

### 수~목 — span_to_condition() 구현

[#261 결정 코멘트](../../issues/261#issuecomment-5737937465) 기준으로 `src/kopl/c2_specificity/clues.py`에 구현한다.

```python
def span_to_condition(span: dict) -> dict | None:
    """
    B infer.py 스팬 한 개 → c2 condition dict 또는 None.
    None: 조건 생성 불가 (other subject, REL 축, 미해석 등)

    출력: {"axis": str, "resolution": int, "confidence": float}
    """
    ...
```

**축별 resolution 표**:

| axis | explicit | implicit | inferential | 비고 |
|---|---|---|---|---|
| LOC_ADMIN | resolve() 코드 길이: 시도=1·시군구=2·읍면동=3 | 같음 | 같음 | 미해석→None |
| LOC_FACILITY | 코드 있으면 4 | 4 | — | 없으면 None |
| AGE | 숫자 파싱→3, 세대→1 | 1 | 1 | |
| SEX | 1 (항상) | 1 | — | 배우자 호칭→family SEX 1 추가 |
| JOB | 2 | 1 | 1 | 직장 특정(3) 금지 |
| FAM | 학년·자녀수 정규식→3, 그 외→2 | 2 | 1 | |
| COMMUTE | 노선·역→2, 나머지→1 | 1 | — | |
| INCOME | 1 | — | — | |
| REL_HOME | 조건 안 만듦 → 동글 location confidence 1.0으로 올림 | | | |
| REL_WORK | 조건 안 만듦 → location 유지 + commute 1 (conf 0.5) 추가 | | | |

level → confidence: `explicit` 1.0 · `implicit` 0.8 · `inferential` 0.5

subject 처리: `other` → None · `self` → confidence 그대로 · `unknown` → confidence × 0.5

상수는 `model.py`에 모은다.

### 목~금 — C3 어댑터 + 증류 타깃 PR

**C3 어댑터**: `loo.py`의 `risk_fn`에 `risk_total`을 연결한다.

```python
# scripts/gen_contribution_targets.py
from kopl.c2_specificity import risk_total
from kopl.c3_contribution.loo import leave_one_out

def risk_fn(post_ids: tuple[str, ...]) -> float:
    conditions = build_conditions(post_ids)  # span_to_condition 사용
    return risk_total(conditions)

result = leave_one_out(
    user_ref=user_ref,
    post_ids=all_post_ids,
    risk_fn=risk_fn,
)
```

전 인물(115명) 실행 → `data/corpus/v0/gold/contribution/<pid>.json`

계약 검증:

```bash
check-jsonschema --schemafile docs/contracts/contribution.schema.json \
  data/corpus/v0/gold/contribution/A11.json
```

**PR에 첨부**: 20명 persona 검산 대조표 (ground_truth 비교)

### 만들 것

```
src/kopl/c2_specificity/clues.py               span_to_condition()
scripts/gen_contribution_targets.py             전 인물 실행 스크립트
data/corpus/v0/gold/contribution/<pid>.json     증류 타깃 세트
```

### 완료 기준

- [x] `loo.py` LOO 기여도 — 단위 테스트 통과 (#251 머지 · 9/16 · CI guard pass)
- [ ] PR #268 clamp 수정 + 25개 테스트 통과 → 재제출·머지
- [ ] `span_to_condition()` — 축별 resolution 표 완전 구현 (#261 결정 기준)
- [ ] `gen_contribution_targets.py` — 115명 전 인물 실행 + 계약 통과
- [ ] PR — 검산 대조표 20명 첨부

---

## D · 박재현 — PM 역할

> 전체 매뉴얼 [docs/roles/D-stage2.md](docs/roles/D-stage2.md)

### 현황

QLoRA 3ep adapter v1 확정 (verdict 90% · dev_loss 0.0044 · #264 · 9/18). 추가 학습 불필요. W6는 PM 역할 집중.

### 월 9/21 11:15 — KISIA 줌 주간보고회 발표

W5 성과 발표. [위 팀 회의 §0](#0-전원-공통--월-921-1115-kisia-줌-주간보고회) 표 참고.

### 수 23:59 — 주간보고서 취합

팀원 5명 보고 수합 + KISIA 제출.

### 목 9/25 21:00 — 멘토링

**안건:**
1. W6 진행 공유 — C 증류 타깃 진행 상황
2. E 활동 메타 필드 착수 보고
3. W7 대응 — B 1단 F1 확정·C 기여도 v1 확정·D Qwen3 v1 확정

### w05 태그 — C PR 머지 후

C 증류 타깃 PR 머지 직후 단다:

```bash
git tag w05
git push origin w05
```

### PM 몫

| 언제 | 무엇 |
|---|---|
| 일 9/20 저녁 | 팀원 보고 5줄 취합 (KISIA 줌 전날) |
| **월 9/21 11:15** | KISIA 줌 주간보고회 발표 |
| **수 23:59** | 주간보고서 최종 제출 |
| **목 9/25 21:00** | 멘토링 — W6 진행·W7 대응 |
| C PR 머지 후 | w05 태그 |

### 완료 기준

- [ ] 월 9/21 KISIA 줌 발표 완료
- [ ] 주간보고서 수 23:59 제출
- [ ] w05 태그 (C 증류 타깃 PR 머지 후)

---

## E · 이지희 — 활동 메타 필드

> 전체 매뉴얼 [docs/roles/E-system.md](docs/roles/E-system.md) · [howto/e-integration.md](docs/roles/howto/e-integration.md)

### ⭐ 이번 주 E 의 핵심 — 공개/비공개 토글

조치 ③ 시연에 필수다. 이 필드가 없으면 W9 에디터 실시간 경고 화면에서 "공개 전환→위험도 상승" 흐름을 보여줄 수 없다 ([roadmap §4](docs/roadmap.md)).

```
W5: 3화면 연결 ✅ → W6: 활동 메타 필드 착수 → W7: 에디터 실시간 경고 (D와)
```

### 수 — schema 마이그레이션

```sql
-- 현재 컬럼 확인
SELECT sql FROM sqlite_master WHERE name='posts';
```

없으면 마이그레이션:

```python
# apps/sns/migrate_meta.py
import sqlite3, os
conn = sqlite3.connect(os.environ["SNS_DB_PATH"])
try:
    conn.execute("ALTER TABLE posts ADD COLUMN geo_tag TEXT")
    conn.execute("ALTER TABLE posts ADD COLUMN visibility TEXT DEFAULT 'public'")
    conn.commit()
    print("마이그레이션 완료")
except sqlite3.OperationalError as e:
    print(f"이미 있음: {e}")
conn.close()
```

> ⚠️ 로컬 테스트 DB와 veilo.site 운영 DB를 구분해서 실행한다. `SNS_DB_PATH` 환경변수로 경로 확인 후 진행.

### 수~목 — 글 작성 화면 공개/비공개 토글

```html
<!-- apps/sns/templates/new_post.html 에 추가 -->
<label>
  <input type="checkbox" name="visibility" value="private" id="visibility-toggle">
  <span>비공개로 게시</span>
</label>
```

```python
# apps/sns/app.py — POST /posts 핸들러에 visibility 추가
visibility = request.form.get("visibility", "public")
# INSERT INTO posts (..., visibility) VALUES (..., ?)
```

### 목~금 — 위치태그 입력 필드 + seed_sns 갱신

```html
<!-- apps/sns/templates/new_post.html -->
<input type="text" name="geo_tag" placeholder="위치 (선택)">
```

`seed_sns.py` 갱신 — visibility·geo_tag 필드를 시딩 시 채운다:

```python
# geo_tag: persona의 행정구역 코드 기반
# visibility: 'public' 기본, 일부 인물은 'private' 혼합
```

### 만들 것

```
apps/sns/migrate_meta.py                 schema 마이그레이션
apps/sns/templates/new_post.html         공개/비공개 토글 + 위치태그 입력
apps/sns/app.py                          visibility·geo_tag 핸들러 추가
seed_sns.py                              메타 필드 시딩 갱신
```

### 완료 기준

- [x] 3화면 (스캔·진단·조치) — `ENGINE_MODE=mock` 엔드투엔드 에러 없음 (#254 · 9/17)
- [ ] schema 마이그레이션 — `geo_tag`, `visibility` 컬럼 추가
- [ ] 글 작성 화면 — 공개/비공개 토글 동작 확인
- [ ] seed_sns.py — visibility 필드 포함 재시딩 통과

---

## 이번 주 일정

| 요일 | 시각 | 누가 | 무엇 |
|---|---|---|---|
| **월 9/21** | 11:15 | D(PM) | KISIA 줌 주간보고회 발표 |
| 수 9/24 | | C | PR #268 clamp 수정 재제출 |
| 수 9/24 | | E | schema 마이그레이션 (geo_tag·visibility) |
| **수 23:59** | | 팀원 5명 | 주간보고서 5줄 PM에게 |
| 수~목 | | C | span_to_condition() 구현 |
| 수~목 | | E | 공개/비공개 토글 구현 |
| 목~금 | | C | C3 어댑터 + gen_contribution_targets.py + PR |
| 목~금 | | E | 위치태그 입력 + seed_sns 갱신 |
| **목 9/25 21:00** | | 전원+멘토 | 멘토링 — W6 진행 공유 · W7 대응 |
| C PR 머지 후 | | D | w05 태그 |

---

## 이번 주 반드시 지킬 것

**① C는 span_to_condition()에서 REL 축을 조건으로 만들지 않는다.**
REL_HOME·REL_WORK는 수식자다. REL_HOME(self)는 동글의 location confidence를 1.0으로 올리고, REL_WORK는 location 그대로 + commute 1(conf 0.5)만 추가한다.

**② E는 마이그레이션 전 `SNS_DB_PATH`로 경로를 확인한다.**
veilo.site 운영 DB와 로컬 테스트 DB를 구분해 마이그레이션한다.

**③ D는 w05 태그를 C PR 머지 전에 달지 않는다.**
증류 타깃 세트가 포함된 커밋이 main에 들어온 뒤에 태그를 단다.

---

## 막히면

| 상황 | 어떻게 |
|---|---|
| `span_to_condition()` LOC_ADMIN resolve() 코드 해석 불명 | `src/kopl/c2_specificity/geo.py` → `resolve()` 반환값 길이: 4자리=시도·7자리=시군구·10자리=읍면동 |
| PR #268 테스트 cp949 오류 | `PYTHONIOENCODING=utf-8 python -m pytest` |
| clamp 수정 후 기존 테스트 기댓값 불일치 | sex `resolution=2` → 클램프로 `resolution=1` 변경. 테스트에 해당 케이스 있으면 기댓값 수정 |
| `ALTER TABLE` 후 재시딩 필요한지 | 불필요 — ALTER TABLE은 기존 행 유지, 새 컬럼은 NULL/DEFAULT로 채워짐 |
| `check-jsonschema` 명령이 없다 | `pip install check-jsonschema` |
| SNS 서버 포트 3000 이 안 켜진다 | `apps/sns/` 디렉터리의 README 확인 또는 E에게 |
| PR 머지가 안 된다 | 리뷰어에게 요청 — 재촉하지 말고 한 번만 |

---

## 저장소 구조

```
KISIA_Project/
├─ README.md                      ← 이번 주 할 일 (이 문서)
├─ CONTRIBUTING.md                브랜치·커밋·리뷰 규칙
├─ docs/
│  ├─ overview.md                 프로젝트가 뭔지
│  ├─ plan.md                     계획 전문 (v2.2)
│  ├─ roadmap.md                  12주 주차별 계획
│  ├─ roles/                      역할별 작업 매뉴얼 5종
│  ├─ contracts/                  ⭐ 모듈 인터페이스 계약 6종 (W2 고정)
│  ├─ design/                     설계서 (W4 제출 완료)
│  ├─ decisions.md                결정 기록 [DEC-NNN]
│  ├─ mentor-log.md               멘토 피드백 [MF-NNN]
│  └─ RULES-DO-NOT.md             절대 하면 안 되는 것
├─ src/kopl/
│  ├─ c1_detector/                1단 탐지 (B)
│  ├─ c2_specificity/             특정성 엔진 (C)
│  ├─ c3_contribution/            기여도 엔진 (C · W5 신규)
│  └─ c4_stage2/                  2단 추론·가명화 (D · W5 신규)
├─ data/
│  ├─ corpus/v0/personas/         인물 JSON (115명 · W4 동결)
│  ├─ corpus/v0/posts/            생성 글 (3,092편 · W4 동결)
│  ├─ corpus/v0/gold/             골드셋 검수분 (417편 587스팬)
│  ├─ corpus/v0/gold/blind/       blind 분 ✅ (C · #229 머지 완료 9/14 · 159편 267스팬)
│  ├─ corpus/v0/gold/iaa/         IAA 배정 + A·C 라벨링
│  ├─ corpus/v0/gold/contribution/ 증류 타깃 세트 (C · W5 신규)
│  ├─ corpus/v0/splits/           train/test 분리 (A · W5 신규)
│  ├─ realism/cards/              리얼리즘 카드 18장
│  └─ dict/admin/                 행정구역·인구 사전
├─ experiments/
│  ├─ exp01-baseline/             베이스라인 3종 + LLM 상한 (W4 완성)
│  ├─ exp05-model-size/           Qwen3 크기 비교 (W3 완료)
│  ├─ exp06-finetune/             1단 파인튜닝 (B · W4~)
│  └─ exp07-qwen3-finetune/       2단 QLoRA (D · W4~)
├─ apps/
│  ├─ sns/                        가상 SNS (v0 + 시딩 완료)
│  └─ analyzer/                   분석 웹앱 (E · W5 신규)
├─ models/
│  └─ registry.md                 모델 체크포인트 등록부
└─ scripts/                       운영 스크립트
```

---

## 현재 미결 (9/20 기준)

**PR**
- [ ] PR #268 C `risk_total` + clamp 수정 — **C 수정 대기** → 머지 후 C3 어댑터 연결

**이슈 — W6**
- [ ] #261 span_to_condition() 구현 → C3 어댑터 → 증류 타깃 PR
- [ ] w05 태그 (C 증류 타깃 PR 머지 후)

**장기**
- [ ] [#206](../../issues/206) #201 후속 추적 — 각자 인물 JSON 확인
- [ ] [MF-015](docs/mentor-log.md) 대회 제출 요건·배포 범위 확인
- [ ] 잡담 글 「단서 0」 계약 vs 자영업·농업 인물의 삶 (#201 남은 쟁점) — v2
