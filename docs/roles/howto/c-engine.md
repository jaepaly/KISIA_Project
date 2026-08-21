# 특정성·기여도 엔진 만들기

> **대상: C 신정현.** [C-specificity.md](../C-specificity.md)의 코드 편.
> 개념(축·감쇠·해상도)은 본 매뉴얼 §4·§5에 있다. **여기는 그걸 코드로 옮긴 것이다.**
> W3(L1) → W5(기여도) → W7(상관)에 걸쳐 쓴다.

---

## 0. 전체 흐름 한 장

```
글 집합 S
   │
   ├─ B의 스팬 + A의 라벨  →  Clue 목록 (축·kind·값·신뢰도·출처글)
   │
   ├─ 축별로 가장 좁은 조건 하나씩 고르기          ← 규칙 1
   │
   ├─ location × age × sex : 교차표 직접 조회      ← 규칙 2
   ├─ 나머지 축 : 신뢰도 가중 + 감쇠 곱             ← 규칙 3
   ├─ 하한 클램프 + floor_applied 기록              ← 규칙 4
   │        ↓
   │      k, level              (법적 정박)
   │
   └─ 축별 해상도 → 점수 → 가중합
            ↓
          risk 0~100            (서비스 점수)
                ↓
   글 하나씩 빼고 risk 재계산 = 기여도
```

> **핵심**: `risk` 는 **글이 아니라 단서 집합의 함수**다. 그래서 누적 곡선과 기여도가 같은 함수 하나에서 나온다. 따로 만들지 않는다.

**파일 배치**

```
src/kopl/c2_specificity/
    __init__.py
    model.py      Clue · 상수 테이블 (튜닝 손잡이가 전부 여기 모인다)
    dicts.py      regions.json · population.csv 로더
    engine.py     joint_k() · risk_total() · specificity()
src/kopl/c3_contribution/
    __init__.py
    loo.py        leave_one_out() · greedy_min_set()
    shapley.py    monte_carlo_shapley()   (W7~, 여유 시)
tests/
    test_c2_engine.py
    test_c3_contribution.py
```

---

## 1. 자료구조

```python
# src/kopl/c2_specificity/model.py
from dataclasses import dataclass

AXES = ["location", "age", "sex", "occupation", "family", "commute", "income"]
# ↑ A의 persona ground_truth 키와 같은 이름이다. 바꾸지 않는다.

@dataclass(frozen=True)          # frozen=True → 해시 가능 → frozenset·lru_cache에 넣을 수 있다
class Clue:
    clue_id: str                 # "R1-b07#0"
    post_id: str                 # "R1-b07"
    axis: str                    # AXES 중 하나
    kind: str                    # "facility" | "emd" | "sigungu" | "age_exact" | ...
    value: str                   # "신갈저수지"
    resolution: int = 0          # 해상도 단계 (0 = 미상). 계약의 conditions[].resolution 과 같은 값
                                 # ⚠️ 'level' 이라고 부르지 않는다 — 계약에서 level 은 위험 등급이다
    confidence: float = 1.0      # 0~1
    geo_code: str | None = None  # location 축일 때만
    ratio: float | None = None   # 비율 축(occupation 등)일 때 전국 비율 p
```

> **`frozen=True` 가 핵심이다.** 이게 있어야 `frozenset(clues)` 를 캐시 키로 쓸 수 있고, 그게 §4 캐싱의 전부다.

### 튜닝 손잡이 — 전부 한 파일에 모은다

```python
# src/kopl/c2_specificity/model.py (이어서)

ALPHA   = 0.6            # 감쇠 지수. 1.0 = 감쇠 없음(붕괴), 0에 가까울수록 안 좁혀짐
K_FLOOR = 1.0            # k 하한
N_KOREA = 51_000_000     # 기준 모집단 (인구통계 합계로 대체할 것)

# 축별 해상도 → 점수  (본 매뉴얼 §5 표)
RESOLUTION = {
    "location":   {0: 0, 1: 20, 2: 55, 3: 85, 4: 100},
    "age":        {0: 0, 1: 40, 2: 70, 3: 100},
    "sex":        {0: 0, 1: 60},
    "occupation": {0: 0, 1: 40, 2: 70, 3: 100},
    "family":     {0: 0, 1: 30, 2: 55, 3: 85},
    "commute":    {0: 0, 1: 40, 2: 75},
    "income":     {0: 0, 1: 50},
}
WEIGHTS = {a: 1.0 for a in AXES}

ENGINE_VERSION = "c2-0.1.0"
```

