"""협회 게이트웨이(monorouter · Anthropic 호환) 연결 확인 — 주소 형태 × 인증 방식 × 모델 이름을 짧게 찔러 본다.
키 값은 출력하지 않는다. .env 만 읽는다."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "demo"))
from tools.compare_rewrite import load_env  # noqa: E402

load_env()
key = os.getenv("ANTHROPIC_API_KEY", "")
base = os.getenv("ANTHROPIC_BASE_URL", "").rstrip("/")
print("key present:", bool(key), "| base:", base)
import anthropic  # noqa: E402

bases = [base, base + "/v1"] if not base.endswith("/v1") else [base, base[:-3]]
models = ["claude-haiku-4-5-20251001", "claude-haiku-4-5", "claude-sonnet-4-5", "claude-3-5-haiku-latest"]
ok = None
for b in bases:
    for mode in ("api_key", "auth_token"):
        kw = {"base_url": b, mode: key}
        try:
            c = anthropic.Anthropic(**kw, max_retries=0, timeout=30)
            m = c.messages.create(model=models[0], max_tokens=16, messages=[{"role": "user", "content": "ping"}])
            print(f"OK   base={b} mode={mode} model={models[0]} -> {m.content[0].text[:30]!r}")
            ok = (b, mode)
            break
        except Exception as e:  # noqa: BLE001
            msg = str(e).replace(key, "***")[:160]
            print(f"FAIL base={b} mode={mode}: {e.__class__.__name__} {msg}")
    if ok:
        break
if ok:
    b, mode = ok
    c = anthropic.Anthropic(**{"base_url": b, mode: key}, max_retries=0, timeout=30)
    for mdl in models[1:]:
        try:
            c.messages.create(model=mdl, max_tokens=8, messages=[{"role": "user", "content": "ping"}])
            print("model ok:", mdl)
        except Exception as e:  # noqa: BLE001
            print("model no:", mdl, e.__class__.__name__, str(e).replace(key, "***")[:100])
    print("\n→ .env 에 맞춰 둘 값: ANTHROPIC_BASE_URL=" + b + " · 인증=" + mode)
