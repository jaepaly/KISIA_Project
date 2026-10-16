"""1단 예측 jsonl 읽기 — D 하류 단계(d_stage2 · d_risk_action · d_downstream)가 같이 쓴다.

한 줄 = ``{"post_id": str, "spans": [ {...}, ... ]}``. 형식이 다르면 **조용히 비우지 않고 멈춘다** (#359 B 리뷰):
- ``spans`` 가 없거나 리스트가 아니면 오류 — 예: exp06 의 ``candidates`` 형식을 그대로 넣은 경우.
  탐지가 정말 없는 글은 ``"spans": []`` 로 적는다(그건 정상)
- 스팬 하나하나는 객체(dict)여야 한다
- 같은 ``post_id`` 가 두 번 나오면 오류 — 뒤 줄이 앞 줄을 덮어 결과가 바뀌는 것을 막는다
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_pred_rows(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for no, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        where = f"{path}:{no}"
        if not isinstance(row, dict):
            raise ValueError(f"{where} — 한 줄은 JSON 객체여야 한다")
        pid = row.get("post_id")
        if not isinstance(pid, str) or not pid:
            raise ValueError(f"{where} — post_id 가 없거나 문자열이 아니다")
        if "spans" not in row:
            keys = ", ".join(sorted(row)) or "없음"
            raise ValueError(f"{where} ({pid}) — spans 필드가 없다 (있는 키: {keys}). "
                             "탐지가 없는 글은 \"spans\": [] 로 적는다")
        spans = row["spans"]
        if not isinstance(spans, list):
            raise ValueError(f"{where} ({pid}) — spans 가 리스트가 아니다 ({type(spans).__name__})")
        if not all(isinstance(s, dict) for s in spans):
            raise ValueError(f"{where} ({pid}) — spans 안의 스팬은 객체여야 한다")
        if pid in seen:
            raise ValueError(f"{where} ({pid}) — 같은 post_id 가 {seen[pid]}번째 줄에도 있다")
        seen[pid] = no
        rows.append(row)
    return rows
