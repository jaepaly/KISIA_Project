"""LLM provider 어댑터.

이슈 4-① 요구사항: 호출부만 갈아끼울 수 있게. 조립기(prompts.py)와
검증기(validate.py)는 경로와 무관하다.

  echo      키 없이 도는 스텁. 배선·비율 확인용.
  cli       로컬 CLI에 위임 (무료 Codex 등). --cli-cmd 로 명령 지정
  gemini    GEMINI_API_KEY (AI Studio)
  openai    OPENAI_API_KEY
  anthropic ANTHROPIC_API_KEY  ← 교사 라벨 전용. 생성에는 쓸 수 없다
  ollama    로컬 (OLLAMA_HOST)

이슈 1항: 생성에는 Claude 계열·Qwen 계열을 쓸 수 없다.
  Claude — 교사 라벨이 Claude다. 교사가 자기가 심은 단서를 회수하게 된다
  Qwen   — 2단 학습 대상이 Qwen3-4B다. 일치율 0.8이 부풀 수 있다
코드가 막는다. 실수로 손이 가는 자리라 주석이 아니라 예외로 둔다.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request

DEFAULT_MODELS = {
    "echo": "echo-dryrun",
    "cli": "cli-delegated",
    "gemini": "gemini-2.0-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "ollama": "llama3.1:8b",
}

# 생성 금지 계열 (이슈 1항). 교사 라벨·2단 런타임은 별도 스크립트라 여기서 막지 않는다.
BLOCKED_GENERATION = {
    "claude": "교사 라벨이 Claude 계열이다. 순환 편향으로 「추가 탐지율」이 무의미해진다",
    "anthropic": "교사 라벨이 Claude 계열이다. 순환 편향으로 「추가 탐지율」이 무의미해진다",
    "qwen": "2단 학습 대상이 Qwen3-4B다. 자기 계열 글을 더 잘 읽어 일치율이 부풀 수 있다",
}


def load_dotenv(path: str = ".env") -> int:
    """의존성 없이 .env 를 읽는다.

    bootstrap.sh 가 .env 를 만들어 주지만 파이썬은 그 파일을 자동으로 읽지 않는다.
    export 를 안 하고 .env 에만 키를 넣으면 os.environ 에 안 잡혀서
    "키를 넣었는데 없다고 나온다"가 된다. 이미 있는 환경변수는 덮지 않는다.
    """
    from pathlib import Path

    n = 0
    for base in (Path(path), Path(__file__).resolve().parent / path,
                 Path.cwd() / path):
        f = Path(base)
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("\"'")
            if k and k not in os.environ:
                os.environ[k] = v
                n += 1
        break
    return n


class LLMError(RuntimeError):
    pass


def check_generation_model(provider: str, model: str, cli_cmd: str = "") -> None:
    """생성 경로에 금지 계열이 들어왔는지 본다. 위반이면 실행 자체를 막는다."""
    blob = f"{provider} {model} {cli_cmd}".lower()
    for fam, why in BLOCKED_GENERATION.items():
        if fam in blob:
            raise LLMError(
                f"생성 모델로 '{fam}' 계열은 쓸 수 없다 — {why}\n"
                f"    (교차모델 배치: 생성 Gemini / 교사 Claude / 2단 Qwen3-4B)\n"
                f"    입력: provider={provider} model={model} {cli_cmd}"
            )


def list_models(provider: str) -> list[str]:
    """내 키로 실제 쓸 수 있는 모델 ID를 조회한다.

    모델 ID는 자주 바뀌고 무료 티어에서 빠지기도 한다. 추측해서 넣으면
    첫 호출이 404로 죽으므로 먼저 확인한다.
    """
    load_dotenv()
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise LLMError("GEMINI_API_KEY 없음")
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        out = []
        for m in data.get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                out.append(m["name"].removeprefix("models/"))
        return sorted(out)
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise LLMError("OPENAI_API_KEY 없음")
        req = urllib.request.Request(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        return sorted(m["id"] for m in data.get("data", []))
    raise LLMError(f"{provider} 는 모델 조회를 지원하지 않는다")


class LLMClient:
    def __init__(
        self,
        provider: str = "echo",
        model: str | None = None,
        temperature: float = 1.0,
        max_tokens: int = 4096,
        max_retries: int = 3,
        cli_cmd: str = "",
    ) -> None:
        if provider not in DEFAULT_MODELS:
            raise LLMError(f"모르는 provider: {provider}")
        self.provider = provider
        self.model = model or DEFAULT_MODELS[provider]
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.cli_cmd = cli_cmd
        self.calls = 0
        # 한도 소모 보고용 (이슈 5항: 20편에 몇 % 닳는지 → 3,000편 환산)
        self.usage = {"input_tokens": 0, "output_tokens": 0, "in_chars": 0, "out_chars": 0}
        self.elapsed = 0.0
        self.truncated = 0
        self._thinking_supported = True
        self.last_truncated = False

    @property
    def version(self) -> str:
        return f"{self.provider}:{self.model}"

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        self.last_truncated = False
        self.usage["in_chars"] += len(system) + len(user)
        t0 = time.time()
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                out = getattr(self, f"_{self.provider}")(system, user)
                self.usage["out_chars"] += len(out)
                self.elapsed += time.time() - t0
                return out
            except Exception as e:  # noqa: BLE001
                last = e
                if attempt < self.max_retries - 1:
                    time.sleep(2**attempt)
        self.elapsed += time.time() - t0
        raise LLMError(f"{self.version} 호출 실패: {last}")

    # ── providers ────────────────────────────────────────────────────
    def _echo(self, system: str, user: str) -> str:
        kind = "clue" if "심을 단서" in user else "ambient" if "지역 생활" in user else "noise"
        out = [
            "제목: 스텁",
            f"[ECHO 더미 · {kind} · 실제 생성물 아님] "
            "파이프라인 배선 확인용 문자열. provider를 바꾸면 실제 글로 대체된다.",
        ]
        # 캡션이 지정됐으면 그 수만큼 낸다 — parse 배선을 확인하기 위해서다
        import re as _re
        for i, _ in enumerate(_re.findall(r"^\s*캡션(\d+):", user, _re.M)):
            out.append(f"캡션{i}: 스텁 캡션")
        return "\n".join(out)

    def _cli(self, system: str, user: str) -> str:
        """무료 Codex 등 로컬 CLI에 위임. 프롬프트는 stdin으로 넘긴다.

            --provider cli --cli-cmd "codex exec -"
        """
        if not self.cli_cmd:
            raise LLMError("--cli-cmd 가 필요하다 (예: 'codex exec -')")
        parts = shlex.split(self.cli_cmd)
        # Windows 에서 codex 는 codex.CMD 다. CreateProcess 가 PATHEXT 를 해석하지
        # 않아 FileNotFoundError 가 난다. shutil.which 는 PATHEXT 를 본다.
        exe = shutil.which(parts[0]) or parts[0]
        r = subprocess.run(
            [exe] + parts[1:],
            input=f"{system}\n\n---\n\n{user}",
            capture_output=True,
            # text=True 는 로케일 인코딩을 쓴다. 한국어 Windows 는 cp949 라
            # 한글 프롬프트가 cp949 로 나가고 codex 가
            # «input is not valid UTF-8» 로 거부한다. 반드시 utf-8 로 고정한다.
            encoding="utf-8",
            errors="replace",
            # codex 는 API 가 아니라 에이전트라 한 호출에 수십 초~수 분이 걸린다
            timeout=600,
        )
        if r.returncode != 0:
            raise LLMError(f"CLI 실패(rc={r.returncode}): {r.stderr[:300]}")
        # ⚠️ codex 는 실패해도 rc=0 을 준다. 지원하지 않는 모델을 넘기면
        #    stderr 에만 ERROR 를 찍고 stdout 은 비운 채 0 으로 끝난다 —
        #    「The '<model>' model is not supported when using Codex with a
        #    ChatGPT account.」 (2026-09-02 실측, codex-cli 0.151.0)
        #    rc 만 보면 성공으로 읽혀 빈 글이 코퍼스에 들어간다.
        if not r.stdout.strip():
            tail = (r.stderr or "").strip().splitlines()
            hint = tail[-1][:300] if tail else "(stderr 도 비어 있다)"
            raise LLMError(
                f"CLI 가 rc=0 인데 응답이 비었다. stderr 마지막 줄: {hint}")
        return r.stdout

    def _gemini(self, system: str, user: str) -> str:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise LLMError("GEMINI_API_KEY 없음 (.env 확인)")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={key}"
        )
        gen_cfg = {
            "temperature": self.temperature,
            "maxOutputTokens": self.max_tokens,
        }
        # Gemini 3.x 는 기본적으로 사고에 토큰을 쓴다. 짧은 블로그 글에는 필요 없고
        # 그만큼 본문이 잘린다. 다만 모델·API 버전에 따라 이 필드를 거부한다
        # (400 INVALID_ARGUMENT). 거부당하면 빼고 한 번 더 시도한다.
        if self._thinking_supported:
            gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}

        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen_cfg,
        }
        try:
            data = self._post(url, body, {})
        except LLMError as e:
            if self._thinking_supported and "INVALID_ARGUMENT" in str(e):
                print("    (thinkingBudget 미지원 모델 — 해당 옵션 없이 재시도)")
                self._thinking_supported = False
                gen_cfg.pop("thinkingConfig", None)
                data = self._post(url, body, {})
            else:
                raise
        um = data.get("usageMetadata", {})
        self.usage["input_tokens"] += um.get("promptTokenCount", 0)
        self.usage["output_tokens"] += um.get("candidatesTokenCount", 0)
        self.usage["thinking_tokens"] = self.usage.get("thinking_tokens", 0) + um.get(
            "thoughtsTokenCount", 0
        )
        cand = data["candidates"][0]
        reason = cand.get("finishReason", "")
        if reason and reason not in ("STOP", "FINISH_REASON_STOP"):
            # MAX_TOKENS 면 글이 중간에 끊긴 것이다. 조용히 넘기면 잘린 글이 코퍼스에 들어간다
            self.truncated += 1
            self.last_truncated = True
            print(f"    ⚠ 응답이 끊겼다 (finishReason={reason})")
        return "".join(
            p.get("text", "")
            for p in cand.get("content", {}).get("parts", [])
        )

    def _openai(self, system: str, user: str) -> str:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise LLMError("OPENAI_API_KEY 없음 (.env 확인)")
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        data = self._post(
            "https://api.openai.com/v1/chat/completions",
            body,
            {"Authorization": f"Bearer {key}"},
        )
        u = data.get("usage", {})
        self.usage["input_tokens"] += u.get("prompt_tokens", 0)
        self.usage["output_tokens"] += u.get("completion_tokens", 0)
        return data["choices"][0]["message"]["content"]

    def _anthropic(self, system: str, user: str) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY 없음")
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        data = self._post(
            "https://api.anthropic.com/v1/messages",
            body,
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        u = data.get("usage", {})
        self.usage["input_tokens"] += u.get("input_tokens", 0)
        self.usage["output_tokens"] += u.get("output_tokens", 0)
        return "".join(b.get("text", "") for b in data.get("content", []))

    def _ollama(self, system: str, user: str) -> str:
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        body = {
            "model": self.model,
            "system": system,
            "prompt": user,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        return self._post(f"{host}/api/generate", body, {})["response"]

    @staticmethod
    def _post(url: str, body: dict, headers: dict) -> dict:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise LLMError(f"HTTP {e.code}: {e.read().decode('utf-8')[:300]}") from e

    # ── 한도 환산 (이슈 5항) ──────────────────────────────────────────
    def burn_report(self, posts_done: int, target_posts: int = 3000) -> str:
        if not posts_done:
            return "호출 없음"
        u = self.usage
        tok = u["input_tokens"] + u["output_tokens"]
        # 토큰을 안 주는 경로(cli/ollama)는 문자수로 근사한다 (한국어 ~1.5자/토큰)
        est = tok or int((u["in_chars"] + u["out_chars"]) / 1.5)
        per = est / posts_done
        think = u.get("thinking_tokens", 0)
        lines = [
            f"  측정: {posts_done}편 / 호출 {self.calls}회 / {self.elapsed:.0f}초",]
        if think:
            lines.append(f"  ⚠ 사고 토큰 {think:,} — 본문이 잘릴 수 있다")
        if self.truncated:
            lines.append(f"  ⚠ 끊긴 응답 {self.truncated}건 — 해당 글은 다시 뽑아야 한다")
        lines += [
            f"  토큰: {est:,} ({'실측' if tok else '문자수 근사'}) · 편당 {per:,.0f}",
            f"  {target_posts:,}편 환산: 약 {per * target_posts:,.0f} 토큰",
            f"  소요시간 환산: 약 {self.elapsed / posts_done * target_posts / 60:.0f}분",
        ]
        return "\n".join(lines)
