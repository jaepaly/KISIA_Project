# 공공데이터 받아서 지명 사전 만들기

> **대상: C 신정현.** [C-specificity.md](../C-specificity.md)의 실무 편.
> W2 월~금. **하루 반이면 끝난다.** 어려운 건 없고, 함정이 몇 개 있을 뿐이다.

---

## 0. 무엇을 왜 받나

특정성 엔진이 하는 일은 결국 **표를 조회하는 것**이다. *"신갈동 40대 남성이 몇 명"* 을 답하려면 그 표가 있어야 한다.

| 받을 것 | 무엇에 쓰나 | 없으면 |
|---|---|---|
| **행정구역 코드·계층** | 지명 → 코드 변환, 시도/시군구/읍면동 포함관계 | 동 이름 중복을 구분 못 한다 |
| **읍면동 × 연령 × 성별 인구** | k 계산의 본체 (§4 규칙 2의 교차표) | 조건을 곱해야 하고, 그러면 붕괴한다 |
| **시설·랜드마크 위치** | "신갈저수지" → 신갈동 | 시설 단서를 지역으로 못 바꾼다 |

**W2에는 앞의 둘만.** 시설은 W4다.

---

## 1. 어디서 받나

> ⚠️ 사이트 메뉴 구조와 파일 이름은 바뀐다. **아래는 2026-08 기준이고, 못 찾으면 사이트 검색창에 굵은 글씨의 자료명을 그대로 넣는다.**

### ① 행정구역 코드·계층

| | |
|---|---|
| 사이트 | **행정표준코드관리시스템** `https://www.code.go.kr` |
| 자료 | **법정동코드 전체자료** (공통표준코드 → 법정동코드) |
| 형식 | 탭 구분 텍스트 (`.txt`) |
| 컬럼 | `법정동코드` · `법정동명` · `폐지여부` |
| 크기 | 5만 행 안팎 |

**법정동코드 10자리 구조** — 이걸 알면 계층을 따로 만들 필요가 없다.

```
4 1 4 6 3 1 0 1 0 0
└─┘ └───┘ └───┘ └─┘
시도  시군구  읍면동   리
 2자리  3자리   3자리  2자리
```

- 뒤 8자리가 `00000000` → **시도**
- 뒤 5자리가 `00000` → **시군구**
- 뒤 2자리가 `00` → **읍면동**
- 그 외 → **리** (우리는 안 쓴다)

즉 **상위 코드는 자기 코드에서 뒷자리를 0으로 밀면 나온다.** 부모-자식 관계를 따로 계산할 필요가 없다.

### ② 읍면동 × 연령 × 성별 인구

| | |
|---|---|
| 사이트 | **주민등록 인구통계** `https://jumin.mois.go.kr` |
| 자료 | **연령별 인구현황** |
| 조회 조건 | 행정구역 **읍면동**까지 · 구분 **남/여 구분** · 연령 **5세 단위** · 기준월 **하나로 고정** |
| 형식 | CSV 또는 XLSX 내려받기 |

> **기준월을 하나로 고정한다.** 나중에 파일을 다시 받을 때 다른 달을 받으면 숫자가 미묘하게 달라지고, 그러면 **W5에 잰 기여도와 W7에 잰 상관이 같은 기준이 아니게 된다.** 고른 달을 `dict_version` 에 박는다 (예: `geo-2026-07`).

**보조 — KOSIS** `https://kosis.kr` : 위 사이트에서 원하는 조합이 안 나올 때, 그리고 직업·가구 구성 비율(§4 규칙 3에서 쓰는 `p`)을 찾을 때 쓴다. OpenAPI도 있지만 **W2에는 파일 내려받기로 충분하다.**

### ③ 시설·랜드마크 (W4)

| 사이트 | 자료 | 비고 |
|---|---|---|
| **공공데이터포털** `https://www.data.go.kr` | 전국 도시공원 / 전국 초중등학교 위치 / 전국 도서관 등 **"표준데이터"** | 대부분 CSV, 주소 컬럼 포함 |
| **도로명주소 개발자센터** `https://business.juso.go.kr` | 주소 → 행정코드 변환 | 주소만 있고 코드가 없을 때 |

**저수지·낚시터처럼 표준데이터가 없는 것도 있다.** 그 경우는 §5의 수동 목록으로 간다.

