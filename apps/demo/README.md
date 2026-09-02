# 대회용 스파이크 — 정본 아님

> **원티드 AI Championship 2026 제출용 데모.** 정본은 E 의 W5 분석 웹앱이며 이 디렉터리는 참고자료다.
> 팀 로드맵에 영향을 주지 않는다 — PM 단독 작업. `apps/sns/` 는 **읽기만** 하고 고치지 않는다.

「파도풀」 — 한국어 SNS 글의 재식별 위험을 개인이 스스로 점검하는 도구. 이름·전화번호가 하나도 없어도
나이·사는 곳·가족·소득 같은 준식별자가 여러 글에 흩어져 있다가 결합되면 개인이 특정된다. 파도풀은 그 결합을
찾아 **후보가 몇 명까지 좁혀지는가(k)** 를 주민등록 인구표로 센다.

## 띄우기

```bash
pip install -r apps/sns/requirements.txt -r apps/demo/requirements.txt
export PYTHONIOENCODING=utf-8 PYTHONPATH=src            # Windows git-bash 기준

python apps/demo/seed.py --reset          # 코퍼스 인물 5명 → data/interim/sns.db (리허설 전 항상)
python apps/demo/sns_ext.py               # 우리뜰(가상 SNS)  http://localhost:3000
python apps/demo/app.py                   # 파도풀(분석기)     http://localhost:8000

python -m pytest apps/demo/test_demo.py apps/sns/test_export.py -v
```

| 환경변수 | 기본 | 뜻 |
|---|---|---|
| `SNS_URL` | `http://localhost:3000` | 파도풀이 읽는 우리뜰 주소. **이 주소의 `/api/export/<user_ref>` 만 본다** |
| `DEMO_PORT` · `SNS_PORT` | 8000 · 3000 | 포트 |
| `DEMO_PERSONAS` | `D05,D01,D11,D17,D06` | 연결 화면의 예시 계정 (시딩과 같은 목록) |
| `DEMO_EXTERNAL_REWRITE` | 꺼짐 | `true` + `OPENAI_API_KEY` 가 있을 때만 리라이트 후보를 외부 API 로 만든다. 그 사실이 화면 상단과 provenance 에 표시된다 |
| `C1_MODEL_PATH` | 없음 | B 의 KoELECTRA 가중치 경로. 있으면 규칙 탐지기 대신 실제 모델을 쓴다 |

## 시연 4장면 (목업 그대로)

메인 인물은 **D05 「마당일기」** (`u_1a2e7dcc`) — 68세 · 여성 · 담양군 창평면. **글 18편에 지명이 한 번도 안 나온다.**

| 장면 | 어디서 | 무엇을 | 보이는 것 |
|---|---|---|---|
| 1 | 우리뜰 `/u/u_1a2e7dcc` | 방문자 눈으로 블로그를 본다 | 시골 잡담뿐. 신상이 없어 보인다 |
| 2 | 파도풀 `/` → 스캔 | export 로 **공개 글만** 읽는다 | 직접 식별자 0건인데 후보 **421명**. 깔때기 5,100만 → 호남 → 면 지역 → 창평면 → 65~69세 |
| 3 | 파도풀 조치 카드 → 우리뜰 | 조치 3종. **실행 버튼은 우리뜰에 있다** | ② 위치태그 끄기 · ③ 리라이트 3안 중 골라 우리뜰 수정 화면으로 · ① 「예순여덟」 글 비공개 |
| 4 | 파도풀 → 재스캔 | 같은 export 를 다시 읽는다 | 421명 → 수십만 명. 끊긴 경로가 취소선으로 남는다 |

근거 카드의 **「위험 문장 표시」 스위치**를 켜야 형광이 켜진다(기본 OFF). 점선은 잡았지만 **걸러낸** 표현이다 —
b17 「예전에 광주 살 때는」(시제 → 과거 거주), b08 「딸네 있는 여수로」(타인), b18 「해남서 왔다는 아주머니」(타인).
지명 사전만 쓰는 도구는 이 계정을 광주로 찍는다.

## 무엇이 진짜고 무엇이 스탑갭인가

| 부품 | 상태 | 데모에서 |
|---|---|---|
| 가상 SNS 우리뜰 · `/api/export` · 비공개 → export 반영 | ✅ E 완성 | `apps/sns` 그대로. `sns_ext.py` 가 **고치지 않고 import 해서** 위치태그 지우기·본문 수정 라우트 2개를 덧씌운다 |
| 특정성 k · 깔때기 | ✅ 실제 | C 의 `kopl.c2_specificity` — `regions.json`(geo-2026-07) + 행안부 주민등록 교차표(읍면동 × 5세 × 성별). 예시값 없음 |
| 조치 추천 · 예상 효과 | ✅ 실제 계산 | 조치를 적용한 상태로 깔때기를 다시 센다 (what-if). 계약 `Action.projected_delta` = 단독 효과, 화면의 「누적」 = 앞 조치까지 적용 |
| 1단 스팬 탐지 | ⚠️ **규칙 기반 스탑갭** | `engine/detect.py`. B 의 v1 은 9/20, 통합 W6~. `C1_MODEL_PATH` 로 교체 가능. 화면 상단에 명시 |
| 2단 결합 추론 · 리라이트 | ❌ 다음 버전 | 리라이트 후보는 캐시·규칙(`recommend.py`). 외부 API 는 옵션(기본 꺼짐). 「2단 모델 자리」로 소개 |
| 위험 점수(0~100) | ⚠️ 화면용 환산 | k 의 로그 척도 (`specificity.risk_score`). 정식 위험도 모델이 아니며 화면에 그렇게 적혀 있다 |

