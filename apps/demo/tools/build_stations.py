"""역 사전 만들기 — 도시철도 역 이름 → 행정동(읍면동) 코드.

    python apps/demo/tools/build_stations.py --stations <표준데이터 json> --bounds <행정동 geojson> --out data/dict/stations.json

입력 (둘 다 공개 자료, 키 없이 받는다)
  - 공공데이터포털 「전국도시철도역사정보표준데이터」(국가철도공단 취합) — 역 이름·노선·위경도·도로명주소. 898건, 기준일 2019~2021.
    https://www.data.go.kr/data/15013205/standard.do  (columList.json → standard.json, 페이지 1)
  - 행정동 경계 GeoJSON (vuski/admdongkor, 행안부 행정동 코드 adm_cd2 10자리) — 2026-07 판.
    https://github.com/vuski/admdongkor

방법
  - 역 좌표가 들어 있는 행정동 하나(`emd`)를 점-다각형 판정으로 고른다 (순수 파이썬, 의존성 없음).
  - 걸어서 닿는 범위로 `near`(반경 700m 안에 경계가 들어오는 행정동들)도 같이 둔다 — 역 하나를 동 하나로 볼지
    이웃 동까지 합칠지는 특정성 규칙의 판단(C)이라, 둘 다 실어서 쓰는 쪽이 고르게 한다.
  - 같은 이름의 역이 여러 도시에 있으면(시청·중앙·교대…) `ambiguous: true`. 맥락 없이 한 곳으로 못 박지 않는다.
  - 코드는 kopl.c2_specificity 의 regions.json 과 맞춘다. 경계 파일의 코드가 사전에 없으면(신설·개편) 이름으로 다시 찾고,
    그래도 없으면 시군구까지만 둔다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))


def _ring_contains(ring: list[list[float]], x: float, y: float) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-18) + xi:
            inside = not inside
        j = i
    return inside


def _poly_contains(poly: list[list[list[float]]], x: float, y: float) -> bool:
    if not _ring_contains(poly[0], x, y):
        return False
    return not any(_ring_contains(h, x, y) for h in poly[1:])


def _polys(geom: dict) -> list[list[list[list[float]]]]:
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def _bbox(polys) -> tuple[float, float, float, float]:
    xs = [p[0] for poly in polys for ring in poly for p in ring]
    ys = [p[1] for poly in polys for ring in poly for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """대략의 거리(m) — 짧은 거리라 등장방형 근사면 충분하다."""
    kx = 111_320 * math.cos(math.radians((lat1 + lat2) / 2))
    ky = 110_574
    return math.hypot((lon1 - lon2) * kx, (lat1 - lat2) * ky)


def _min_dist_to_polys(polys, lat: float, lon: float) -> float:
    """점에서 다각형 꼭짓점까지의 최소 거리(m). 변까지의 거리는 아니지만 700m 판정엔 충분하다."""
    best = float("inf")
    for poly in polys:
        for ring in poly:
            for x, y in ring:
                d = _meters(lat, lon, y, x)
                if d < best:
                    best = d
    return best


def norm(s: str) -> str:
    return unicodedata.normalize("NFC", s or "").strip()


def station_aliases(name: str) -> list[str]:
    """「용마산」 → 용마산역·용마산 · 「금곡역」 → 금곡역·금곡. 괄호 병기(「서울대입구(관악구청)」)는 앞만."""
    base = re.sub(r"\(.*?\)", "", norm(name)).strip()
    base = base[:-1] if base.endswith("역") and len(base) > 2 else base
    out = [base + "역", base]
    inner = re.findall(r"\((.*?)\)", norm(name))
    for x in inner:
        x = x.strip()
        if x and x not in out:
            out.append(x + "역" if not x.endswith("역") else x)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", required=True)
    ap.add_argument("--bounds", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--near-m", type=float, default=700.0)
    args = ap.parse_args()

    from kopl.c2_specificity.engine import _get_default_dictionary
    R = _get_default_dictionary().regions
    by_name_sgg: dict[tuple[str, str], list[str]] = defaultdict(list)
    for code, r in R.items():
        if r["level"] == "emd":
            by_name_sgg[(r["sigungu"], r["name"])].append(code)
    sgg_by_code = {code: r for code, r in R.items() if r["level"] == "sigungu"}

    feats = json.load(open(args.bounds, encoding="utf-8"))["features"]
    areas = []
    for f in feats:
        polys = _polys(f["geometry"])
        if not polys:
            continue
        areas.append((f["properties"], polys, _bbox(polys)))

    raw = json.load(open(args.stations, encoding="utf-8"))
    rows = []
    name_count: dict[str, set[str]] = defaultdict(set)
    unmatched_code = 0
    for r in raw:
        try:
            lat, lon = float(r["LATITUDE"]), float(r["LONGITUDE"])
        except (TypeError, ValueError):
            continue
        hit = None
        near = []
        pad = args.near_m / 100_000  # 도 단위 여유 (≈1.1km)
        for props, polys, (x0, y0, x1, y1) in areas:
            if not (x0 - pad <= lon <= x1 + pad and y0 - pad <= lat <= y1 + pad):
                continue
            if hit is None and any(_poly_contains(p, lon, lat) for p in polys):
                hit = props
            elif _min_dist_to_polys(polys, lat, lon) <= args.near_m:
                near.append(props)
        if hit is None:
            continue
        # 경계 코드 → 사전 코드
        code = hit["adm_cd2"]
        if code not in R:
            cands = by_name_sgg.get((hit["sggnm"], hit["adm_nm"].split()[-1]), [])
            code = cands[0] if len(cands) == 1 else None
            if code is None:
                unmatched_code += 1
        near_codes = []
        for p in near:
            c = p["adm_cd2"]
            if c not in R:
                cands = by_name_sgg.get((p["sggnm"], p["adm_nm"].split()[-1]), [])
                c = cands[0] if len(cands) == 1 else None
            if c and c not in near_codes and c != code:
                near_codes.append(c)
        sgg_code = (code[:5] + "00000") if code else None
        if sgg_code and sgg_code not in sgg_by_code:
            sgg_code = next((c for c, s in sgg_by_code.items() if s["name"] == hit["sggnm"] and s["sido"] == hit["sidonm"]), None)
        aliases = station_aliases(r["STATN_NM"])
        rows.append({
            "name": aliases[0], "aliases": aliases, "line": norm(r["ROUTE_NM"]), "operator": norm(r["INSTITUTION_NM"]),
            "lat": lat, "lon": lon,
            "emd": code, "emd_name": R[code]["full_name"] if code else hit["adm_nm"],
            "sigungu": sgg_code, "near": near_codes,
        })
        name_count[aliases[0]].add(hit["sggnm"] + "/" + hit["sidonm"])

    # 같은 이름의 역: 1.5km 안에 모여 있으면 환승역 하나(노선 합침 · 동 경계에 걸치면 near 로 합침),
    # 멀리 떨어져 있으면(서울 시청역 / 부산 시청역) 서로 다른 역이고 이름만으로는 못 정한다 → ambiguous
    by_name: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_name[row["name"]].append(row)
    out = []
    for name, group in by_name.items():
        clusters: list[list[dict]] = []
        for row in group:
            for cl in clusters:
                if any(_meters(row["lat"], row["lon"], o["lat"], o["lon"]) <= 1500 for o in cl):
                    cl.append(row)
                    break
            else:
                clusters.append([row])
        for cl in clusters:
            head = dict(cl[0])
            head["lines"] = []
            head["near"] = list(cl[0]["near"])
            for row in cl:
                if row["line"] not in head["lines"]:
                    head["lines"].append(row["line"])
                if row["emd"] and row["emd"] != head["emd"] and row["emd"] not in head["near"]:
                    head["near"].append(row["emd"])
                for c in row["near"]:
                    if c not in head["near"] and c != head["emd"]:
                        head["near"].append(c)
            head.pop("line", None)
            head["ambiguous"] = len(clusters) > 1
            out.append(head)
    out.sort(key=lambda x: (x["sigungu"] or "", x["name"]))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "_source": ["공공데이터포털 전국도시철도역사정보표준데이터 (국가철도공단, 기준일 2019~2021, 898건)",
                     "행정동 경계 vuski/admdongkor ver20260701 (행안부 adm_cd2)"],
        "_method": "역 좌표가 든 행정동 = emd · 반경 700m 안에 경계가 닿는 행정동 = near · 같은 이름이 다른 시군구에도 있으면 ambiguous",
        "_note": "역 하나를 동 하나로 볼지(emd) 이웃까지 합칠지(emd+near)는 특정성 규칙의 판단. 둘 다 실었다.",
        "stations": out,
    }
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    amb = sum(1 for s in out if s["ambiguous"])
    print(f"stations={len(out)} (from {len(raw)} rows) · emd unresolved={sum(1 for s in out if not s['emd'])} "
          f"· code-not-in-dict={unmatched_code} · ambiguous names={amb} → {args.out}")


if __name__ == "__main__":
    main()