---

## 2. 받자마자 하는 것 — 라이선스 기록 (5분)

**다운로드 버튼을 누른 그 자리에서 적는다.** 나중에 하려면 어느 페이지에서 받았는지 기억이 안 난다.

`data/README.md` 의 라이선스 표에 한 줄씩 추가한다.

```markdown
| 출처 | 용도 | 라이선스 | 확인일 |
|---|---|---|---|
| 행안부 행정표준코드 · 법정동코드 전체자료 | 행정구역 계층 사전 | 공공누리 제1유형 | 2026-08-24 |
| 행안부 주민등록 인구통계 · 연령별 인구현황(2026-07) | k 계산 인구 교차표 | 공공누리 제1유형 | 2026-08-24 |
| 공공데이터포털 · 전국 도시공원 표준데이터 | 시설 매핑 | 이용허락범위 제한 없음 | 2026-08-24 |
```

> ⚠️ **라이선스는 추측하지 말고 페이지에 표기된 것을 그대로 적는다.** 공공누리 제1유형이 대부분이지만 예외가 있다. 벤치마크 `KoPrivacyLeak` 공개 여부가 이 표에 걸려 있다([plan.md §6](../../plan.md)).

원본 파일은 `data/dict/admin/_raw/` 에 그대로 두고, **가공본만 커밋한다.** 원본이 수십 MB면 커밋하지 않고 받는 절차만 기록한다.

---

## 3. 함정 5가지 — 여기서 반나절이 날아간다

| # | 증상 | 원인 | 대처 |
|---|---|---|---|
| 1 | 한글이 `¿¬·É` 처럼 깨진다 | CP949(EUC-KR) 인코딩 | `pd.read_csv(f, encoding="cp949")` · 또는 `iconv -f CP949 -t UTF-8 in.txt > out.txt` |
| 2 | 코드가 `4.14631e+09` 로 보인다 | **엑셀로 열었다** | 엑셀로 열지 않는다. 이미 저장했으면 원본을 다시 받는다 |
| 3 | 코드 앞자리 `0` 이 사라졌다 | 숫자로 파싱됨 | `pd.read_csv(f, dtype=str)` — **모든 코드 컬럼은 문자열** |
| 4 | 인구 숫자가 `1,234` 라 더할 수 없다 | 천 단위 콤마 | `df["pop"].str.replace(",", "").astype(int)` |
| 5 | 동 이름은 같은데 인구가 다르다 | **행정동 ≠ 법정동** | §4 참조 |

### 행정동과 법정동 — 이건 개념부터

| | 법정동 | 행정동 |
|---|---|---|
| 무엇 | 법으로 정한 지역 이름. 주소에 쓴다 | 행정 편의로 나눈 단위. 주민센터 관할 |
| 예 | 신갈동 하나 | 신갈동이 인구가 많으면 신갈1동·신갈2동으로 쪼갬 |
| 어디에 있나 | 행정표준코드 | **주민등록 인구통계** |

**우리에게 필요한 건 인구다.** 그러니 **인구통계 쪽 코드(행정동)를 정본으로 삼는다.** 법정동코드는 계층 관계와 이름 검색용 보조로만 쓴다.

> 완벽히 매핑하려고 애쓰지 않는다. 이름이 안 맞는 건 `unmatched.csv` 로 빼두고 넘어간다. **전국 읍면동 3,500개 중 몇십 개가 안 맞아도 우리 코퍼스의 지명은 A가 아는 목록이라 실제로는 문제가 안 된다.**

---

## 4. `regions.json` 만들기

### 목표 형식

```json
{
  "schema_version": "1.0",
  "dict_version": "geo-2026-07",
  "source": "행안부 법정동코드 전체자료 + 주민등록 인구통계 2026-07",
  "generated_at": "2026-08-25",
  "regions": {
    "4146310100": {
      "code": "4146310100",
      "name": "신갈동",
      "full_name": "경기도 용인시 기흥구 신갈동",
      "level": "emd",
      "parent": "4146300000",
      "sido": "경기도",
      "sigungu": "용인시 기흥구",
      "population": 21930,
      "aliases": ["신갈", "신갈동"]
    }
  },
  "name_index": {
    "신갈동": ["4146310100"],
    "중앙동": ["2611053000", "4113052000", "..."]
  }
}
```

