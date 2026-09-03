# 대회용 스파이크 — 정본 아님

> **원티드 AI Championship 2026 제출용 데모.** 정본은 E 의 W5 분석 웹앱이며 이 디렉터리는 참고자료다.
> 팀 로드맵에 영향을 주지 않는다 — PM 단독 작업. `apps/sns/` 는 **읽기만** 하고 고치지 않는다.
> **로컬 브랜치에만 둔다.** push·PR 은 하지 않는다.

「파도풀」 — SNS 에 붙는 재식별 위험 점검 서비스. 이름·전화번호가 하나도 없어도 나이·사는 곳·가족·소득 같은
준식별자가 여러 글에 흩어져 있다가 결합되면 개인이 특정된다. 파도풀은 그 결합을 찾아 **후보가 몇 명까지
좁혀지는가(k)** 를 주민등록 인구표로 센다.

**논지**: 가상 SNS 「우리뜰」이 파도풀을 붙여 쓴다. 글을 쓸 때 올리기 전에 한 번 점검하고, 이미 쓴 글은 모아서
점검한다. 우리뜰이 네이버·인스타 자리이고, 다른 SNS 도 같은 방식으로 붙일 수 있다.
(크롬 확장으로 만들지 않은 이유 — 확장은 에디터 안에서는 되지만 **이미 써 둔 글 목록을 불러와 함께 셀 수 없다.**)

## 띄우기

```bash
pip install -r apps/sns/requirements.txt -r apps/demo/requirements.txt
export PYTHONIOENCODING=utf-8 PYTHONPATH=src            # Windows git-bash 기준

python apps/demo/seed.py --reset          # 코퍼스 인물 5명 → data/interim/sns.db (리허설 전 항상. 서버가 떠 있어도 됨)
python apps/demo/app.py                   # 파도풀 API      http://localhost:8000
python apps/demo/sns_ext.py               # 우리뜰(플랫폼)  http://localhost:3000  ← 심사위원이 보는 곳

python -m pytest apps/demo/test_demo.py apps/sns/test_export.py -v     # 22 passed
```

| 환경변수 | 기본 | 뜻 |
|---|---|---|
| `PADOPOOL_URL` | `http://localhost:8000` | 우리뜰이 부르는 파도풀 API |
| `SNS_URL` | `http://localhost:3000` | 파도풀 단독 화면(개발용)이 읽는 우리뜰 |
| `DEMO_PORT` · `SNS_PORT` | 8000 · 3000 | 포트 |
| `DEMO_PERSONAS` | `D05,D01,D11,D17,D06` | 파도풀 단독 화면의 예시 계정 (시딩과 같은 목록) |
| `DEMO_EXTERNAL_REWRITE` | 꺼짐 | `true` + `OPENAI_API_KEY` 가 있을 때만 리라이트 후보를 외부 API 로 만든다. provenance 에 표시된다 |
| `C1_MODEL_PATH` | 없음 | B 의 KoELECTRA 가중치 경로. 있으면 규칙 탐지기 대신 실제 모델 |

## 시연 — 전부 우리뜰 안에서

메인 인물 **D05 「마당일기」** `/u/u_1a2e7dcc` — 68세 · 여성 · 담양군 창평면. **글 18편에 지명이 한 번도 안 나온다.**

| 장면 | 어디서 | 보이는 것 |
|---|---|---|
| 1 | 블로그 `/u/u_1a2e7dcc` | 방문자 눈에는 시골 잡담뿐. 프로필에 「🛟 내 글 점검하기」 버튼 |
| 2 | **내 글 점검** `/u/u_1a2e7dcc/check` | 직접 식별자 0건인데 후보 **421명**. 깔때기 5,100만 → 호남(방언) → 면 지역(「면사무소」) → 창평면(위치태그) → 65~69세 |
| 3 | 같은 화면의 조치 카드 | ② 위치태그 지우기 · ③ 리라이트 3안 중 골라 「이 표현으로 고치기」 → 수정 화면에서 저장 · ① 「예순여덟」 글 비공개. **버튼이 다 여기(플랫폼) 있다** |
| 4 | 조치를 누르면 자동 재계산 | 421 → 111,069 → 407,969 → 1,259,354명. 끊긴 경로가 취소선으로 남는다 |
| 5 | **글쓰기** `/new` → 「🛟 파도풀로 점검」 | 올리기 전 1회 [MF-015]. 「이 글 하나가 후보를 1,259,354명 → 421명으로 좁힙니다」 + 새는 문장 형광. 고쳐 쓰고 다시 점검하거나 「알고도 올리기」 |

근거 카드의 **「위험 문장 표시」 스위치**를 켜야 형광이 켜진다(기본 OFF). 점선은 잡았지만 **걸러낸** 표현이다 —
b17 「예전에 광주 살 때는」(시제 → 과거 거주), b08 「딸네 있는 여수로」(타인), b18 「해남서 왔다는 아주머니」(타인).

## 경계 — 어디가 플랫폼이고 어디가 파도풀인가

