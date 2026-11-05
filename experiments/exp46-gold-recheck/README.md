# exp46 — 정답 3종 블라인드 사람 검수

test 239편에는 정답 파일이 세 개 있다([exp44](../exp44-xlmr-handoff/README.md#평가-기준--유리한-정답만-골라-보고하지-않는다)). 같은 수정 KoELECTRA의 partial F1이 정답에 따라 크게 달라진다.

| 정답 | 무엇 | 스팬 | 수정 KoELECTRA F1 |
|---|---|---:|---:|
| `official239` | 사람(C) 라벨 · 공식 골드 | 358 | .4013 |
| `previous_ai239` | AI가 라벨 관례를 통일한 것 | 428 | .7533 |
| `conservative239` | official의 명백한 오류만 AI가 보수적으로 고친 것 | 454 | .6062 |

이전 AI 정답에서 F1이 높게 나오는 이유는 두 가지로 볼 수 있다. 그 정답이 실제로 맞아서일 수도 있고, 모델과 AI 라벨러가 **같은 버릇**을 가져서일 수도 있다. 이 실험은 세 정답이 서로 갈리는 지점만 뽑는다. 어느 쪽이 맞는지는 **어느 정답에서 나온 후보인지 모르는 상태로** 사람이 판정한다.

- 공식 판정 값(명시 proxy **0.5211**)과 `data/corpus/*/gold/`, exp44 `data/`는 **바꾸지 않는다.** 이 실험은 해석용 기준만 정한다.
- 이 폴더의 스크립트는 정답 파일과 `data/corpus/v0/posts/`(합성 글)를 읽기만 한다. GPU는 쓰지 않는다.

## 검수자가 할 일 — 1시간 안팎 (60항목 × 1분)

**한 명만 해도 결과가 나온다.** 여럿이 하면 사람끼리 얼마나 일치하는지(κ)도 함께 나온다.

1. 브랜치를 받는다 (PowerShell · 저장소 루트)
   ```powershell
   git fetch origin
   git switch PM/exp46-gold-recheck
   ```
2. 검수지를 자기 역할 이름으로 복사한다. 역할 → 계정 매핑은 `.github/CODEOWNERS`를 따른다(A=nuewsun · B=philotti · C=jhyun114 · D=jaepaly · E=zihhhhh). 아래 `A`를 자기 역할로 바꾼다.
   ```powershell
   Copy-Item experiments/exp46-gold-recheck/sheet.csv experiments/exp46-gold-recheck/reviews/A.csv
   ```
3. `reviews/A.csv`를 엑셀로 연다. 행마다 `문맥`에서 【】로 표시한 부분을 읽고 **`선택` 칸에만** 아래 다섯 값 중 하나를 쓴다. 메모는 자유롭게 쓴다.
   - `X` / `Y` — 그 후보가 맞음 (`후보_Z`는 이번 검수지에 없다 — 아래 「후보가 둘인 이유」)
   - `모두 틀림` — 둘 다 틀림. 맞는 답을 `메모`에 적어 주면 좋다
   - `애매` — 규칙상 어느 쪽으로도 볼 수 있음
   - `item_id`·`후보_*` 칸은 고치지 않는다. 고치면 집계 스크립트가 거부한다
4. 엑셀에서 **다른 이름으로 저장 → 「CSV UTF-8(쉼표로 분리)」**로 저장한다. 일반 「CSV」로 저장했어도 집계는 읽는다
5. 커밋하고 push 한다
   ```powershell
   git add experiments/exp46-gold-recheck/reviews/A.csv
   git commit -m "exp(exp46): A 정답 블라인드 검수 결과"
   git push
   ```

블라인드를 지키는 방법:

- 검수가 끝날 때까지 `experiments/exp44-xlmr-handoff/data/`, `data/corpus/v0/gold/`을 열지 않는다. `post_id`는 원문 전체를 보고 싶을 때만 쓴다. `data/corpus/v0/posts/`에서 찾으면 된다
- 다른 사람의 `reviews/*.csv`는 끝낸 뒤에 본다. 판정은 서로 상의하지 않는다
- **C(@jhyun114)는 선택이다.** `official239`를 쓴 사람이라 자기 라벨을 지지할 가능성이 있다. 그래서 다수결·Fleiss κ에서는 빼고 따로 집계한다. 촬영 일정이 우선이다

### 판정 기준 — 계약 요약 ([label-schema](../../docs/contracts/label-schema.md))

- **채점은 partial match다.** `type`이 같고 문자 IoU ≥ 0.5이면 같은 스팬으로 친다. 조사 한두 글자 차이(「서른여덟」 vs 「서른여덟에」)는 이미 같은 후보로 합쳤다. 남은 후보끼리는 **유형이 다르거나, 경계가 절반 넘게 다르거나, 한쪽에만 스팬이 있는** 경우다
- **유형 10개**: AGE · SEX · LOC_ADMIN · LOC_FACILITY · REL_HOME(집 근처·동네) · REL_WORK(회사 앞·공장에서) · JOB · FAM · COMMUTE(교통·통근·퇴근길) · INCOME(소비·지출 수준). 배우자 호칭(남편·아내)은 SEX/implicit이다
- **등급**: `explicit`은 값이 그대로 적힌 경우다. **「마흔여덟」처럼 한글 수사여도 explicit**이다. `implicit`은 값이 직접 적히진 않았지만 단독으로 거의 확정되는 경우고, `inferential`은 단독으로는 확정되지 않는 경우다. 등급은 F1에 들어가지 않으니 **등급만 다르면 판정에 쓰지 말고** 유형·범위·스팬 여부로 고른다
- **경계**: 어절 단위로 끊고, 끝 어절의 조사·어미는 포함한다. 서술어는 뺀다. 스팬끼리 겹치면 안 되고, 겹칠 때는 가장 긴 것을 우선한다
- **스팬이 아닌 것**: 「무릎이 예전 같지 않네요」 같은 세대 신호, 밈. 학력·학교·전공·정치성향·건강·지적 수준은 라벨하지 않는다
- 판단 질문은 하나다. **「이 글을 쓴 사람(또는 언급된 사람)의 7속성 — 나이·성별·위치·직업·가족·통근·소득 — 을 좁히는 단서인가, 그렇다면 어느 유형·범위인가」**

## 불일치 단위 — 어떻게 묶었나

1. 글마다 세 정답의 스팬을 모두 노드로 둔다. **같은 채널에서 한 글자라도 겹치면 간선으로 잇는다(유형 무관).** 연결 성분 하나가 단위 하나다
2. 단위 안에서 정답 두 개의 스팬 집합을 계약 규칙으로 비교한다. 규칙은 유형 일치 + IoU ≥ .5이고, IoU 내림차순으로 탐욕적 1:1 짝을 짓는다. exp44 `handoff.match_counts`와 같다. 개수가 같고 전부 짝지어지면 **채점상 같다**고 본다
3. 세 정답이 모두 채점상 같으면 「일치」다. 그렇지 않은 단위가 **불일치 단위**이고, 불일치 단위 하나가 검수 항목 하나다
4. 같은 것끼리 묶은 묶음 하나가 후보 하나다. 묶음 안에서 경계·등급이 조금 다른 표시본 가운데 하나를 무작위로 보여 준다. 등급이나 조사만 다른 차이는 F1을 바꾸지 않기 때문이다
5. 층 = **패턴 × 성격**
   - 패턴 `O_alone`: official 혼자 다름(previous = conservative) · `P_alone`: previous 혼자 다름(official = conservative)
   - 성격 `lone_extra`(혼자만 스팬 있음) · `lone_missing`(혼자만 스팬 없음) · `type`(겹치는데 유형 다름) · `boundary`(유형은 같고 IoU<.5 또는 분할 수 차이)

### 결과 — 전체 불일치와 60항목 층 구성

239편 중 스팬이 있는 글은 230편이고, 단위는 511개다. **일치 156 · 불일치 355.** conservative가 혼자 다른 단위나 셋이 모두 다른 단위는 **0개**였다. conservative239는 단위마다 official과 previous 가운데 한쪽을 따른다. 그래서 모든 항목은 **official 쪽과 previous 쪽의 맞대결**이고, 후보는 항상 둘이다.

| 층 | 모집단 | 표본 |
|---|---:|---:|
| O_alone · lone_missing (official만 스팬 없음) | 110 | 7 |
| O_alone · lone_extra (official만 스팬 있음) | 24 | 7 |
| O_alone · type | 9 | 8 |
| O_alone · boundary | 9 | 8 |
| P_alone · lone_missing (previous만 스팬 없음) | 92 | 7 |
| P_alone · lone_extra (previous만 스팬 있음) | 43 | 7 |
| P_alone · type | 30 | 8 |
| P_alone · boundary | 38 | 8 |
| **합계** | **355** | **60** |

층마다 균등하게 뽑았다(공개 seed `20261105`). 표본 비율은 모집단 비율과 다르다. 60항목 원시 비율은 「갈리는 유형마다 누가 맞나」를 보여 준다. **전체 불일치 355개에 대한 추정은 층 크기로 가중한 값**(`stratum_weighted`)을 쓴다. 전체 수치는 [`units_summary.json`](units_summary.json)에 있다.

### 블라인드 설계

- **공개**: 단위 정의 · 층화 추출(seed 고정). 아래 명령으로 누구나 같은 60개 단위를 다시 뽑을 수 있다
  ```powershell
  $env:PYTHONIOENCODING = 'utf-8'
  python -X utf8 experiments/exp46-gold-recheck/build_sheet.py summary
  ```
- **비공개**: 항목 순서, 후보 X/Y 배정, 표시본 선택은 **비밀 salt**로 섞었다. salt와 「후보 → 정답」 매핑(키)은 저장소 밖 PM 로컬에 둔다. 저장소에는 아래 해시만 적는다. 검수가 끝나면 키를 공개하고, 누구나 해시를 대조하고 `build_sheet.py build --salt <공개 salt>`로 같은 sheet가 나오는지 확인할 수 있다
- 키 SHA-256: `a38bf76580d89348346dcd1b6392f0a9e4fc1f1c2d5d4bc8dc61b561cd0d0aa2`

## 집계 — PM

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python -X utf8 experiments/exp46-gold-recheck/tally.py --key C:/Users/dor12/kisia-private/exp46_key.json --out C:/Users/dor12/kisia-private/exp46_tally.json
python -X utf8 -m unittest discover -s experiments/exp46-gold-recheck/tests -v
```

- `per_reviewer` — 검수자별로 정답마다 지지 항목 수 · 비율 · Wilson 95% CI, `모두 틀림`·`애매` 비율, 층별 분포를 낸다. 분모는 응답한 항목 전체다(모두 틀림·애매 포함)
- `majority_pooled` — C를 뺀 검수자의 항목별 다수결이다. 동률은 `애매`로 처리한다. 원시 비율과 함께 `stratum_weighted`(층 가중 추정 · 층별 분산 합으로 낸 95% CI)를 낸다
- `fleiss_pooled`(C 제외) · `cohen_pairs`(C 포함 모든 쌍) — 다섯 범주(X/Y/Z/모두 틀림/애매)로 계산한 일치도다

## 해석 기준 — 사전 등록 (검수 결과를 보기 전에 정함)

주 지표는 **C를 뺀 다수결의 층 가중 지지율**이다. 모든 항목이 official 대 previous 대결이라 두 지지율의 합은 `1 − (모두 틀림 + 애매)`다.

| 결과 | 판단 | 이후 실험의 주 비교 기준 |
|---|---|---|
| `모두 틀림 + 애매` ≥ 30% | 세 정답 모두 갈리는 곳에서 믿기 어렵다 | 결론 보류 · 지금 정책(conservative 주 · 나머지 병기) 유지 |
| previous 지지율 95% CI **하한 > official 지지율 상한** | AI 관례가 사람 판단에도 맞다. 높은 F1은 버릇 효과만은 아니다 | conservative239 · previous239 병기, official239는 진단용 |
| official 지지율 95% CI **하한 > previous 지지율 상한** | 높은 F1은 같은 버릇 효과다 | **official239** 로 되돌린다. previous239는 참고치 |
| 그 밖(구간 겹침) | 판정 불가 | conservative239를 주 기준으로 두고 세 값 병기(exp44 정책 그대로) |

- conservative239의 지지율은 따로 보고한다. 「명백한 오류만 고친다」는 전제가 맞았다면 O_alone 층에서는 previous 쪽, P_alone 층에서는 official 쪽이 이겨야 한다. 층별 결과로 이 전제를 확인한다
- 검수자가 둘 이상이고 Fleiss κ < .40이면 결론 앞에 「사람끼리도 많이 갈림」을 먼저 적는다
- C의 결과는 위 판단에 넣지 않고 옆에 적는다
- **어떤 결과든 공식 판정 값 0.5211은 바꾸지 않는다.** 공식 골드 파일도 이 실험으로 고치지 않는다. 고쳐야 한다는 결론이 나면 별도 PR(골드셋 승인 절차)로 다룬다

## 한계

- 60항목이고, 층마다 7~8개다. 층별 결론은 방향만 보여 줄 뿐 정밀하지 않다
- 검수자가 팀원이고, 정답 파일은 공개 저장소에 있다. 블라인드는 검수자가 파일을 열지 않는다는 약속에 기댄다
- 라벨러마다 버릇이 있다(예: official은 조사를 빼는 경향). 이 버릇으로 출처를 짐작할 여지는 남는다. 조사 차이는 같은 후보로 합쳐 줄였지만 경계·유형 항목에서는 완전히 지울 수 없다
- 단위 안의 다른 스팬(세 정답이 모두 일치한 것)은 문맥에 표시하지 않는다. 【】 부분만 판정한다

## 파일

| 파일 | 내용 |
|---|---|
| `build_sheet.py` | 단위 생성 · 층화 추출 · 검수지와 비공개 키 생성 |
| `sheet.csv` | 검수지 원본(UTF-8 BOM). **직접 채우지 말고 `reviews/`에 복사해서 채운다** |
| `units_summary.json` | 불일치 전체 통계 · 층 구성 · 표본 단위 id(정답 매핑 없음) |
| `reviews/<역할>.csv` | 검수 결과 |
| `tally.py` | 집계 |
| `tests/test_exp46.py` | 매칭·층 판정 · 가짜 키·가짜 검수로 집계 · 커밋된 sheet에 정답 이름이 없는지 검사 |