> **코드는 전부 예시다.** 실제 값은 받은 파일에서 확인한다.
> `name_index` 가 **동 이름 중복을 다루는 장치**다. 이름으로 조회하면 후보 목록이 나오고, 상위 지역 단서로 좁힌다. 후보가 여럿이면 **가장 인구가 많은 것을 고르지 말고, 후보 전체를 반환해 상위 단서로 교집합을 잡는다** — 이게 R1의 "신갈저수지 ∧ 기흥호수" 교집합과 같은 원리다.

### 코드

```python
# scripts/c2_build_regions.py
import json, pandas as pd
from pathlib import Path

RAW = Path("data/dict/admin/_raw")
OUT = Path("data/dict/admin")
DICT_VERSION = "geo-2026-07"

# --- 1) 법정동코드 전체자료 --------------------------------------------
#  컬럼명은 파일마다 다를 수 있다. 먼저 head 로 눈으로 확인할 것.
ld = pd.read_csv(RAW / "법정동코드 전체자료.txt", sep="\t",
                 dtype=str, encoding="cp949")
ld.columns = [c.strip() for c in ld.columns]
ld = ld[ld["폐지여부"] == "존재"]                    # 폐지된 동 제거
ld["code"] = ld["법정동코드"].str.zfill(10)

def level_of(code: str) -> str:
    if code.endswith("00000000"): return "sido"
    if code.endswith("00000"):    return "sigungu"
    if code.endswith("00"):       return "emd"
    return "ri"

def parent_of(code: str) -> str | None:
    lv = level_of(code)
    if lv == "sido":    return None
    if lv == "sigungu": return code[:2] + "00000000"
    if lv == "emd":     return code[:5] + "00000"
    return code[:8] + "00"

ld["level"]  = ld["code"].map(level_of)
ld["parent"] = ld["code"].map(parent_of)

# 법정동명은 "경기도 용인시 기흥구 신갈동" 처럼 전체 경로로 들어온다
parts = ld["법정동명"].str.split()
ld["name"]      = parts.str[-1]
ld["full_name"] = ld["법정동명"]
ld["sido"]      = parts.str[0]
ld["sigungu"]   = parts.str[1:-1].str.join(" ")

emd = ld[ld["level"].isin(["sido", "sigungu", "emd"])].copy()

# --- 2) 인구 붙이기 ----------------------------------------------------
#  population.csv 는 c2_build_population.py 가 먼저 만든다 (§5)
pop = pd.read_csv(OUT / "population.csv", dtype={"code": str})
total = pop.groupby("code")["population"].sum()
emd["population"] = emd["code"].map(total).fillna(0).astype(int)

# --- 3) 저장 -----------------------------------------------------------
regions, name_index = {}, {}
for r in emd.to_dict("records"):
    regions[r["code"]] = {
        "code": r["code"], "name": r["name"], "full_name": r["full_name"],
        "level": r["level"], "parent": r["parent"],
        "sido": r["sido"], "sigungu": r["sigungu"],
        "population": r["population"],
        "aliases": sorted({r["name"], r["name"].rstrip("동읍면")}),
    }
    name_index.setdefault(r["name"], []).append(r["code"])

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "regions.json").write_text(json.dumps({
    "schema_version": "1.0",
    "dict_version": DICT_VERSION,
    "source": "행안부 법정동코드 전체자료 + 주민등록 인구통계 2026-07",
    "generated_at": "2026-08-25",
    "regions": regions,
    "name_index": name_index,
}, ensure_ascii=False, indent=1), encoding="utf-8")

print(f"regions={len(regions)}  names={len(name_index)}")
```

> **`ensure_ascii=False` 를 빼먹지 않는다.** 빼면 한글이 `신갈` 로 저장돼 사람이 못 읽고, 파일이 3배로 커지고, git diff가 지옥이 된다.

---

## 5. `population.csv` 만들기 — k 계산의 본체

### 목표 형식 (long format)

다운로드 파일이 어떤 모양이든 **아래 4컬럼으로 정규화한다.** 이 형식이면 조회가 한 줄이다.

```csv
code,name,sex,age_band,population
4146310100,신갈동,M,40-44,812
4146310100,신갈동,M,45-49,764
4146310100,신갈동,F,40-44,798
```

