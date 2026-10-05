"""KISIA 팀 게이트웨이 .env 읽기 — 같은 키가 여러 줄이면 **비어 있지 않은 마지막 값**을 쓴다.

c5_corpus.llm.load_dotenv 는 먼저 읽은 값을 지켜서, 빈 줄(ANTHROPIC_API_KEY=)이 앞에 있으면 키가 없다고 나온다.
값은 출력하지 않는다.
"""
from __future__ import annotations

import os
from pathlib import Path


def load(path: str, keys: tuple[str, ...] = ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL")) -> dict[str, bool]:
    found: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("\"'")
        if k in keys and v:
            found[k] = v
    for k, v in found.items():
        os.environ[k] = v
    return {k: k in found for k in keys}
