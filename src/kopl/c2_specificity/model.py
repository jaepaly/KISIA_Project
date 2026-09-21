"""C2 특정성 위험도 계산에 사용하는 축·해상도 상수."""

from __future__ import annotations

AXES = (
    "location",
    "age",
    "sex",
    "occupation",
    "family",
    "commute",
    "income",
)

# docs/roles/howto/c-engine.md §1의 정본 표.
# 0은 해당 축의 단서가 없거나 해상도를 확정하지 못한 상태다.
RESOLUTION: dict[str, dict[int, float]] = {
    "location": {0: 0.0, 1: 20.0, 2: 55.0, 3: 85.0, 4: 100.0},
    "age": {0: 0.0, 1: 40.0, 2: 70.0, 3: 100.0},
    "sex": {0: 0.0, 1: 60.0},
    "occupation": {0: 0.0, 1: 40.0, 2: 70.0, 3: 100.0},
    "family": {0: 0.0, 1: 30.0, 2: 55.0, 3: 85.0},
    "commute": {0: 0.0, 1: 40.0, 2: 75.0},
    "income": {0: 0.0, 1: 50.0},
}

# W6~W7에서 튜닝할 때 한 곳만 바꾸도록 별도 상수로 둔다.
WEIGHTS: dict[str, float] = {axis: 1.0 for axis in AXES}


# 골드 단서 등급은 해상도가 아니라 탐지 신뢰도로만 변환한다 (#261).
LEVEL_CONFIDENCE: dict[str, float] = {
    "explicit": 1.0,
    "implicit": 0.8,
    "inferential": 0.5,
}

REGION_LEVEL_RESOLUTION: dict[str, int] = {
    "sido": 1,
    "sigungu": 2,
    "emd": 3,
}

SPOUSE_TERMS = (
    "남편",
    "아내",
    "와이프",
    "배우자",
    "신랑",
    "신부",
)