- `sex` — `M` / `F` 두 값만
- `age_band` — `0-4` … `95-99` · `100+` (5세 단위). 표기를 절대 섞지 않는다
- 합계 행(`총인구수`, `계`)은 **버린다.** 남겨두면 이중 계산된다

### 조회

```python
def lookup(pop, code=None, sex=None, age_bands=None) -> int:
    q = pop
    if code:       q = q[q["code"] == code]
    if sex:        q = q[q["sex"] == sex]
    if age_bands:  q = q[q["age_band"].isin(age_bands)]
    return int(q["population"].sum())

lookup(pop, code="4146310100")                                  # 신갈동 전체
lookup(pop, code="4146310100", sex="M",
       age_bands=["40-44", "45-49"])                            # 40대 남성
```

**이 두 줄이 §4 규칙 2의 전부다.** 독립 가정 없이 실측값을 읽는다.

### 넓은 표(wide)를 long으로 바꾸는 뼈대

```python
# scripts/c2_build_population.py
import pandas as pd, re
from pathlib import Path

raw = pd.read_csv("data/dict/admin/_raw/연령별인구현황_2026_07.csv",
                  dtype=str, encoding="cp949")
raw.columns = [c.strip() for c in raw.columns]

# 1) 행정기관코드 / 행정기관명 컬럼 이름을 실제 파일에서 확인해 맞춘다
code_col, name_col = "행정기관코드", "행정기관"
raw["code"] = raw[code_col].str.extract(r"(\d{10})")[0]
raw["name"] = raw[name_col].str.split().str[-1]

# 2) "2026년07월_남_40~44세" 같은 컬럼을 (sex, age_band) 로 푼다
rows = []
for col in raw.columns:
    m = re.search(r"(남|여)[_\s]*(\d+)~(\d+)세", col)
    if not m:
        continue
    sex = "M" if m.group(1) == "남" else "F"
    band = f"{m.group(2)}-{m.group(3)}"
    part = raw[["code", "name", col]].copy()
    part.columns = ["code", "name", "population"]
    part["sex"], part["age_band"] = sex, band
    rows.append(part)

pop = pd.concat(rows, ignore_index=True)
pop["population"] = (pop["population"].fillna("0")
                     .str.replace(",", "").astype(int))
pop = pop.dropna(subset=["code"])
pop = pop[["code", "name", "sex", "age_band", "population"]]
pop.to_csv("data/dict/admin/population.csv", index=False, encoding="utf-8")
print(pop.shape, pop["population"].sum())
```

> **정규식은 파일에 맞춰 고쳐야 한다.** `100세 이상` 같은 컬럼은 위 정규식에 안 걸리므로 따로 처리하거나 버린다. 버려도 우리 용도에는 영향이 없다.

### 폴백 — 교차표를 도저히 못 만들겠으면

**총인구만 있는 `population.csv` 로도 L1까지는 간다.** 연령·성별은 전국 비율로 곱하고 `assumptions` 에 *"연령·성별은 전국 비율 대용"* 이라고 적는다. **완벽한 데이터를 기다리느라 W2를 넘기는 게 더 나쁘다.**

---

## 6. 검증 — 이걸 통과해야 다음 단계로 간다

`scripts/c2_check_dict.py` 로 만들어 매번 돌린다. **"잘 됐다" 대신 이 숫자들을 본다.**

```python
import json, pandas as pd

R = json.load(open("data/dict/admin/regions.json", encoding="utf-8"))
pop = pd.read_csv("data/dict/admin/population.csv", dtype={"code": str})

checks = {
    "시도 수 (기대 17)":        sum(1 for r in R["regions"].values() if r["level"] == "sido"),
    "시군구 수 (기대 250 안팎)": sum(1 for r in R["regions"].values() if r["level"] == "sigungu"),
    "읍면동 수 (기대 3,500 안팎)": sum(1 for r in R["regions"].values() if r["level"] == "emd"),
    "전국 인구 합 (기대 5,100만 안팎)": int(pop["population"].sum()),
    "인구 0인 읍면동":          sum(1 for r in R["regions"].values()
                                if r["level"] == "emd" and r["population"] == 0),
    "이름이 2곳 이상인 동":      sum(1 for v in R["name_index"].values() if len(v) > 1),
    "코드 길이 10 아닌 것":      sum(1 for c in R["regions"] if len(c) != 10),
    "sex 값 종류 (기대 2)":      pop["sex"].nunique(),
    "age_band 종류 (기대 21)":   pop["age_band"].nunique(),
}
for k, v in checks.items():
    print(f"{v:>12,}  {k}")
```

