"""외부 LLM 호출은 이 파일에서만 한다 (E-system.md §2 「한 파일에서만 · 게이트를 통과」).

기본값은 **꺼짐**이다. 켜려면 두 조건이 모두 필요하다 —
    DEMO_EXTERNAL_REWRITE=true   AND   OPENAI_API_KEY 가 있다.

켜지면 리라이트 후보 3안을 API 로 만들고, provenance.external_llm_used 가 true 가 된다.
꺼져 있으면 `recommend.py` 의 캐시·규칙 후보를 쓴다. 데모 페이지는 어느 쪽을 썼는지 표시한다.

⚠️ 보내는 것은 단서 문장 하나와 스팬 구간뿐이다. 글 전체·닉네임·user_ref 는 보내지 않는다.
   .env 의 ALLOW_EXTERNAL_LLM 기본값은 건드리지 않는다 — 이 게이트는 데모 전용 별도 스위치다.
"""

from __future__ import annotations

import json
import os
from typing import Any

MODEL = os.getenv("DEMO_EXTERNAL_MODEL", "gpt-4o-mini")


def enabled() -> bool:
    return os.getenv("DEMO_EXTERNAL_REWRITE", "").lower() == "true" and bool(os.getenv("OPENAI_API_KEY"))


def rewrite_candidates(sentence: str, span_text: str, voice_hint: str) -> list[dict[str, Any]] | None:
    """[{"text": 대체 표현, "note": 한 줄 설명}] ×3, 실패·비활성이면 None."""
    if not enabled():
        return None
    import requests

    system = ("너는 한국어 글의 프라이버시 리라이터다. 주어진 문장에서 표시된 구간만 바꾼다. "
              "말투·어미·방언은 그대로 두고, 신상(지명·행정단위·배차 간격·나이·소득 주기)이 새는 정보만 지운다. "
              "후보 3개를 낸다: ① 정보만 지운 최소 수정, ② 표현을 조금 더 바꾼 안, ③ 이유 자체를 바꾼 안. "
              'JSON 배열만 출력한다: [{"text": "...", "note": "..."}]')
    user = f"문장: {sentence}\n바꿀 구간: {span_text}\n말투 힌트: {voice_hint}"
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={"model": MODEL, "temperature": 0.7,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            timeout=30,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.strip("`").split("\n", 1)[1] if "\n" in content else content.strip("`")
        arr = json.loads(content)
        out = [{"text": str(a["text"]).strip(), "note": str(a.get("note", "")).strip()} for a in arr][:3]
        return out if len(out) == 3 else None
    except Exception:  # noqa: BLE001 — 데모는 외부 실패로 멈추지 않는다. 캐시로 떨어진다
        return None