> **상수를 코드 여기저기에 흩어놓지 않는다.** W6~W7 튜닝은 이 파일 하나만 고치는 작업이어야 한다. 흩어지면 *"어제 뭘 바꿨더라"* 가 된다.

---

## 2. 사전 로더 — pandas 필터링을 dict로 바꾼다

```python
# src/kopl/c2_specificity/dicts.py
import json, csv
from collections import defaultdict
from pathlib import Path

ADMIN = Path("data/dict/admin")

def load_regions():
    return json.loads((ADMIN / "regions.json").read_text(encoding="utf-8"))

def load_population():
    """POP[code][sex][age_band] = 인구수  형태의 3중 dict"""
    pop = defaultdict(lambda: defaultdict(dict))
    with (ADMIN / "population.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pop[row["code"]][row["sex"]][row["age_band"]] = int(row["population"])
    return pop

def pop_lookup(POP, code=None, sex=None, age_bands=None, default=None) -> int:
    if code is None or code not in POP:
        return default
    by_sex = POP[code]
    sexes = [sex] if sex else list(by_sex.keys())
    total = 0
    for s in sexes:
        bands = by_sex.get(s, {})
        keys = age_bands if age_bands else bands.keys()
        total += sum(bands.get(b, 0) for b in keys)
    return total
```

> **왜 pandas를 안 쓰나.** `df[df.code == x]` 는 매번 7만 행을 훑는다. 기여도 계산은 조회를 수백~수천 번 하므로 여기가 느려지면 전체가 느려진다. **dict 조회는 상수 시간이다.** 사전 *만드는* 건 pandas로 하고, *쓰는* 건 dict로 한다.

---

## 3. k와 위험도

```python
# src/kopl/c2_specificity/engine.py
import math
from .model import (AXES, ALPHA, K_FLOOR, N_KOREA,
                    RESOLUTION, WEIGHTS, ENGINE_VERSION)
from .dicts import pop_lookup

AGE_BANDS = {          # age 단서 → 인구 교차표의 age_band 목록
    "20대": ["20-24", "25-29"], "30대": ["30-34", "35-39"],
    "40대": ["40-44", "45-49"], "50대": ["50-54", "55-59"],
    "40대 후반": ["45-49"], "40대 초반": ["40-44"],
}

def narrowest(clues, axis):
    """규칙 1 — 한 축에서 가장 좁은 조건 하나만. 곱하지 않는다."""
    cand = [c for c in clues if c.axis == axis]
    return max(cand, key=lambda c: (c.resolution, c.confidence)) if cand else None

def axis_levels(clues):
    lv = {a: 0 for a in AXES}
    for c in clues:
        lv[c.axis] = max(lv[c.axis], c.resolution)
    return lv

def risk_total(clues):
    """§5 — 축별 해상도를 점수로 바꿔 가중 평균"""
    lv = axis_levels(clues)
    num = sum(WEIGHTS[a] * RESOLUTION[a][lv[a]] for a in AXES)
    return num / sum(WEIGHTS.values())

def k_level(k) -> str:
    """계약 값은 영문 상수다 — 한글 "매우 높음"은 E가 화면에서 매핑한다.
       (docs/roles/howto/e-contracts.md §3-2 · E-system.md §3)"""
    if k is None: return "UNKNOWN"      # 산출 불가. 0을 쓰지 않는다
    n = math.floor(k)
    if n <= 2: return "VERY_HIGH"
    if n <= 4: return "HIGH"
    return "ACCEPTABLE"

def joint_k(clues, POP):
    steps = []

    # --- 규칙 2 : location × age × sex 는 교차표 직접 조회 -------------
    loc = narrowest(clues, "location")
    age = narrowest(clues, "age")
    sex = narrowest(clues, "sex")

    code  = loc.geo_code if loc else None
    bands = AGE_BANDS.get(age.value) if age else None
    sx    = sex.value if sex else None            # "M" / "F"

    n = None
    if code:
        n = pop_lookup(POP, code=code, sex=sx, age_bands=bands)
        steps.append({"axis": "location+age+sex",
                      "condition": f"{loc.value}({code}) / {age.value if age else '-'} / {sx or '-'}",
                      "n_after": n, "method": "crosstab_lookup"})
    if n is None:                                  # 지역 단서가 없으면 전국에서 시작
        n = float(N_KOREA)
        steps.append({"axis": "-", "condition": "지역 단서 없음",
                      "n_after": n, "method": "national_base"})

    n = float(n)

    # --- 규칙 3 : 나머지 축은 신뢰도 가중 + 감쇠 ------------------------
    for axis in ("occupation", "family", "commute", "income"):
        c = narrowest(clues, axis)
        if c is None or c.ratio is None:
            continue
        p  = max(min(c.ratio, 1.0), 1e-6)
        q  = 1.0 - c.confidence * (1.0 - p)        # 신뢰도가 낮으면 1에 가까워진다
        qd = q ** ALPHA                            # 감쇠
        n *= qd
        steps.append({"axis": axis, "condition": c.value,
                      "p": round(p, 4), "confidence": c.confidence,
                      "q_damped": round(qd, 4), "n_after": round(n, 1),
                      "method": "ratio_damped"})

    # --- 규칙 4 : 하한 + 플래그 ----------------------------------------
    floored = n < K_FLOOR
    return max(n, K_FLOOR), floored, steps

def specificity(clues, POP, dict_version: str):
    k, floored, steps = joint_k(clues, POP)
    lv = axis_levels(clues)
    return {
        "engine_version": ENGINE_VERSION,
        "dict_version": dict_version,
        "k": round(k, 1),
        "level": k_level(k),
        "risk": round(risk_total(clues), 1),
        "risk_by_axis": {a: RESOLUTION[a][lv[a]] for a in AXES},
        "floor_applied": floored,
        "steps": steps,
        "assumptions": [
            f"모집단: 주민등록 인구통계 {dict_version}",
            "location·age·sex 는 교차표 직접조회 (독립 가정 없음)",
            f"나머지 축은 전국 비율 × 신뢰도 × 감쇠(alpha={ALPHA})",
        ],
    }
```

