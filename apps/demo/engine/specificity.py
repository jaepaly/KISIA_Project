"""특정성 깔때기 — C 의 `kopl.c2_specificity` (지명 사전 + 주민등록 인구 교차표) 위에서 k 를 센다.

C 의 `specificity_l1(location, age, sex)` 은 «정답 조건» 을 받는 함수다. 데모는 정답을 모르고
스팬만 있으므로, 같은 사전·같은 교차표로 **조건을 하나씩 겹치며** 후보 수를 줄인다.
각 단계가 어느 글의 어느 스팬에서 왔는지 남긴다 — 화면의 「어떻게 좁혀지나」 가 이것이다.

k 의 뜻은 C 계약과 같다 — 조건에 해당하는 주민등록 인구 수. 크면 안전하다.
등급 경계(k≤2 VERY_HIGH · <5 HIGH · ≥5 ACCEPTABLE)도 C 의 `classify_k` 를 그대로 쓴다.

⚠️ 인구 교차표는 읍면동 행만 있다. 시도·시군구는 하위 읍면동을 합산한다.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from kopl.c2_specificity.dicts import pop_lookup
from kopl.c2_specificity.engine import (
    _get_default_dictionary,
    _get_default_population,
    age_to_band,
    classify_k,
)

from .dialect import REGION_SIDOS

_ALL_BANDS = ["0-4", "5-9", "10-14", "15-19", "20-24", "25-29", "30-34", "35-39", "40-44",
              "45-49", "50-54", "55-59", "60-64", "65-69", "70-74", "75-79", "80-84",
              "85-89", "90-94", "95-99", "100+"]

# 흔한 일반명사와 겹치는 시군구 약칭 — 사전 매칭에서 뺀다.
# 둘째 줄부터는 코퍼스 2,942편 실측 오탐 (한동안·경기 구경·수정·예산·사진도·이천 원·기장·상당히·진해서·거창한·영양제·유연제·인사하·보여주·저수지·출구로·옆구리·연남동·접은 양산).
_PLACE_STOPLIST = {"영광", "장수", "동해", "광명", "화성", "안성", "정선", "청도", "의성", "성주",
                   "고성", "남양", "동구", "서구", "남구", "북구", "중구", "강남", "강서", "강동",
                   "강북", "중랑", "동작", "서초", "송파", "마포", "광산", "달성", "수성",
                   "동안", "경기", "수정", "예산", "진도", "이천", "기장", "상당", "진해", "거창",
                   "영양", "연제", "사하", "여주", "수지", "구로", "구리", "남동", "양산"}


@lru_cache(maxsize=1)
def _index() -> dict[str, Any]:
    d = _get_default_dictionary()
    R = d.regions
    emd_by_sido: dict[str, list[str]] = {}
    emd_by_ancestor: dict[str, list[str]] = {}
    for code, r in R.items():
        if r["level"] != "emd":
            continue
        # 부모 사슬 전부에 등록한다 — 구가 있는 시(고양·용인·수원…)는 읍면동의 직계 부모가 구라서
        # 직계만 보면 시 코드 아래 읍면동이 0개가 된다 (세종은 읍면동의 부모가 시도다)
        p = r["parent"]
        while p:
            emd_by_ancestor.setdefault(p, []).append(code)
            if R[p]["level"] == "sido":
                emd_by_sido.setdefault(p, []).append(code)
                break
            p = R[p]["parent"]
    sido_by_name = {r["name"]: code for code, r in R.items() if r["level"] == "sido"}
    return {"R": R, "emd_by_sido": emd_by_sido, "emd_by_ancestor": emd_by_ancestor,
            "sido_by_name": sido_by_name, "dict_version": _dict_version()}


def _dict_version() -> str:
    import json
    from kopl.c2_specificity.engine import DEFAULT_REGIONS_PATH
    with open(DEFAULT_REGIONS_PATH, encoding="utf-8") as f:
        head = f.read(400)
    try:
        return json.loads(head.split('"dict_version": ')[1].split(",")[0])
    except Exception:  # noqa: BLE001
        return "geo-unknown"


def dict_version() -> str:
    return _index()["dict_version"]


def descendants(code: str) -> list[str]:
    """코드(시도·시군구·읍면동) 아래 읍면동 코드 전부."""
    ix = _index()
    if ix["R"][code]["level"] == "emd":
        return [code]
    return list(ix["emd_by_ancestor"].get(code, []))


def nation_codes() -> list[str]:
    ix = _index()
    return [c for codes in ix["emd_by_sido"].values() for c in codes]


def count(codes: list[str], sex: str | None = None, bands: list[str] | None = None) -> int:
    P = _get_default_population()
    total = 0
    for c in codes:
        v = pop_lookup(P, geo_code=c, sex=sex, age_bands=bands)
        if v:
            total += v
    return total


_SIDO_SHORT = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
               "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기",
               "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남",
               "전북특별자치도": "전북", "경상북도": "경북", "경상남도": "경남",
               "제주특별자치도": "제주", "전남광주통합특별시": "전남"}
_LEVEL_KO = {"emd": "읍면동", "sigungu": "시군구", "sido": "시도"}


def ancestors(canonical: str) -> list[dict[str, str]]:
    """정본 지명의 상위 행정구역을 가까운 것부터 — [{"text": 「김해시」, "canonical": 정본, "level": "시군구"}, …].
    구가 있는 시는 구 → 시 → 도 순으로 나온다. 풀리지 않는 이름이면 빈 목록."""
    ix = _index()
    codes = resolve_place(canonical)
    if len(codes) != 1:
        return []
    out = []
    p = ix["R"][codes[0]]["parent"]
    while p:
        r = ix["R"][p]
        text = _SIDO_SHORT.get(r["name"], r["name"]) if r["level"] == "sido" else r["name"]
        out.append({"text": text, "canonical": r["full_name"] if r["level"] != "sido" else r["name"],
                    "level": _LEVEL_KO.get(r["level"], r["level"])})
        p = r["parent"]
    return out


@lru_cache(maxsize=1)
def place_lexicon() -> tuple[tuple[str, str], ...]:
    """(표면형, 정본 이름) — 탐지기가 본문에서 찾을 지명 목록.

    시도는 약칭까지, 시군구는 접미사를 뗀 약칭(2자 이상)까지, 읍면동은 접미사 포함 전체만.
    """
    ix = _index()
    out: dict[str, str] = {}
    # 같은 이름이 전국에 여럿인 시군구·읍면동(중앙동 31곳 · 고성군 2곳)은 맥락 없이는 못 정한다 —
    # 정본 대신 이름만 두어 resolve 가 여러 후보를 내게 하고, 앞에 상위 지명이 붙어야(detect 의 합치기) 확정된다.
    dup: dict[str, int] = {}
    for r in ix["R"].values():
        if r["level"] != "sido":
            dup[r["name"]] = dup.get(r["name"], 0) + 1
    sido_short = _SIDO_SHORT
    for code, r in ix["R"].items():
        name = r["name"]
        if r["level"] == "sido":
            out[name] = name
            if name in sido_short and sido_short[name] not in _PLACE_STOPLIST:
                out[sido_short[name]] = name
        elif r["level"] == "sigungu":
            canon = r["full_name"] if dup[name] == 1 else name
            out[name] = canon
            short = name[:-1] if name[-1] in "시군구" and len(name) >= 3 else None
            if short and len(short) >= 2 and short not in _PLACE_STOPLIST and short not in out:
                out[short] = canon
        else:
            if len(name) >= 3 and name not in out:
                out[name] = r["full_name"] if dup[name] == 1 else name
    # 광주 — 경기 광주시와 전남광주통합특별시(옛 광주광역시)의 동명 지명. 사전이 한쪽으로 못 박지 않게
    # 정본 이름 대신 «동명» 표기를 두어 resolve 가 빈 목록을 내게 한다 (계약의 ambiguous 경로와 같은 뜻).
    out["광주"] = "광주 (동명 지명 — 경기 광주시 / 전남광주통합특별시)"
    # 긴 표면형부터 매칭되게 정렬
    return tuple(sorted(out.items(), key=lambda kv: -len(kv[0])))


def resolve_place(canonical: str) -> list[str]:
    """정본 이름 → 코드 후보. 시도 이름은 직접, 그 외는 C 의 resolve."""
    ix = _index()
    if canonical in ix["sido_by_name"]:
        return [ix["sido_by_name"][canonical]]
    from kopl.c2_specificity.engine import resolve
    return resolve(canonical)


# ── 깔때기 ────────────────────────────────────────────────────────────────

def funnel(signals: dict[str, Any]) -> dict[str, Any]:
    """조건을 겹쳐 k 를 센다.

    signals = {
      "dialect_region": "호남" | None,                     # {axis: location, kind: dialect_region}
      "admin_unit":  {"unit": "면", "src": {...}} | None,   # 「면사무소」 류 — 읍·면 단위 힌트
      "places": [ {"canonical": "전남광주통합특별시 담양군 창평면", "src": {...}}, ... ],  # 명시 지명·위치태그
      "age":    {"value": 68, "src": {...}} | {"min": 65, "src": {...}} | None,
      "sex":    {"value": "F", "src": {...}} | None,
    }
    src 는 {"post_id", "span_id", "text", "channel"} 꼴이며 화면 표시용이다.
    """
    ix = _index()
    steps: list[dict[str, Any]] = []
    codes = nation_codes()
    n = count(codes)
    steps.append({"axis": "nation", "condition": "전 국민(주민등록)", "n_after": n,
                  "method": "sum", "src": None})

    region = signals.get("dialect_region")
    if region and region in REGION_SIDOS:
        sido_codes = [ix["sido_by_name"][s] for s in REGION_SIDOS[region] if s in ix["sido_by_name"]]
        sub = [c for sc in sido_codes for c in descendants(sc)]
        if sub:
            codes = sub
            n = count(codes)
            steps.append({"axis": "location", "kind": "dialect_region", "condition": f"말투로 보아 {region} 지역",
                          "n_after": n, "method": "dialect_lexicon", "src": signals.get("dialect_src")})

    au = signals.get("admin_unit")
    if au:
        unit = au["unit"]
        suffixes = ("읍", "면") if unit == "읍면" else (unit,)
        sub = [c for c in codes if ix["R"][c]["name"].endswith(suffixes)]
        if sub and len(sub) < len(codes):
            codes = sub
            n = count(codes)
            steps.append({"axis": "location", "kind": "admin_unit",
                          "condition": f"{'·'.join(suffixes)} 단위 지역 (면사무소 같은 시설 언급)",
                          "n_after": n, "method": "name_suffix_filter", "src": au["src"]})

    # 명시 지명·위치태그 — 가장 좁은 것 하나를 택한다 (해석 불가·중의는 건너뛴다).
    # 크기가 같으면 이미 올라간 글의 것을 초안(draft)보다 먼저 — «올리기 전/후» 비교가 순서에 흔들리지 않게
    best: tuple[int, list[str], dict[str, Any]] | None = None
    for p in sorted(signals.get("places") or [], key=lambda x: (x.get("src") or {}).get("post_id") == "draft"):
        cands = resolve_place(p["canonical"])
        if len(cands) != 1:
            continue
        sub = [c for c in descendants(cands[0]) if c in set(codes)] or descendants(cands[0])
        if not sub:
            continue
        if best is None or len(sub) < len(best[1]):
            best = (len(sub), sub, p)
    if best:
        codes = best[1]
        n = count(codes)
        p = best[2]
        steps.append({"axis": "location", "kind": "admin_code",
                      "condition": f"지명 «{p['canonical']}»" + (" (위치태그)" if p["src"].get("channel") == "geo_tag" else ""),
                      "n_after": n, "method": "regions.json resolve", "src": p["src"]})

    bands: list[str] | None = None
    age = signals.get("age")
    if age and age.get("value") is not None:
        bands = [age_to_band(int(age["value"]))]
        cond = f"나이 {bands[0]}세 (5세 구간)"
    elif age and age.get("decade") is not None:
        d = int(age["decade"])
        bands = [b for b in _ALL_BANDS if b != "100+" and d <= int(b.split("-")[0]) < d + 10]
        cond = f"나이 {d}대"
    elif age and age.get("min") is not None:
        m = int(age["min"])
        bands = [b for b in _ALL_BANDS if b == "100+" or int(b.split("-")[0]) >= m]
        cond = f"나이 {m}세 이상"
    if bands:
        n = count(codes, None, bands)
        steps.append({"axis": "age", "condition": cond, "n_after": n,
                      "method": "crosstab_lookup", "src": age["src"]})

    sex = signals.get("sex")
    if sex and sex.get("value") in ("M", "F"):
        n = count(codes, sex["value"], bands)
        steps.append({"axis": "sex", "condition": "성별 " + ("여성" if sex["value"] == "F" else "남성"),
                      "n_after": n, "method": "crosstab_lookup", "src": sex["src"]})
    else:
        steps.append({"axis": "sex", "condition": "성별은 단서가 없어 남녀 합산",
                      "n_after": n, "method": "abstain", "src": None})

    k = max(1, n)
    return {"k": k, "k_level": classify_k(k), "steps": steps, "n_codes": len(codes)}


def risk_score(k: int | None, nation: int | None = None) -> int | None:
    """데모용 위험 점수 — 후보 수의 로그 척도. k=1 → 100, k=전국 → 0.

    2단 계약의 risk.current 자리에 넣는 값이다. 정식 위험도 모델(C contribution + D 추천)이
    아니라 화면용 환산이다. 화면에도 그렇게 적는다.
    """
    if not k:
        return None
    nation = nation or count(nation_codes())
    s = 100 * (1 - math.log10(k) / math.log10(nation))
    return int(round(max(0, min(100, s))))


def risk_label(k: int | None) -> tuple[str, str]:
    """(문구, css 등급). 등급 경계는 데모 표시용 — 계약 k_level 은 따로 보여준다."""
    if not k:
        return "산출 불가", "unk"
    if k <= 2:
        return "사실상 특정", "hi"
    if k < 5:
        return "위험 매우 높음", "hi"
    if k < 1000:
        return "위험 높음", "hi"
    if k < 100_000:
        return "위험 보통", "mid"
    return "위험 낮음", "low"