```
우리뜰 (3000, apps/sns + sns_ext.py)        파도풀 (8000, app.py)
  글·계정·사진 DB                              DB 없음 · 파일 없음 · 저장 없음
  /api/export/<user_ref>  ──(같은 형식)──▶   POST /api/scan   전체 점검
  글쓰기 초안             ──────────────▶   POST /api/check  올리기 전 점검
  ◀── 진단·권고 JSON (Stage2Output 포함) ──
  조치 실행은 여기서: 비공개 · 위치태그 · 본문 수정
```

- 파도풀에 넘어가는 건 `/api/export` 형식뿐이다. 우리뜰이 원본 뷰 함수(`sns.export`)를 그대로 불러 만든다.
- 파도풀은 권고까지. 우리뜰의 글을 바꾸는 라우트는 파도풀에 없다 (테스트가 `requests.post`·`sqlite3` 부재를 확인).
- 외부 LLM 은 `engine/external.py` 한 곳, 기본 꺼짐.

## 무엇이 진짜고 무엇이 스탑갭인가

| 부품 | 상태 | 데모에서 |
|---|---|---|
| 우리뜰 · `/api/export` · 비공개 → export 반영 | ✅ E 완성 | `apps/sns` 그대로. `sns_ext.py` 가 import 해서 점검 화면·에디터 점검·태그 지우기·본문 수정을 **덧씌운다** |
| 특정성 k · 깔때기 | ✅ 실제 | C 의 `kopl.c2_specificity` — `regions.json`(geo-2026-07) + 행안부 주민등록 교차표(읍면동 × 5세 × 성별). 예시값 없음 |
| 조치 추천 · 예상 효과 · 올리기 전/후 k | ✅ 실제 계산 | 조치(또는 초안)를 반영한 상태로 깔때기를 다시 센다 |
| 1단 스팬 탐지 | ⚠️ **규칙 기반 스탑갭** | `engine/detect.py`. B 의 v1 은 9/20, 통합 W6~. `C1_MODEL_PATH` 로 교체 가능. 화면에 명시 |
| 2단 결합 추론 · 리라이트 | ❌ 다음 버전 | 리라이트 후보는 캐시·규칙. 외부 API 는 옵션(기본 꺼짐). 「2단 모델 자리」로 소개 |
| 위험 점수(0~100) | ⚠️ 화면용 환산 | k 의 로그 척도. 정식 위험도 모델이 아니며 화면에 그렇게 적혀 있다 |

## 실측 수치 (D05 · 시딩 그대로)

| 상태 | k |
|---|---|
| 점검 직후 (위치태그 켜짐) | **421** — 창평면 3,341 → 65~69세 421 (성별 단서 없음 → 기권, 남녀 합산) |
| ② 위치태그 지움 | 111,069 — 방언(호남) 4,875,618 → 면 지역 854,527 → 65~69세 |
| ③ b03 리라이트 | 407,969 — 면 단위 경로가 끊겨 호남 전체 65~69세 |
| ① b14 비공개 | 1,259,354 — 나이가 「경로당 → 65세 이상」으로 넓어진다 (인물 설계의 암묵-only ablation) |

> 핸드오프 문서의 「D05 k=5」는 옛 값이다. 현행 사전·교차표로는 421 (`specificity_l1` 도 같은 값).

## 미결

1. **리라이트 3안과 계약.** 현행 `Rewrite.suggestion` 은 단수라 같은 span_id 로 Rewrite 레코드 3개를 낸다. `suggestions` 배열로 갈지는 D·E 논점.
2. **`sns_ext.py`** 는 E 의 W4~W6 「메타 관리」· W9 「에디터 경고」 화면이 나오면 지운다.
3. **배포는 AWS** [MF-013] — 크레딧 조건 확인 후. 두 프로세스를 한 인스턴스에 두고 `PADOPOOL_URL` 만 맞추면 된다.
4. 시딩 인물 5명은 `specificity_l1` 이 UNKNOWN 을 내지 않는 인물이다 (115명 중 63명 산출 가능, #115 법정동 문제).

## 파일

```
sns_ext.py          우리뜰 실행기 — apps/sns 를 import 해 점검 화면·에디터 점검·조치 라우트를 덧씌운다 (임시)
app.py              파도풀 API (8000): POST /api/scan · /api/check. DB 없음. 단독 화면(/)은 개발 확인용
seed.py             코퍼스 → sns.db 시딩 (E 의 scripts/seed_sns.py 가 나오면 삭제)
engine/detect.py    1단 스탑갭 (규칙). span.schema.json 형식
engine/dialect.py   방언 사전 매칭 → flags.dialect_hits
engine/specificity.py  깔때기 — kopl.c2_specificity 위에서 k
engine/pipeline.py  export → 뷰 → k (what-if 지원) · findings
engine/recommend.py 조치 3종 + 예외 · 리라이트 3안 · Stage2Output
engine/external.py  외부 LLM (기본 꺼짐)
templates/sns_ext/  우리뜰에 덧씌우는 화면: profile_ext · check · new_ext · post_ext · edit_post
templates/, static/ 파도풀 단독 화면(개발용) · demo.css (우리뜰 점검 화면도 /pado-static 으로 같이 쓴다)
test_demo.py        숫자 · 함정 · 계약 · 계층 경계 · API 12건
```