**출력의 `steps` 를 반드시 채운다.** E의 화면에서 *"왜 이 점수인가"* 를 보여주는 데 쓰이고, 심사 질문에도 이걸로 답한다. 계산만 하고 과정을 안 남기면 **나중에 재구성할 수 없다.**

---

## 4. 기여도 — leave-one-out과 캐싱

```python
# src/kopl/c3_contribution/loo.py
from functools import lru_cache
from kopl.c2_specificity.engine import risk_total

# 단서 집합 → risk. 같은 집합이면 다시 계산하지 않는다.
@lru_cache(maxsize=200_000)
def _risk_cached(clues: frozenset) -> float:
    return risk_total(clues)

def risk_of_posts(post_ids, clue_index) -> float:
    """clue_index: {post_id: tuple[Clue, ...]}"""
    clues = frozenset(c for p in post_ids for c in clue_index.get(p, ()))
    return _risk_cached(clues)

def leave_one_out(post_ids, clue_index):
    base = risk_of_posts(post_ids, clue_index)
    rows = []
    for pid in post_ids:
        rest = [p for p in post_ids if p != pid]
        r = risk_of_posts(rest, clue_index)
        rows.append({
            "post_id": pid,
            "risk_without": round(r, 1),
            # ⚠️ 부호 — 계약의 delta 는 "이 글을 비공개했을 때의 변화"다. 내려가면 음수.
            #    (base - r) 로 쓰면 부호가 반대가 되고, 에러 없이 반대로 추천된다.
            "delta": round(r - base, 1),
            "clue_ids": [c.clue_id for c in clue_index.get(pid, ())],
        })
    rows.sort(key=lambda d: d["delta"])        # 가장 많이 내리는 글이 먼저
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return {"baseline_risk": round(base, 1), "contributions": rows}
```

> **`delta` 부호는 [E-system.md §3](../E-system.md)의 계약 규약이고, E의 목 엔진도 음수로 돌아간다.** 여기서 양수로 뱉으면 조치 화면이 *"이 글을 빼면 위험도가 올라간다"* 로 읽는다 — **검사기가 못 잡는 종류의 버그다.**

**캐시가 왜 이렇게 잘 듣나.** `risk` 는 *어느 글에서 왔는지* 와 무관하게 **단서 집합만** 보기 때문이다. leave-one-out에서 글을 하나 빼도 그 글의 단서가 다른 글에 중복돼 있으면 **집합이 그대로**이고, 캐시가 그대로 맞는다. 중복이 많은 실제 코퍼스일수록 캐시 적중률이 높다.

> ⚠️ **캐시는 사전 버전에 묶인다.** `dict_version` 이 바뀌면 `_risk_cached.cache_clear()` 를 호출하거나 프로세스를 다시 띄운다. 안 하면 옛 사전 값이 섞인다.