| 항목 | 통과 기준 | 안 맞으면 |
|---|---|---|
| 시도 수 | **17** | 세종·제주 처리 확인 |
| 전국 인구 합 | **5,000만~5,200만** | 합계 행을 안 버렸을 가능성이 크다(이중 계산) |
| 인구 0인 읍면동 | 전체의 5% 미만 | 행정동↔법정동 매칭 실패. `unmatched.csv` 확인 |
| 코드 길이 10 아닌 것 | **0** | `zfill(10)` 누락 또는 숫자 파싱 사고 |
| `sex` 종류 | **2** | 합계 컬럼이 섞였다 |
| 이름이 2곳 이상인 동 | 0이 아니어야 정상 | 0이면 `name_index` 가 잘못 만들어졌다 |

**손으로 하는 확인 3개**

```python
def lookup_by_name(R, name):
    """이름 → 코드 후보 목록. 단일 값을 반환하지 않는다."""
    return [R["regions"][c] for c in R["name_index"].get(name, [])]

lookup_by_name(R, "성수1가1동")   # 서울 성동구 하나만 나오는가
lookup_by_name(R, "중앙동")        # 여러 곳이 나오는가 (나와야 정상)
lookup_by_name(R, "없는동")        # 빈 리스트를 반환하는가 (예외를 던지면 안 된다)
```

---

## 7. 시설 사전 (W4) — 완벽하지 않아도 된다

**시설 → 행정코드 매핑**은 두 경로가 있다.

| 경로 | 방법 | 커버리지 |
|---|---|---|
| 표준데이터 | 공공데이터포털 CSV의 **주소 컬럼** → 앞부분 문자열로 행정구역 매칭 | 공원·학교·도서관 등 |
| **수동** | A에게 코퍼스 지명 목록을 받아 손으로 코드 부여 | 저수지·낚시터·동네 상권 등 |

```json
{
  "schema_version": "1.0",
  "facilities": {
    "신갈저수지": {"kind": "저수지", "codes": ["4146310100"], "confidence": 0.8,
                   "source": "manual", "note": "A 코퍼스 지명 목록"},
    "기흥호수":   {"kind": "호수",   "codes": ["4146310300"], "confidence": 0.8,
                   "source": "manual"}
  }
}
```

- `codes` 를 **배열로 둔다.** 시설이 여러 동에 걸치거나, 생활권이 인접 동을 포함하는 경우가 있다.
- `confidence` 는 §4 규칙 3의 신뢰도로 그대로 들어간다. 수동 매핑은 0.8, 주소 자동 매칭은 0.9 정도에서 시작한다.

> **폴백**: 시설 데이터가 안 구해지면 **수동 30개면 충분하다.** 우리 코퍼스에 등장하는 지명은 A가 설계 시점에 정한 목록이고, 그 목록 밖의 시설은 평가에 나오지 않는다. A에게 요청할 것: **"코퍼스에 쓸 지명·시설 목록"** 한 장.

---

## 8. 지명 사전 계약 초안 — D와의 회의에 이걸 들고 간다

> `docs/contracts/geo-dictionary.md` 로 저장한다. **신정현·박재현 공동 소유** — 변경에 2명 승인이 필요하다([contracts/README.md](../../contracts/README.md)).
> 회의는 **30분**이면 된다. 빈칸을 채우고 둘이 합의하면 끝이다.

