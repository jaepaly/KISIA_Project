"""글쓰기 화면 계정 점검 — 빠른 결과 먼저 · 정밀 판정(2단 모델) 뒤따라.

분석 서버가 모델을 쓸 수 있으면 ?progressive=1 점검이 항목별 판정을 규칙으로 먼저 내고(stage2_followup),
pado.js padoFollow 가 /api/stage2-followup 을 물어 바뀐 항목을 화면에 표시한다. 모델을 못 쓰는 서버는 그 칸이 없어 지금과 같다.
padoFollow 는 node 로 가짜 fetch 를 붙여 실제로 돌려 본다(node 가 없으면 그 테스트만 건너뛴다).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import db as dbmod
    live = tmp_path / "sns.db"
    c = dbmod.connect(live)
    dbmod.init(c)
    c.close()
    monkeypatch.setenv("SNS_DB_PATH", str(live))
    monkeypatch.delenv("SNS_SEED_DB", raising=False)
    monkeypatch.delenv("SNS_SESSION_DIR", raising=False)
    import app as appmod
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def test_new_page_opts_in_and_follows(client):
    html = client.get("/new").get_data(as_text=True)
    assert '/static/pado.js?v=406' in html
    # 계정 점검 두 경로(같은 출처 /scan · 다른 출처 /upload) 모두 빠른 결과를 묻는다 · 예상 시간도 빠른 결과 기준
    assert "/scan/${encodeURIComponent(m.user_ref)}${window.PADO_PROGRESSIVE}" in html
    assert "padoCheckExport(ex, ctrl.signal, prog.setAhead, window.PADO_PROGRESSIVE)" in html
    assert "/sns/estimate/${encodeURIComponent(me.user_ref)}${window.PADO_PROGRESSIVE}" in html
    # 「함께 점검」(초안 합산)은 항목별 판정을 쓰지 않아 지금처럼 묻지 않는다
    assert "padoCheckExport(ex, sig)" in html
    assert "followModel(g, m, key)" in html and "stopFollow()" in html
    for words in ("빠른 결과(규칙)예요", "정밀 판정이 끝났어요", "판정이 바뀐 항목", "정밀 판정을 받지 못해", "정밀 판정을 기다리는 점검이 많아",
                  "실제 정보가 맞다는 뜻은 아니에요"):
        assert words in html, words


def test_pado_js_keeps_default_single_response():
    js = (HERE / "static" / "pado.js").read_text(encoding="utf-8")
    assert 'async function (exportObj, signal, onAhead, query = "")' in js   # 기본은 지금처럼 /upload 한 번
    assert 'window.PADO_PROGRESSIVE = "?progressive=1"' in js
    # 새 요청은 분석 서버(BASE)의 상대 경로뿐 — 외부 요청 0건
    block = js[js.index("window.padoFollow"):js.index("window.padoDiffFindings")]
    assert "${BASE}/api/stage2-followup" in block and "http" not in block.replace("${BASE}", "")


NODE = shutil.which("node")

_HARNESS = r"""
const fs = require("fs");
globalThis.window = globalThis;
globalThis.PADO_BASE = "/check";
const answers = JSON.parse(process.argv[2]);
const asked = [];
let aborted = 0;
globalThis.fetch = async (url, opts) => {
  asked.push(url);
  const a = answers.length > 1 ? answers.shift() : answers[0];
  if (a === "error") throw new Error("net");
  // hang — 연결만 붙잡힌 서버: 취소 신호를 받아야만 끝난다 · hang_forever — 취소 신호도 무시한다
  if (a === "hang") return new Promise((_, rej) => opts.signal.addEventListener("abort", () => { aborted++; rej(new Error("abort")); }));
  if (a === "hang_forever") return new Promise(() => {});
  return { ok: true, json: async () => a };
};
eval(fs.readFileSync(process.argv[1], "utf8"));
const states = [];
const realSet = setTimeout;
globalThis.setTimeout = (fn, ms) => realSet(fn, Math.max(1, Math.round(ms / 1000)));   // 1000배 빠르게(2초 → 2ms · 마감 300초 → 300ms)
const t0 = Date.now();
window.padoFollow({ job: "abcdefghijklmnopqrstuvwx", est_seconds: 5 }, (s) => {
  states.push(s);
  if (!["pending", "running"].includes(s.status)) {
    const diff = s.findings ? window.padoDiffFindings({ age: { verdict: "abstain" }, location: { verdict: "narrowed", granularity: "sido" } }, s.findings) : null;
    console.log(JSON.stringify({ states, asked: asked.slice(0, 3), n_asked: asked.length, diff, aborted, ms: Date.now() - t0 }));
    process.exit(0);
  }
});
realSet(() => { console.log(JSON.stringify({ states, stuck: true })); process.exit(0); }, 5000);
"""


def _run_follow(answers):
    if not NODE:
        pytest.skip("node 없음")
    out = subprocess.run([NODE, "-e", _HARNESS, str(HERE / "static" / "pado.js"), json.dumps(answers)],
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_follow_reports_queue_then_model_findings():
    findings = {"age": {"verdict": "narrowed"}, "location": {"verdict": "narrowed", "granularity": "sido"}}
    r = _run_follow([{"status": "pending", "ahead": 1}, {"status": "pending", "ahead": 1}, {"status": "running", "ahead": 0},
                     {"status": "done", "findings": findings, "model_version": "m"}])
    assert [s["status"] for s in r["states"]] == ["pending", "running", "done"]   # 같은 차례는 한 번만 알린다
    assert r["states"][0]["ahead"] == 1
    assert r["asked"][0] == "/check/api/stage2-followup?job=abcdefghijklmnopqrstuvwx"
    assert r["diff"] == [{"attr": "age", "from": "abstain", "to": "narrowed", "from_granularity": None,
                          "to_granularity": None}]   # 바뀐 항목만


@pytest.mark.parametrize("answer, status", [({"status": "fallback", "reason": "x"}, "fallback"), ({"status": "failed"}, "failed"),
                                            ({"status": "unknown"}, "lost"), ("error", "lost")])
def test_follow_ends_on_failure(answer, status):
    r = _run_follow([answer])
    assert r["states"][-1]["status"] == status and "findings" not in r["states"][-1]


def test_follow_diff_reports_granularity_change():
    """판정이 같아도 범위가 바뀌면 바뀐 항목이다 — 분석기 diffFindings 와 같은 기준 (Codex P2)"""
    findings = {"age": {"verdict": "abstain"}, "location": {"verdict": "narrowed", "granularity": "sigungu"}}
    r = _run_follow([{"status": "done", "findings": findings, "model_version": "m"}])
    assert r["diff"] == [{"attr": "location", "from": "narrowed", "to": "narrowed", "from_granularity": "sido",
                          "to_granularity": "sigungu"}]


def test_new_page_shows_granularity_in_diff():
    html = (HERE / "templates" / "new.html").read_text(encoding="utf-8")
    assert "vFmt(x.from, x.from_granularity)" in html and "vFmt(x.to, x.to_granularity)" in html
    js = (HERE / "static" / "pado.js").read_text(encoding="utf-8")
    assert "window.padoGrainLabel" in js


def test_follow_aborts_stalled_requests():
    """묻기가 멈추면(응답 없이 연결만 유지) 요청마다 취소하고 다시 묻다가 실패 한도에서 끝난다 (Codex P2)"""
    r = _run_follow(["hang"])
    assert not r.get("stuck"), r
    assert r["states"][-1]["status"] == "lost"
    assert r["aborted"] >= 1 and r["n_asked"] >= 2


def test_follow_deadline_fires_even_if_request_never_returns():
    """취소 신호도 무시하는 요청이어도 전체 마감 타이머가 끝낸다"""
    r = _run_follow(["hang_forever"])
    assert not r.get("stuck"), r
    assert r["states"][-1]["status"] == "lost" and r["n_asked"] == 1