### 그리디 — 추천의 실물

```python
# src/kopl/c3_contribution/loo.py (이어서)
def greedy_min_set(post_ids, clue_index, target: float, max_remove: int = 5):
    """목표 위험도 이하로 내리는 최소 글 조합을 그리디로 찾는다.
       ⚠️ 기여도 상위 n개를 그냥 고르는 것과 다르다 — 매번 재계산한다."""
    remaining = list(post_ids)
    path, removed = [], []
    cur = risk_of_posts(remaining, clue_index)

    while cur > target and len(removed) < max_remove:
        best_pid, best_r = None, cur
        for pid in remaining:
            r = risk_of_posts([p for p in remaining if p != pid], clue_index)
            if r < best_r - 1e-9:
                best_pid, best_r = pid, r
        if best_pid is None:          # 어느 글을 빼도 안 내려간다 → 포화
            break
        remaining.remove(best_pid)
        removed.append(best_pid)
        cur = best_r
        path.append({"remove": best_pid, "risk_after": round(cur, 1)})

    return {
        "removed": removed,
        "greedy_path": path,
        "final_risk": round(cur, 1),
        "reached_target": cur <= target,
        "note": "greedy_path는 매 제거 후 재계산한 값이다. "
                "delta 상위 n개의 합과 일치하지 않는다",
    }
```

**`note` 를 출력에 실어 D에게 보낸다.** D가 이걸 모르면 추천 화면에 *"3개 빼면 −33"* 같은 잘못된 예상치가 뜬다.

**중단 조건 두 개를 다 넣는다** — 목표 도달, 그리고 **더 내려가지 않음(포화)**. 포화 감지가 없으면 무한히 글을 빼라고 추천하게 된다. 선행 PoC 자체 측정에서 누적 곡선이 5편 부근에서 포화했으므로 **실제로 자주 걸리는 분기다.**

### Shapley 근사 (W7~, 여유 시)

```python
# src/kopl/c3_contribution/shapley.py
import random
from .loo import risk_of_posts

def monte_carlo_shapley(post_ids, clue_index, n_perm=200, seed=0):
    """모든 순서로 글을 하나씩 넣어보고 평균 증가분을 그 글의 몫으로 본다.
       정확 계산은 2^n 이라 불가능 → 순열을 무작위로 n_perm개 뽑아 평균."""
    rng = random.Random(seed)          # 시드 고정 — 재현성이 지표다
    phi = {p: 0.0 for p in post_ids}
    empty = risk_of_posts([], clue_index)
    for _ in range(n_perm):
        order = list(post_ids)
        rng.shuffle(order)
        cur, prev = [], empty
        for pid in order:
            cur.append(pid)
            r = risk_of_posts(cur, clue_index)
            phi[pid] += r - prev
            prev = r
    return {p: round(v / n_perm, 2) for p, v in phi.items()}
```

**언제 leave-one-out 대신 이걸 쓰나.**

| 상황 | 증상 | 처방 |
|---|---|---|
| 단서가 여러 글에 **중복** | 기여도가 전부 0에 가깝다 | Shapley가 중복분을 나눠 갖는다 |
| 두 글이 **함께** 있어야 좁혀짐 | 개별 기여도가 실제보다 크게 나온다 | Shapley가 상호작용을 흡수한다 |
| 그 외 | — | **leave-one-out으로 충분하다** |

> **폴백**: Shapley는 [roadmap.md §5](../../roadmap.md)의 지표 3계층 어디에도 없다. **못 해도 [필수]·[목표] 지표는 전부 채워진다.** 시간이 없으면 건너뛰고, 발표에서 *"상호작용 보정은 향후 과제"* 로 한 줄 남긴다.

---

## 5. 계산량 감각 — 언제 느려지나

| 작업 | risk 평가 횟수 (글 n=19) | 비고 |
|---|---|---|
| leave-one-out | n+1 = **20** | 즉시 |
| 그리디 (5개까지) | 최대 n+(n−1)+… ≈ **90** | 즉시 |
| Shapley 200순열 | 200×n = **3,800** | 캐시로 실제 계산은 훨씬 적다 |
| exp8 (인물 100명 × 조치 4종 × 강도 4단계) | **수만** | 여기서 처음 체감된다 |

**느려지면 이 순서로 본다.**

