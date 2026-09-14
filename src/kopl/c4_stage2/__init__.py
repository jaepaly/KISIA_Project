"""C4 2단 추론·조치 — 가명화·복원 계층."""

from .anonymize import TYPE_LABELS, anonymize, restore

__all__ = [
    "TYPE_LABELS",
    "anonymize",
    "restore",
]
