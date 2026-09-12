"""시설 사전 — 1차: 도시철도 역 이름 → 행정동. `data/dict/admin/stations.json` 을 읽는다.

행정구역 사전(`engine.RegionDictionary`)은 «지명» 만 안다. 「용마산역 근처에 산다」 처럼 역·시설 이름이 단서일 때
그 시설이 놓인 읍면동으로 풀어 주는 것이 이 모듈이다. 엔진에 어떻게 물릴지(resolve 가 시설도 받게 할지, 별도 축으로 둘지)는
특정성 담당(C)이 정한다 — 여기서는 조회 함수만 둔다.

역 하나를 어느 범위로 볼지도 열어 둔다:
  - scope="emd"  : 역이 놓인 행정동 하나
  - scope="near" : 역 둘레 700m 안에 경계가 닿는 이웃 행정동까지 (걸어서 닿는 생활권)
같은 이름의 역이 여러 도시에 있으면(시청·중앙·교대 …) `ambiguous=True` 로 돌려주고 코드를 주지 않는다 —
행정구역 사전이 동명 지명을 한 곳으로 못 박지 않는 것과 같은 원칙이다.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DEFAULT_STATIONS_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "dict" / "admin" / "stations.json"
)


@dataclass(frozen=True)
class StationHit:
    name: str                       # 정본 역 이름 (…역)
    ambiguous: bool                 # 같은 이름의 역이 서로 다른 도시에 있는가
    n_candidates: int               # 후보 역 수 (ambiguous 일 때 2 이상)
    emd: str | None = None          # 역이 놓인 행정동 코드 (10자리)
    codes: tuple[str, ...] = ()     # scope 에 따른 행정동 코드 묶음
    lines: tuple[str, ...] = ()
    near: tuple[str, ...] = field(default_factory=tuple)


@lru_cache(maxsize=1)
def _load(path: str) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    by_alias: dict[str, list[dict]] = {}
    for st in doc["stations"]:
        for a in st["aliases"]:
            by_alias.setdefault(a, []).append(st)
    return {"by_alias": by_alias, "stations": doc["stations"], "meta": {k: v for k, v in doc.items() if k.startswith("_")}}


def load_stations(path: str | Path = DEFAULT_STATIONS_PATH) -> list[dict]:
    """역 레코드 전체. 필드: name · aliases · lines · operator · lat · lon · emd · emd_name · sigungu · near · ambiguous."""
    return _load(str(path))["stations"]


def station_aliases(path: str | Path = DEFAULT_STATIONS_PATH) -> list[str]:
    """탐지기가 사전 매칭에 쓸 표면형 전부 (「용마산역」「용마산」 …). 긴 것부터."""
    return sorted(_load(str(path))["by_alias"], key=len, reverse=True)


def station_lookup(
    text: str,
    scope: str = "emd",
    path: str | Path = DEFAULT_STATIONS_PATH,
) -> StationHit | None:
    """표면형 → 역. 모르는 이름이면 None. 동명 역이 여러 도시면 ambiguous=True 이고 codes 는 비어 있다."""
    key = unicodedata.normalize("NFC", text).strip()
    hits = _load(str(path))["by_alias"].get(key) or []
    if not hits:
        return None
    if len(hits) > 1 or hits[0].get("ambiguous"):
        return StationHit(name=hits[0]["name"], ambiguous=True, n_candidates=len(hits))
    st = hits[0]
    near = tuple(st.get("near") or [])
    codes = (st["emd"],) + (near if scope == "near" else ())
    return StationHit(name=st["name"], ambiguous=False, n_candidates=1, emd=st["emd"], codes=codes,
                      lines=tuple(st.get("lines") or []), near=near)