1. **`pop_lookup` 이 pandas인가** → dict로 바꾼다 (§2). 대개 여기서 끝난다
2. **캐시가 켜져 있는가** → `_risk_cached.cache_info()` 로 hit율 확인
3. **`risk_of_posts` 가 매번 frozenset을 새로 만드는가** → 글별 단서를 미리 `frozenset` 으로 만들어두고 합집합만 취한다
4. 그래도 느리면 **Shapley의 `n_perm` 을 줄인다** (200 → 50). 순위는 거의 안 바뀐다

> **실시간일 필요가 없다.** 우리 제품의 지연 요구(< 300ms)는 **B의 1단 탐지**에 걸린 것이고([plan.md §10](../../plan.md)), 기여도 계산은 스캔 후 한 번 도는 배치다. **몇 초 걸려도 된다.**

---

## 6. 회귀 테스트 4종 — "잘 동작함" 대신 이걸 돌린다

```python
# tests/test_c3_contribution.py
import pytest
from kopl.c2_specificity.model import Clue
from kopl.c3_contribution.loo import risk_of_posts, leave_one_out

def test_monotone(fixture_index):
    """① 단조성 — 글을 추가하면 위험도가 줄지 않는다"""
    ids = list(fixture_index)
    prev = 0.0
    for i in range(1, len(ids) + 1):
        r = risk_of_posts(ids[:i], fixture_index)
        assert r >= prev - 1e-9, f"{i}편에서 위험도가 감소했다"
        prev = r

def test_deterministic(fixture_index):
    """② 결정성 — 같은 입력에 같은 출력"""
    ids = list(fixture_index)
    a = leave_one_out(ids, fixture_index)
    b = leave_one_out(list(reversed(ids)), fixture_index)
    assert a["baseline_risk"] == b["baseline_risk"]

def test_negative_control(n1_index):
    """③ 네거티브 — 신호 없는 글만 넣으면 위험도가 낮다"""
    assert risk_of_posts(list(n1_index), n1_index) < 15.0

def test_no_collapse(dense_clues, POP):
    """④ 붕괴 방지 — 조건을 6개 넣어도 k가 살아 있다"""
    from kopl.c2_specificity.engine import joint_k
    k, floored, _ = joint_k(frozenset(dense_clues), POP)
    assert k >= 1.0
    assert not floored, "6개 조건에서 하한이 걸렸다 → ALPHA를 올려라"
```

| # | 테스트 | 깨지면 무슨 뜻인가 |
|---|---|---|
| ① | **단조성** | 위험도 계산에 버그가 있다. 글이 늘었는데 위험이 줄 수는 없다 |
| ② | **결정성** | 딕셔너리 순회 순서·부동소수 누적 순서·시드 문제. 이게 깨지면 모든 수치가 무의미해진다 |
| ③ | **네거티브** | 과탐이다. *"아무 글에나 위험하다고 하는 것 아니냐"* 반박에 못 답한다 (선행 PoC 자체 측정 N1 = 8.8) |
| ④ | **붕괴 방지** | §4 규칙이 안 먹고 있다. ALPHA 또는 축 분리를 확인한다 |

**픽스처는 R1로 만든다.** A의 코퍼스를 기다리지 않는다 — R1의 글 19편 중 단서가 있는 4편(b01·b07·b12·b15)만 손으로 `Clue` 로 적어도 테스트는 돈다.

```python
# tests/conftest.py (발췌)
@pytest.fixture
def fixture_index():
    C = Clue
    return {
        "R1-b01": (C("R1-b01#0", "R1-b01", "location", "relative", "집에서 차로 십 분",
                     resolution=1, confidence=0.4),),
        "R1-b07": (C("R1-b07#0", "R1-b07", "location", "facility", "신갈저수지",
                     resolution=4, confidence=0.8, geo_code="4146310100"),),
        "R1-b12": (C("R1-b12#0", "R1-b12", "location", "facility", "기흥호수",
                     resolution=4, confidence=0.8, geo_code="4146310300"),),
        "R1-b15": (),   # 함정(지인 거주지) — 단서 없음으로 둔다
    }
```

> **b15는 함정이다.** A가 설계한 오답 유도용이고(*"동탄 사는 지인"*), 우리 엔진도 이걸 본인 거주지로 잡으면 안 된다. **함정 글의 기여도가 0으로 나오는지**가 좋은 확인 항목이다.

---

## 7. W7 상관 측정 — 윈도우 만들기

