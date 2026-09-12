from kopl.c2_specificity.engine import _get_default_dictionary
from kopl.c2_specificity.facilities import load_stations, station_aliases, station_lookup


def test_every_station_code_exists_in_regions() -> None:
    regions = _get_default_dictionary().regions
    stations = load_stations()
    assert len(stations) >= 700
    for st in stations:
        assert st["emd"] in regions and regions[st["emd"]]["level"] == "emd"
        assert all(c in regions for c in st["near"])


def test_station_resolves_to_dong_and_scope_widens() -> None:
    hit = station_lookup("용마산역")
    assert hit and not hit.ambiguous and hit.codes == ("1126054000",)     # 서울 중랑구 면목제4동
    assert station_lookup("용마산") is not None                             # 역을 뗀 표면형도 같은 역
    near = station_lookup("용마산역", scope="near")
    assert near and set(near.codes) > set(hit.codes)


def test_same_name_in_several_cities_is_ambiguous() -> None:
    hit = station_lookup("시청역")
    assert hit and hit.ambiguous and hit.n_candidates >= 3 and hit.codes == ()
    assert station_lookup("없는역") is None


def test_transfer_station_is_one_record_with_all_lines() -> None:
    hit = station_lookup("태릉입구역")
    assert hit and not hit.ambiguous and len(hit.lines) == 2


def test_aliases_are_sorted_longest_first() -> None:
    a = station_aliases()
    assert a and len(a[0]) >= len(a[-1])