```markdown
# 지명 사전 계약 (geo-dictionary)

> 공동 소유: C 신정현 · D 박재현
> 확정일: 2026-__-__ · dict_version: `geo-2026-07`

## 0. 왜 공동 소유인가

D의 가명화(`신갈동 → [경기 남부의 특정 동]`)와 C의 특정성 계산
(`신갈동은 몇 명으로 좁히나`)은 같은 사전을 요구한다.
**가명화기 = 특정성 엔진의 역함수.** 사전이 어긋나면 복원이 깨진다.

## 1. 키

| 항목 | 확정 |
|---|---|
| 키 | **행정코드 10자리 문자열** (`"4146310100"`) |
| 왜 문자열인가 | 숫자로 파싱하면 앞자리 0이 소실된다 |
| 계층 | 시도 · 시군구 · **읍면동까지**. 리는 쓰지 않는다 |
| 정본 | 인구통계(행정동) 기준. 법정동코드는 이름 검색 보조 |
| 이름 조회 | `name_index[이름] → 코드 배열`. **단일 값을 반환하지 않는다** |

## 2. 가명 라벨 형식

| 원 표현 | 축 | kind | 가명 라벨 | 복원 키 |
|---|---|---|---|---|
| 신갈저수지 | location | facility | `[시설A·저수지]` | `{"slot":"A","code":"4146310100"}` |
| 기흥호수 | location | facility | `[시설B·호수]` | `{"slot":"B","code":"4146310300"}` |
| 신갈동 | location | emd | `[경기 남부의 특정 동]` | `{"code":"4146310100"}` |
| 용인시 | location | sigungu | `[경기 남부의 특정 시]` | `{"code":"4146300000"}` |
| 마흔여덟 | age | age_exact | `[40대 후반]` | `{"value":48}` |
| 고1·중2 | family | child_grade | `[중고생 자녀 2명]` | `{"value":["고1","중2"]}` |

**권역 이름**(`경기 남부`)은 시도 + 방위로 고정한다. 시군구 이름을 넣지 않는다.

## 3. 슬롯 규칙 ⭐

- 슬롯 문자는 **사용자 단위로 유지**한다. 글이 바뀌어도 `신갈저수지 = 시설A` 는 그대로다.
- 같은 실제 대상은 항상 같은 슬롯. **이게 깨지면 2단이 "A와 B가 같은 생활권"을 판정할 수 없다.**
- 슬롯 테이블은 D가 소유하고, 세션(= 사용자 분석 1회) 안에서만 유효하다.

## 4. 복원

- 치환 시 **문자 offset을 함께 저장**한다. 문자열 치환만으로 되돌리면 반드시 깨진다.
- 복원 테이블은 **외부로 나가지 않는다.** 외부 LLM에 보내는 것은 가명 텍스트뿐이다
  ([RULES-DO-NOT #2](../RULES-DO-NOT.md)).

## 5. 파일

| 파일 | 소유 | 내용 |
|---|---|---|
| `data/dict/admin/regions.json` | C | 행정구역 계층 + 인구 |
| `data/dict/admin/population.csv` | C | 읍면동 × 연령 × 성별 |
| `data/dict/geo/facilities.json` | C | 시설 → 행정코드 |
| (런타임 메모리) 슬롯 테이블 | D | 가명 ↔ 원문 + offset |

## 6. 변경 절차

`docs/contracts/` 는 CODEOWNERS가 걸려 **2명 승인**이 필요하다.
`dict_version` 이 바뀌면 그 이전에 측정한 k값·기여도는 **재측정한다.**

## 7. 미결

- [ ] `age_band` 표기 (`40-44` 로 확정?)
- [ ] 권역 이름 목록 (수도권 / 경기 남부 / 충청 / …)
- [ ] 시설 kind 목록
```

---

## 9. 흔한 실수 4가지

| 실수 | 고치는 법 |
|---|---|
| 완벽한 데이터를 기다리다 주가 끝난다 | **L0(총인구만)으로 먼저 커밋한다.** 교차표는 W3에 붙여도 된다 |
| 라이선스를 나중에 적으려고 미룬다 | 받는 그 자리에서. 나중에는 어느 페이지였는지 기억이 안 난다 |
| 코드를 숫자로 다룬다 | `dtype=str` 을 습관으로. 엑셀로 열지 않는다 |
| 기준월이 파일마다 다르다 | 하나로 고정하고 `dict_version` 에 박는다 |

---

## 만들고 나면

1. 커밋 — `feat(c2): 행정구역 계층 사전 + 인구 교차표 (geo-2026-07)`
2. `data/README.md` 라이선스 표 갱신 확인
3. 검증 스크립트 출력을 주간보고에 한 줄로 (*"읍면동 3,4xx개 · 전국 인구 5,1xx만 · 미매칭 2.1%"*)
4. D와 `geo-dictionary.md` 합의 → E에게 계약 2종 제출