```python
# experiments/exp-0NN_risk_correlation/run.py
from scipy.stats import spearmanr

WINDOWS = [1, 2, 3, 5, 8, 12, 19]

def build_windows(persona_posts):
    """인물별로 시간순 정렬 후 앞에서부터 누적 윈도우"""
    out = []
    for pid, posts in persona_posts.items():
        posts = sorted(posts, key=lambda p: p["datetime"])
        for w in WINDOWS:
            if w <= len(posts):
                out.append({"persona": pid, "w": w,
                            "post_ids": [p["id"] for p in posts[:w]]})
    return out

# our = 우리 엔진 risk / llm = 교사 LLM이 맞힌 7속성 개수
rho, pval = spearmanr(our, llm)
print(f"Spearman rho={rho:.3f}  p={pval:.4f}  n={len(our)}")
```

| 항목 | 값 |
|---|---|
| 표본 단위 | **글 또는 윈도우.** 인물 단위는 n≈13이라 통계적으로 취약하다 |
| 표본 수 | 인물 10명 × 윈도우 7개 = **70개** 이상 |
| 교사 LLM 호출 | 윈도우당 1회 = **70회.** 크레딧 부담이 작다 |
| 부산물 | **누적 곡선이 그대로 나온다** (w별 평균 risk) |

> **0.7이 안 나오면** `WEIGHTS` 와 `RESOLUTION`(§1)을 조정한다. 그래도 안 되면 **한계로 기록한다.** [목표] 계층 지표이지 [필수]가 아니다([roadmap.md §5](../../roadmap.md)).
> ⚠️ **같은 데이터로 튜닝하고 같은 데이터로 보고하지 않는다.** 인물을 절반으로 나눠 한쪽으로 맞추고 다른 쪽으로 보고한다. 안 그러면 과적합이고, 심사에서 물어본다.

---

## 8. 튜닝 절차 (W6 연휴)

**손잡이는 셋뿐이다.** 한 번에 하나씩만 움직인다.

| 손잡이 | 무엇이 바뀌나 | 증상 → 방향 |
|---|---|---|
| `ALPHA` (0.6) | k가 얼마나 빨리 좁혀지나 | k가 자꾸 하한에 붙는다 → **내린다**(0.4) · 전부 "통상 허용" → **올린다**(0.8) |
| `RESOLUTION` | 속성별 점수 | 특정 속성이 상관을 망친다 → 그 축의 단계 간격을 좁힌다 |
| `WEIGHTS` | 속성 비중 | 어느 축이 실제 추론 성공과 상관이 높은지 보고 조정 |

```
후보 3세트를 만들어 표로 비교한다. 눈으로 고르지 않는다.

| 세트 | ALPHA | 변경 | Spearman | k 하한 걸린 비율 | N1 risk |
|------|-------|------|----------|------------------|---------|
| base | 0.6   | —    |          |                  |         |
| A    | 0.4   | —    |          |                  |         |
| B    | 0.6   | loc 가중 2배 |    |                  |         |
```

**기록을 남긴다.** `experiments/exp-0NN_tuning/results/metrics.json` 만 커밋하고 원본 로그는 커밋하지 않는다.

---

## 9. 막히면

| 상황 | 대처 |
|---|---|
| `risk` 가 항상 같은 값이다 | `resolution` 을 안 채웠을 가능성이 크다. `Clue.resolution` 기본값이 0이라 모두 미상으로 잡힌다 |
| `lru_cache` 에서 `unhashable type` | `Clue` 에 `frozen=True` 가 빠졌거나, 리스트를 인자로 넘겼다. `frozenset` 으로 감싼다 |
| 기여도가 음수로 나온다 | 정상일 수 있다(글을 빼서 오히려 오른 경우는 없어야 하지만, 함정 처리 로직이 있으면 생긴다). 단조성 테스트가 잡는다 |
| 사전을 바꿨는데 값이 그대로다 | 캐시. `_risk_cached.cache_clear()` |
| 어디까지 왔는지 모르겠다 | 본 매뉴얼 §7의 **사다리(L0~L4)** 로 자기 위치를 확인하고 주간보고에 한 줄 쓴다 |

---

## 참고

- [C-specificity.md](../C-specificity.md) — 개념·주차별 할 일·성공 기준
- [c-public-data.md](c-public-data.md) — 사전 만들기, 지명 사전 계약 템플릿
- [plan.md §5](../../plan.md) — 컴포넌트 ②③
- [roadmap.md §5](../../roadmap.md) — 지표 3계층 ([필수]인지 [목표]인지 확인)
- [RULES-DO-NOT.md #9](../../RULES-DO-NOT.md) — 수치에 측정일·데이터 버전·엔진 버전 붙이기
