"""C2 특정성 계산 프로토타입."""

from .clues import build_conditions, span_to_condition
from .engine import (
    RegionDictionary,
    age_to_band,
    classify_k,
    resolve,
    risk_by_axis,
    risk_total,
    specificity,
    specificity_l1,
)

__all__ = [
    "build_conditions",
    "RegionDictionary",
    "age_to_band",
    "classify_k",
    "resolve",
    "risk_by_axis",
    "risk_total",
    "specificity",
    "specificity_l1",
    "span_to_condition",
]