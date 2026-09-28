"""외부 LLM(Claude CLI) — inputs.jsonl 을 인물별로 1회씩 호출. findings 스키마 강제.

    python experiments/exp09-external-agreement/run_external.py [--pilot] [--model claude-sonnet-4-6]

- `claude -p --tools "" --setting-sources ""` : 도구·프로젝트 설정 없이 순수 생성만
- temperature 는 CLI 에서 지정할 수 없다 (README 한계). 재시도 없음 — 실패는 invalid 로 남긴다
- 이미 결과가 있는 인물은 건너뛴다 (중단 후 이어 돌리기)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
import hashlib

HERE = Path(__file__).resolve().parent
ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")
FINDING = {
    "type": "object",
    "required": ["verdict", "confidence", "cross_post", "evidence"],
    "additionalProperties": False,
    "properties": {
        "verdict": {"enum": ["specified", "narrowed", "weak_signal", "abstain"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "cross_post": {"type": "boolean"},
        "evidence": {"type": "array", "items": {
            "type": "object", "required": ["post_id", "span_id"], "additionalProperties": False,
            "properties": {"post_id": {"type": ["string", "null"]}, "span_id": {"type": "string"}}}},
    },
}
SCHEMA = {
    "type": "object", "required": ["findings", "rewrites"], "additionalProperties": False,
    "properties": {
        "findings": {"type": "object", "required": list(ATTRS), "additionalProperties": False,
                     "properties": {k: FINDING for k in ATTRS}},
        "rewrites": {"type": "array", "maxItems": 0},
    },
}


def gateway_env(env_file: Path) -> dict[str, str]:
    """팀 게이트웨이 키만 골라 하위 프로세스 env 로 — 개인 로그인(claude.ai) 대신 이 키로 나간다.
    같은 키가 여러 번 있으면 마지막 줄을 쓴다 (dotenv 관례). 값은 출력하지 않는다."""
    found: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(ANTHROPIC_API_KEY|ANTHROPIC_BASE_URL)\s*=\s*(.*)$", line)
        if m:
            found[m.group(1)] = m.group(2).strip().strip("\"'")
    if set(found) != {"ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"}:
        raise SystemExit(f"{env_file}: ANTHROPIC_API_KEY · ANTHROPIC_BASE_URL 둘 다 있어야 한다")
    url = urlparse(found["ANTHROPIC_BASE_URL"])
    # 공식 엔드포인트면 개인 API 키일 수 있다 — 팀 게이트웨이(별도 호스트 · https)만 허용
    if url.scheme != "https" or not url.hostname or url.hostname.endswith("anthropic.com"):
        raise SystemExit("ANTHROPIC_BASE_URL 이 팀 게이트웨이(https · anthropic.com 아님)가 아니다")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_"))}
    env.update(found)
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--env-file", required=True,
                    help="팀 게이트웨이 키가 든 .env (ANTHROPIC_API_KEY · ANTHROPIC_BASE_URL). 개인 계정으로 돌지 않게 필수")
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--timeout", type=int, default=180)
    a = ap.parse_args()
    data = HERE / "data"
    rows = [json.loads(l) for l in (data / "inputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.pilot:
        keep = set(json.loads((data / "pilot_ids.json").read_text(encoding="utf-8")))
        rows = [r for r in rows if r["persona_id"] in keep]
    out_path = data / ("external_pilot.jsonl" if a.pilot else "external.jsonl")
    done = set()
    if out_path.exists():
        done = {json.loads(l)["persona_id"] for l in out_path.read_text(encoding="utf-8").splitlines() if l.strip()}

    env = gateway_env(Path(a.env_file))
    schema = json.dumps(SCHEMA, ensure_ascii=False)
    with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as cfg, \
            out_path.open("a", encoding="utf-8") as f:
        # 빈 설정 폴더 — 개인 claude.ai 로그인이 API 키보다 우선하므로 격리해야 게이트웨이로 나간다 (실측 9/28)
        env["CLAUDE_CONFIG_DIR"] = cfg
        sp = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True,
                            encoding="utf-8", env=env, cwd=cwd)
        st = json.loads(sp.stdout) if sp.returncode == 0 else {}
        if st.get("authMethod") != "api_key" or st.get("apiKeySource") != "ANTHROPIC_API_KEY":
            raise SystemExit(f"게이트웨이 키로 인증되지 않음: authMethod={st.get('authMethod')} rc={sp.returncode}")
        # URL 자체는 남기지 않고 해시만 — 같은 게이트웨이로 돌았는지 재현 확인용
        url_sha = hashlib.sha256(env["ANTHROPIC_BASE_URL"].encode()).hexdigest()[:12]
        for r in rows:
            if r["persona_id"] in done:
                continue
            t0 = time.time()
            rec = {"persona_id": r["persona_id"], "model": a.model, "route": "kisia-gateway",
                   "gateway_url_sha256_12": url_sha, "findings": None, "error": None}
            try:
                p = subprocess.run(
                    ["claude", "-p", "--model", a.model, "--tools", "", "--setting-sources", "",
                     "--no-session-persistence", "--output-format", "json",
                     "--system-prompt", r["system"], "--json-schema", schema],
                    input=r["user"], capture_output=True, text=True, encoding="utf-8",
                    timeout=a.timeout, cwd=cwd, env=env,
                )
                if p.returncode != 0:
                    raise RuntimeError(f"claude rc={p.returncode}: {p.stderr[:160]}")
                d = json.loads(p.stdout)
                so = d.get("structured_output")
                if d.get("is_error") or not isinstance(so, dict) or "findings" not in so:
                    rec["error"] = f"no structured_output: {str(d.get('result'))[:200]}"
                else:
                    rec["findings"] = so["findings"]
                rec["served_model"] = list((d.get("modelUsage") or {}).keys())
                rec["cost_usd"] = d.get("total_cost_usd")
            except Exception as e:  # noqa: BLE001 — 실패도 결과로 남긴다
                rec["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            rec["sec"] = round(time.time() - t0, 1)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(r["persona_id"], "ok" if rec["findings"] else f"FAIL {rec['error']}", rec["sec"], "s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
