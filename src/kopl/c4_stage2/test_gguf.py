"""2단 GGUF 경로(Stage2GGUF) 검증 — 가짜 llama-server 로 돌린다 (GPU · GGUF · llama.cpp 없이).

실행:
    python -m pytest src/kopl/c4_stage2/test_gguf.py -v
"""

import json
import socket
import sys
import time
from pathlib import Path

import pytest

from kopl.c4_stage2 import infer
from kopl.c4_stage2.infer import (MODEL_VERSION, MODEL_VERSION_GGUF, RULES_VERSION, Stage2GGUF, analyze, chat_prompt,
                                  output_budget, build_user_prompt)
from kopl.c4_stage2.rules import ATTRS

USER = "u_0123abcd"
BODY = "마흔여덟 살 간호사예요."

# 가짜 llama-server — /health 는 바로 ok, /completion 은 받은 본문을 파일에 적고 정해진 답을 돌려준다.
# 인자는 진짜와 같게 받는다(-m <gguf> ... --host 127.0.0.1 --port N) — 받은 인자도 적어 둔다
FAKE_SERVER = r'''
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
args = sys.argv[1:]
port = int(args[args.index("--port") + 1])
host = args[args.index("--host") + 1]
log = args[args.index("-m") + 1] + ".log.jsonl"
answer = open(args[args.index("-m") + 1] + ".answer", encoding="utf-8").read()
with open(log, "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": args}) + "\n")
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        self._send({"status": "ok"})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"path": self.path, "body": body}, ensure_ascii=False) + "\n")
        self._send({"content": "  " + answer + "\n", "stop_type": "eos"})
HTTPServer((host, port), H).serve_forever()
'''


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _answer() -> str:
    findings = {a: {"verdict": "abstain", "confidence": 0.1, "cross_post": False, "evidence": []} for a in ATTRS}
    findings["age"] = {"verdict": "specified", "confidence": 0.9, "cross_post": False,
                       "evidence": [{"post_id": "p1", "span_id": "p1_s01"}]}
    return json.dumps({"findings": findings, "rewrites": []}, ensure_ascii=False)


@pytest.fixture()
def fake(tmp_path):
    gguf = tmp_path / "fake.gguf"
    gguf.write_bytes(b"GGUF fake weights")
    (tmp_path / "fake.gguf.answer").write_text(_answer(), encoding="utf-8")
    script = tmp_path / "fake_server.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    sha = infer._sha256(gguf)
    made = []

    def make(**kw):
        m = Stage2GGUF(gguf, command=[sys.executable, str(script)], sha256=sha, port=kw.pop("port", _free_port()),
                       start_timeout=30, **kw)
        made.append(m)
        return m

    def log():
        return [json.loads(l) for l in (tmp_path / "fake.gguf.log.jsonl").read_text(encoding="utf-8").splitlines()]

    yield make, log, gguf
    for m in made:
        m.close()


def _posts():
    age = BODY.index("마흔여덟")
    return [{"post_id": "p1", "texts": {"body": BODY}, "geo_tag": None, "spans": [
        {"span_id": "p1_s01", "text_id": "body", "start": age, "end": age + 4, "text": "마흔여덟",
         "type": "AGE", "level": "explicit", "subject": "self"}]}]


def test_generate_sends_greedy_chat_prompt_to_localhost(fake) -> None:
    make, log, gguf = fake
    m = make()
    assert m.generate("{\"x\": 1}", max_new_tokens=123) == _answer()   # 앞뒤 공백은 지운다 (HF 경로와 같게)
    rows = log()
    argv = rows[0]["argv"]
    assert argv[argv.index("--host") + 1] == "127.0.0.1" and "--no-webui" in argv
    assert argv[argv.index("-m") + 1] == str(gguf) and argv[argv.index("-np") + 1] == "1"
    body = rows[1]["body"]
    assert rows[1]["path"] == "/completion"
    assert body["prompt"] == chat_prompt(infer.SYSTEM_V2, "{\"x\": 1}")
    assert (body["n_predict"], body["temperature"], body["top_k"], body["cache_prompt"]) == (123, 0, 1, False)


def test_close_stops_server(fake) -> None:
    make, _, _ = fake
    m = make()
    port = m.port
    m.close()
    assert m._proc.poll() is not None
    time.sleep(0.2)
    assert not infer._port_open(port)
    with pytest.raises(RuntimeError, match="꺼져"):
        m.generate("{}")


