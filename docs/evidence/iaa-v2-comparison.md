# IAA 2차 파일럿 16편 — A·C 대조표 및 결과

`#200` 논의 후속. 새 코퍼스(p2.3) 기준 2차 IAA 16편 독립 라벨링
결과를 대조합니다.

## 수치 결과 (scripts/iaa.py)

| level | A | C | TP | P | R | partial F1 | exact F1 |
|---|---|---|---|---|---|---|---|
| explicit | 16 | 11 | 7 | 43.8% | 63.6% | 51.9% | 7.4% |
| implicit | 11 | 16 | 6 | 54.5% | 37.5% | 44.4% | 7.4% |
| inferential | 7 | 3 | 1 | 14.3% | 33.3% | 20.0% | 0.0% |
| **overall** | 34 | 30 | 16 | 47.1% | 53.3% | **50.0%** | 9.4% |

level 일치율 87.5%(14/16), subject 일치율 87.5%(14/16).

**1차(22.9%) 대비 partial F1이 두 배 이상 개선**됐습니다 — `#211`
(등급·유형 판정 기준 §3-3·§4-1·§6)이 실제로 효과가 있었던 것으로
보입니다.

## 전체 대조

| post_id | A | C |
|---|---|---|
| A07_b12 | SEX/implicit/self '형이' | SEX/implicit/self '형' |
| | FAM/implicit/self '엄마한테' | FAM/implicit/self '엄마' |
| | — | INCOME/inferential/self '용돈' |
| A11_b03 | AGE/explicit/self '스물일곱이나' | INCOME/inferential/self '자동으로 빠져나가는 금액' |
| | INCOME/implicit/self '부모님께 손 벌리기' | AGE/explicit/self '스물일곱' |
| | — | FAM/implicit/self '부모님' |
| A12_b07 | SEX/implicit/self '남편과' | SEX/implicit/self '남편' ×6 |
| | FAM/implicit/self '어린이집 등원' | FAM/implicit/self '어린이집 등원' |
| | FAM/implicit/self '첫돌까지' | — |
| A14_b15 | LOC_FACILITY/explicit/self '신촌역 3번 출구 근처' | LOC_ADMIN/explicit/unknown '신촌' |
| | LOC_ADMIN/explicit/self '신촌에서' | SEX/implicit/self '남자애 한 명 없던 반' |
| | — | LOC_FACILITY/explicit/unknown '신촌역 3번 출구' |
| A16_b03 | AGE/explicit/self '예순여덟인데' | AGE/explicit/self '예순여덟' |
| B06_b20 | LOC_ADMIN/explicit/self '인천' | COMMUTE/explicit/self '퇴근길에는 굴포천 산책' |
| | LOC_FACILITY/explicit/self '갈산역' | LOC_FACILITY/explicit/unknown '인천 1호선 갈산역 2번' |
| | LOC_FACILITY/explicit/self '굴포천 산책로' | — |
| B21_b29 | LOC_ADMIN/explicit/other '강원특별자치도 횡성군 둔내면' | JOB/implicit/other '참숯 직거래 공급처 계약' |
| | LOC_FACILITY/explicit/other '가마터까지' | LOC_ADMIN/explicit/other '강원특별자치도 횡성군 둔내면' |
| C08_b03 | LOC_FACILITY/explicit/self '장날 아침 시장 입구에서' | JOB/implicit/self '옆 좌판 생선가게' |
| | REL_HOME/inferential/self '첫 군내버스가' | — |
| | JOB/inferential/self '옆 좌판 생선가게 아지매와' | — |
| D12_b01 | JOB/implicit/self '야간 3일차' | JOB/implicit/self '야간 들어가기 전에 설비' |
| | JOB/inferential/self '설비 점검표' | — |
| D14_b06 | REL_HOME/explicit/self '집 앞 갯벌' | FAM/implicit/self '이모' |
| | FAM/implicit/self '이모가' | — |
| D14_b25 | LOC_ADMIN/explicit/other '친구 회사가 송도로' | REL_WORK/explicit/other '친구 회사가 송도로 옮겨서' |
| E05_b13 | LOC_ADMIN/inferential/self '캥거루는' | — |
| | LOC_ADMIN/explicit/self '한국에 나오니' | — |
| | REL_HOME/implicit/self '룸메이트랑' | — |
| E07_b05 | AGE/explicit/self '일흔셋' | AGE/explicit/self '일흔셋' |
| | LOC_FACILITY/inferential/self '경로당에' | — |
| E08_b11 | REL_HOME/inferential/self '식당까지 걸어서 십 분' | REL_HOME/inferential/self '식당까지 걸어서 십 분' |
| E18_b20 | SEX/implicit/self '언니가' | REL_WORK/explicit/other '언니가 창원 쪽 회사로' |
| | LOC_ADMIN/explicit/other '창원 쪽 회사로' | — |
| E20_b17 | AGE/explicit/self '스물하나인데' | JOB/implicit/self '종강하고' |
| | FAM/implicit/self '엄마가' | AGE/explicit/self '스물하나' |
| | JOB/inferential/self '종강하고' | FAM/implicit/self '엄마' |

## 어느 한쪽이 일방적으로 틀린 게 아닙니다

**A가 놓친 것**
- A07_b12 "용돈" (C가 잡음, INCOME 단서로 타당)
- A11_b03 "부모님" (C가 FAM으로 별도로 잡음, A는 INCOME 하나로만 처리)

**C가 놓친 것**
- E05_b13 전체 (캥거루·한국에 나오니·룸메이트랑 — 간접적 지역·거주 단서)
- D14_b06 "집 앞 갯벌" (캡션의 REL_HOME 단서)
- C08_b03 "첫 군내버스가"(REL_HOME), "장날 아침 시장 입구에서"(LOC_FACILITY)

**경계(§5-2 조사 포함) 불일치 — exact F1을 낮추는 주 원인**
"형이"(A) vs "형"(C), "스물일곱이나"(A) vs "스물일곱"(C), "예순여덟인데"(A)
vs "예순여덟"(C). partial은 매치되지만 exact가 실패하는 대부분이 이 패턴.

**subject 판정(self vs unknown)이 갈리는 자리 — 둘 다 일리 있음**
A14_b15·B06_b20에서 캡션의 위치 정보를 A는 self로, C는 unknown으로
판정. 이 기준을 더 명확히 할 필요가 있어 보임.

**유형이 갈리는 자리**
D14_b25 "친구 회사가 송도로"를 A는 LOC_ADMIN, C는 REL_WORK로. "친구
회사"라는 관계어가 있어 REL_WORK도 타당해 보임.

**A12_b07 — 같은 단어 반복 처리 방식이 다름**
"남편"이 여러 번 나오는 글에서 A는 대표 스팬 하나(첫 등장)만 잡았는데,
C는 등장할 때마다 6개 스팬으로 잡음. 어느 쪽이 맞는지 규칙 정리 필요.

## 다음에 맞춰볼 것

1. §5-2(조사 포함) 재확인 
2. 반복 등장하는 같은 단어를 매번 스팬으로 잡을지, 대표 스팬만 잡을지
3. 캡션의 위치 정보 subject 판정 기준
4. inferential 등급(간접 단서) 판정 시 서로 놓치는 경향 — 공유