## 설계 제약 — 테스트가 지킨다 (`test_demo.py`)

- **원문이 분석 서버에 저장되지 않는다.** 파도풀은 DB·파일이 없다. 결과는 프로세스 메모리(`SESSIONS`)에만 있다.
  `sqlite3`·`sns.db` 가 분석기 코드에 없음을 테스트가 확인한다.
- **분석기는 export 만 읽는다.** `requests.get(f"{SNS_URL}/api/export/…")` 하나. SNS 에 쓰는 호출은 없다.
- **조치 실행 버튼은 SNS 쪽에 있다.** 파도풀의 버튼은 전부 우리뜰로 가는 링크·폼이다. 리라이트도 «제안이 채워진
  수정 화면» 을 열 뿐, 저장은 사용자가 우리뜰에서 누른다.
- **외부 호출은 `engine/external.py` 한 파일**, 기본 꺼짐. 켜면 provenance.external_llm_used 가 true 가 된다.
- **계약 대조.** 스팬 출력은 `span.schema.json`, 결과 JSON(`/api/result/<user_ref>`)은 `stage2-io.schema.json`
  `Stage2Output` 을 jsonschema 로 통과한다. 삭제 권고는 `exceptional` 로 분리, 기본 추천에 없다.
- **기권은 정상 동작.** D05 글에 성별 단서가 없어 성별은 abstain, k 는 남녀 합산이다. 추측하지 않는다.

## 실측 수치 (D05 · 시딩 그대로)

| 상태 | k | 근거 |
|---|---|---|
| 스캔 직후 (위치태그 켜짐) | **421** | 창평면 3,341 → 65~69세 421 (성별 기권) |
| ② 위치태그 끄기 | 111,069 | 방언(호남) 4,875,618 → 면 지역 854,527 → 65~69세 |
| ① 「예순여덟」(b14) 비공개 | 나이가 「경로당 → 65세 이상」으로 넓어진다 | 인물 설계의 암묵-only ablation 이 그대로 재현된다 |

> 핸드오프 문서의 「D05 k=5」는 옛 값이다. 현행 사전·교차표로는 421 이 나온다 (`kopl.c2_specificity.specificity_l1` 도 같은 값).

## 미결 — 팀에 물을 것

1. **리라이트 3안과 계약.** 현행 `Rewrite.suggestion` 은 단수다. 데모는 **같은 span_id 로 Rewrite 레코드 3개**를 내서
   계약을 바꾸지 않고 복수 후보를 실었다. `suggestions` 배열로 계약을 손볼지는 D·E 논점.
2. **`sns_ext.py` 의 라우트 2개**(위치태그 지우기 · 본문 수정)는 E 의 W4~W6 「메타 관리」 화면이 나오면 지운다.
   E 가 같은 경로 이름을 쓰면 데모는 수정 없이 그쪽을 탄다.
3. **배포는 AWS** [MF-013] — 크레딧 조건 확인 후. 두 프로세스(3000·8000)를 한 인스턴스에 두고 `SNS_URL` 만 바꾸면 된다.
   2단 GPU 는 데모에 없다(다음 버전 소개).
4. **시딩 인물** 5명은 `specificity_l1` 이 UNKNOWN 을 내지 않는 인물이다 (115명 중 63명이 산출 가능, #115 법정동 문제).

## 파일

```
app.py              파도풀 Flask (8000). DB 없음
sns_ext.py          우리뜰 실행기 — apps/sns 를 import 해 조치 라우트 2개 추가 (임시)
seed.py             코퍼스 → sns.db 시딩 (E 의 scripts/seed_sns.py 가 나오면 삭제)
engine/detect.py    1단 스탑갭 (규칙). span.schema.json 형식
engine/dialect.py   방언 사전 매칭 → flags.dialect_hits
engine/specificity.py  깔때기 — kopl.c2_specificity 위에서 k
engine/pipeline.py  export → 뷰 → k (what-if 지원) · findings
engine/recommend.py 조치 3종 + 예외 · 리라이트 3안 · Stage2Output
engine/external.py  외부 LLM (기본 꺼짐)
templates/          connect · result · sns_ext/(post_ext · edit_post)
test_demo.py        숫자 · 함정 · 계약 · 계층 경계
```
