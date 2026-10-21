"""LLMClient 회귀 — raon provider 설정 · 재시도 대기 (#393 리뷰). 네트워크 없이 urlopen 을 가짜로 바꿔 잰다."""
import email.message
import io
import urllib.error

import pytest

from kopl.c5_corpus import llm
from kopl.c5_corpus.llm import LLMClient, LLMError


def _http_error(code, retry_after=None):
    h = email.message.Message()
    if retry_after is not None:
        h["retry-after"] = str(retry_after)
    return urllib.error.HTTPError("https://x/v1/chat/completions", code, "err", h, io.BytesIO(b"{}"))


@pytest.fixture
def fake(monkeypatch):
    """urlopen 이 code 로 계속 실패하게 하고, sleep 한 초를 모은다."""
    state = {"calls": 0, "sleeps": []}

    def install(code, retry_after=None):
        def urlopen(req, timeout=None):
            state["calls"] += 1
            raise _http_error(code, retry_after)

        monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
        monkeypatch.setattr(llm.time, "sleep", lambda s: state["sleeps"].append(s))
        monkeypatch.setenv("RAON_API_KEY", "test")
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        return state

    return install


def test_raon_model_env(monkeypatch):
    monkeypatch.setenv("RAON_MODEL", "custom-preview")
    assert LLMClient("raon").model == "custom-preview"
    assert LLMClient("raon", model="explicit").model == "explicit"  # 명시한 인자가 이긴다
    assert LLMClient("gemini").model == llm.DEFAULT_MODELS["gemini"]  # 다른 provider 는 안 읽는다
    monkeypatch.delenv("RAON_MODEL")
    assert LLMClient("raon").model == "raon-1-mini-preview"


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_retry_after_is_honored(fake, code):
    st = fake(code, retry_after=4)
    with pytest.raises(LLMError):
        LLMClient("raon").complete("s", "u")
    assert st["calls"] == 3
    assert st["sleeps"] == [4, 4]  # max(1, 4) · max(2, 4)


def test_no_header_keeps_default_backoff(fake):
    st = fake(429)
    with pytest.raises(LLMError):
        LLMClient("gemini").complete("s", "u")
    assert st["sleeps"] == [1, 2]  # 기존 provider 대기를 바꾸지 않는다


def test_401_ignores_retry_after_and_uses_common_retry(fake):
    # 인증 실패도 기존 공통 재시도(3회 · 1 · 2초)를 탄다 — 바로 실패하지 않는다
    st = fake(401, retry_after=30)
    with pytest.raises(LLMError):
        LLMClient("raon").complete("s", "u")
    assert st["calls"] == 3
    assert st["sleeps"] == [1, 2]
