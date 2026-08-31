"""C2 특정성 계산 프로토타입."""

from .engine import RegionDictionary, classify_k, resolve, specificity

__all__ = [
    "RegionDictionary",
    "classify_k",
    "resolve",
    "specificity",
]