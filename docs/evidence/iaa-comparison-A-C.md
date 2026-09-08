# IAA 1차 파일럿 16편 — A·C 라벨 대조표

`#200` 논의를 위한 실측 대조입니다. 16편 전체를 나란히 놓고, 판단이 갈린 자리 넷(① 경계 ② 등급 ③ 누락 ④ 유형)이 각각 어디서
실제로 나타나는지 표시했습니다.

## 전체 대조

| post_id | A | C | 갈린 유형 |
|---|---|---|---|
| A01_b02 | REL_WORK/implicit/self `단체 사무실이 집에서 자전거로 십 분` (body) | REL_WORK/inferential/self `집 앞 하천길에서` (caption) | ③ 누락 — 서로 다른 단서 |
| A03_b05 | AGE/explicit/self `서른넷` · JOB/implicit/self `복직했다` · LOC_FACILITY/inferential/self `연구동 앞에서` | LOC_ADMIN/inferential/self `연구동 앞에서` · AGE/explicit/self `서른넷에` | ① 경계(서른넷/서른넷에) · ③ 누락(복직했다) · ④ 유형(LOC_FACILITY/LOC_ADMIN) |
| A05_b09 | — | — | 일치 |
| A08_b18 | REL_HOME/inferential/self `집 앞\n도서관` | REL_HOME/inferential/self `집 앞 도서관에서` | ① 경계만(범위 차이) |
| A19_b16 | FAM/implicit/self `큰애` | FAM/inferential/self `큰애가` | ① 경계 · ② 등급 |
| B04_b02 | AGE/explicit/self `마흔다섯` · LOC_ADMIN/explicit/self `정발산` | AGE/explicit/self `마흔다섯의` · LOC_FACILITY/explicit/self `정발산 단독주택 리모델링 현장` | ① 경계 · ④ 유형(LOC_ADMIN/LOC_FACILITY) |
| B06_b25 | JOB/implicit/self `임용 동기` · LOC_FACILITY/explicit/other `송도 신도시 연구소로 이직` | REL_WORK/explicit/other `임용 동기가 이번에 송도 신도시 연구소로 이직해서` | ④ 유형(JOB+LOC_FACILITY 분리 vs REL_WORK 하나) |
| C15_b15 | INCOME/implicit/self `부품값 먼저 나감.\n이번 달 작업비에서...` (긴 스팬) | INCOME/inferential/self `부품값` (짧은 스팬) | ① 경계(길이) · ② 등급 |
| C17_b09 | FAM/implicit/self `여동생` · SEX/explicit/self `오빠인 나` · JOB/implicit/self `면접 2회차` | FAM/inferential/self `여동생이 오빠인 나한테` (하나로 묶음) | ① 경계 · ② 등급 · ③ 누락(SEX·JOB) |
| D07_b16 | — | — | 일치 |
| D12_b04 | AGE/explicit/self `마흔다섯` · JOB/implicit/self `야간 3일차` | AGE/explicit/self `마흔다섯인데` | ① 경계 · ③ 누락(야간 3일차) |
| D12_b23 | JOB/implicit/self `새벽에 들어오니` · FAM/implicit/self `아들` | FAM/inferential/self `아들 중간고사라` (하나로 묶음) | ② 등급 · ③ 누락(새벽에 들어오니) |
| D16_b17 | — | FAM/inferential/self `딸 야자` | ③ 누락 (A가 못 찾음) |
| D20_b18 | — | AGE/explicit/self `쉰둘인데` | ③ 누락 (A가 못 찾음) |
| E08_b14 | FAM/implicit/self `도련님` | — | ③ 누락 (C가 못 찾음) |
| E21_b08 | FAM/implicit/self `할멈` · LOC_ADMIN/explicit/self `남강` | — | ③ 누락 (C가 못 찾음) |

## 패턴 요약

**② 등급 — 가장 빈번.** A19_b16·C15_b15·C17_b09·D12_b23에서 A가
`implicit`을 쓰는 자리에 C는 일관되게 `inferential`을 씁니다.
label-schema §4-1 기준("이 스팬 하나만으로 속성이 거의 확정되는가")
으로 재점검이 필요합니다.

**① 경계 — 조사·어미.** A03_b05·A19_b16·B04_b02·D12_b04에서 C가 조사를
포함(`마흔다섯의`, `마흔다섯인데`)하는데 A는 뗐습니다. §5-2가
"끝 어절의 조사·어미는 포함한다"고 명시하므로 C가 맞습니다.

**④ 유형 — LOC_ADMIN/LOC_FACILITY/REL_WORK.** B04_b02의 "정발산"과
B06_b25의 "임용 동기...이직" 구간에서 유형 판정 자체가 갈립니다.
§3-2·§3-3 표를 다시 대조해 판정 기준을 명문화해야 합니다.

**③ 누락 — 서로 다른 단서.** A01_b02(캡션 vs 본문), E08_b14·E21_b08
(C가 놓침), D16_b17·D20_b18(A가 놓침)처럼, 규칙의 문제가 아니라
각자 읽으며 놓친 경우입니다. 양쪽 다 있으므로 합의 대상이 아니라
그냥 확인 사항입니다.

## 완전 일치

A05_b09, D07_b16(둘 다 스팬 0건) — 둘만 갈림 없이 일치합니다. 스팬이
있으면서 내용까지 완전히 일치한 글은 없습니다.