def test_analyze_uses_budget_and_gguf_version(fake) -> None:
    make, log, _ = fake
    out = analyze(USER, _posts(), model=make(), mode="model")
    _, entries = build_user_prompt(USER, _posts(), cap=True)
    assert out["provenance"]["model_version"] == MODEL_VERSION_GGUF
    assert out["provenance"]["external_llm_used"] is False
    assert out["findings"]["age"]["verdict"] == "specified"
    assert log()[1]["body"]["n_predict"] == output_budget(entries)
    assert MODEL_VERSION_GGUF in infer.MODEL_VERSIONS and MODEL_VERSION in infer.MODEL_VERSIONS


def test_hash_mismatch_refused_before_start(fake, tmp_path) -> None:
    _, _, gguf = fake
    with pytest.raises(RuntimeError, match="GGUF 해시가 다르다") as e:
        Stage2GGUF(gguf, command=[sys.executable, "-c", "raise SystemExit(9)"], port=_free_port())
    assert infer._public_reason(e.value) == "GGUF 해시 불일치"
    assert not (tmp_path / "fake.gguf.log.jsonl").exists()   # 서버를 띄우지 않았다


def test_missing_files_have_fixed_reasons(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("STAGE2_GGUF", raising=False)
    with pytest.raises(FileNotFoundError) as e:
        Stage2GGUF()
    assert infer._public_reason(e.value) == "2단 GGUF 없음"
    gguf = tmp_path / "x.gguf"
    gguf.write_bytes(b"x")
    monkeypatch.delenv("LLAMA_SERVER", raising=False)
    with pytest.raises(FileNotFoundError) as e:
        Stage2GGUF(gguf)
    assert infer._public_reason(e.value) == "llama-server 없음"
    assert str(tmp_path) not in infer._public_reason(e.value)   # 응답에는 PC 경로가 실리지 않는다


def test_port_in_use_is_refused(fake) -> None:
    make, _, _ = fake
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        with pytest.raises(RuntimeError, match="포트가 이미") as e:
            make(port=s.getsockname()[1])
    assert infer._public_reason(e.value) == "llama-server 포트 사용 중"


def test_server_that_dies_fails_start(fake, tmp_path) -> None:
    _, _, gguf = fake
    with pytest.raises(RuntimeError, match="기동 실패"):
        Stage2GGUF(gguf, command=[sys.executable, "-c", "raise SystemExit(3)"], sha256=infer._sha256(gguf),
                   port=_free_port(), start_timeout=20)


def test_engine_selection_by_env(monkeypatch) -> None:
    made = []
    monkeypatch.setattr(infer, "Stage2Model", lambda: made.append("bnb") or "bnb")
    monkeypatch.setattr(infer, "Stage2GGUF", lambda: made.append("gguf") or "gguf")
    for value, want in ((None, "bnb"), ("", "bnb"), ("bnb", "bnb"), ("GGUF", "gguf")):
        if value is None:
            monkeypatch.delenv("STAGE2_ENGINE", raising=False)
        else:
            monkeypatch.setenv("STAGE2_ENGINE", value)
        assert infer._new_model() == want
    monkeypatch.setenv("STAGE2_ENGINE", "vllm")
    with pytest.raises(ValueError) as e:
        infer._new_model()
    assert infer._public_reason(e.value) == "2단 엔진 설정 오류"


def test_auto_falls_back_when_server_errors(fake) -> None:
    make, _, _ = fake
    m = make()
    m.close()   # 생성 중 서버가 죽은 경우
    out = analyze(USER, _posts(), model=m, mode="auto")
    assert out["provenance"]["model_version"] == f"{RULES_VERSION} (fallback: llama-server 꺼짐)"


def test_chat_prompt_matches_tokenizer_template() -> None:
    """토크나이저 템플릿과 글자까지 같다 — Qwen3-4B 토크나이저가 로컬 캐시에 있는 PC 에서만."""
    transformers = pytest.importorskip("transformers")
    try:
        tok = transformers.AutoTokenizer.from_pretrained(infer.BASE_MODEL, local_files_only=True)
    except Exception:  # noqa: BLE001
        pytest.skip("Qwen3-4B 토크나이저 없음")
    user, _ = build_user_prompt(USER, _posts(), cap=True)
    want = tok.apply_chat_template([{"role": "system", "content": infer.SYSTEM_V2}, {"role": "user", "content": user}],
                                   tokenize=False, add_generation_prompt=True, enable_thinking=False)
    assert chat_prompt(infer.SYSTEM_V2, user) == want
