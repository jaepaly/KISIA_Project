"""외부로 나가는 코드는 전부 이 파일에만 둔다.

발표 QnA "정말 안 나가나요"에 이 파일 하나로 답한다
(docs/roles/howto/e-integration.md §5). 기본 경로는 항상 차단.
"""

from __future__ import annotations

import os


def external_llm_allowed() -> bool:
    return os.getenv("ALLOW_EXTERNAL_LLM", "false").lower() == "true"


def call_external_llm(payload: dict):
    if not external_llm_allowed():
        raise RuntimeError("ALLOW_EXTERNAL_LLM=false — 외부 전송 차단 (RULES-DO-NOT #2)")
    if "body" in payload or "pseudonymized_body" not in payload:
        raise RuntimeError("원문 전송 시도 — 가명화된 본문만 넘긴다 (§4 원칙 2)")
    raise NotImplementedError("외부 LLM 연동 미구현 — 현재는 게이트만 있다")
