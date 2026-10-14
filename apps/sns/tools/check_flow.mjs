// 처음부터 끝까지 눌러 보는 브라우저 검사 — Veilo 홈 → 내 글 점검(계정 고르기) → 점검 → 점검 결과 → 위험 줄이기 · 파일 올려 점검.
// check_motion.mjs(소개 화면 연출)와 짝이다. 버튼 하나가 통째로 죽는 회귀(10/14 · 「공개 글 점검」이 요청을 안 보내던 것)를 잡으려고 만들었다.
// pytest 에는 넣지 않는다(CI 에 크롬이 없다). 외부 패키지 없음 — Node 22 내장 fetch · WebSocket 으로 CDP 에 붙는다.
//
// 실행 방법
//   1) 분석기:  ENGINE_MODE=mock SNS_BASE_URL=http://127.0.0.1:3020 SNS_PUBLIC_URL=http://localhost:3020 PYTHONPATH=src uvicorn apps.analyzer.server:app --port 8020
//      (Windows 는 SNS_BASE_URL 을 localhost 대신 127.0.0.1 로 — localhost 는 IPv6 를 먼저 시도해 부를 때마다 2초씩 늦다)
//   2) Veilo:   PADO_BASE=http://localhost:8020 SNS_PORT=3020 python apps/sns/app.py
//   3) 크롬:    check_motion.mjs 머리말과 같다 (--remote-debugging-port=9333 · 헤드리스)
//   4) node apps/sns/tools/check_flow.mjs [--port 9333] [--base http://localhost:3020] [--pado http://localhost:8020]
// 결과는 JSON 한 덩어리 { ok, failed, results:[{ step, check, ok, got, want }] } — 하나라도 실패면 종료 코드 1.
//
// 검사: 홈 상단바 「내 글 점검」 → scan.html · 계정 목록 12명 · 고르면 예상 시간 · 「공개 글 점검」을 누르면 요청이 나가고
//       (느린 네트워크로) 버튼이 「점검 중…」 · 진행 띠가 차오르는 막대 · 결과 화면 도착 · 「위험 줄이기 →」 → 위험 줄이기 화면 내용 ·
//       파일 올려 점검 → 결과 화면(제목 = 파일 이름) · 없는 ?u= → 골라 둔 모습 + 「다른 계정」 → 목록 · 모든 단계에서 스크립트 오류 0

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const arg = (name, fb) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fb; };
const PORT = Number(arg("--port", process.env.CDP_PORT || 9333));
const BASE = arg("--base", process.env.SNS_BASE || "http://localhost:3020").replace(/\/$/, "");
const PADO = arg("--pado", process.env.PADO_BASE || "http://localhost:8020").replace(/\/$/, "");
const T = 10000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const withTimeout = (p, ms, what) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error(`timeout: ${what}`)), ms))]);

const results = [];
function check(step, name, ok, got, want) { results.push({ step, check: name, ok: !!ok, got, want }); }

async function connect() {
  const list = await withTimeout(fetch(`http://127.0.0.1:${PORT}/json`).then((r) => r.json()), T, "list targets");
  let page = list.find((t) => t.type === "page");
  if (!page) page = await withTimeout(fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: "PUT" }).then((r) => r.json()), T, "new target");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await withTimeout(new Promise((res, rej) => { ws.addEventListener("open", res, { once: true }); ws.addEventListener("error", rej, { once: true }); }), T, "ws open");
  let id = 0;
  const pending = new Map(), errors = [], requests = [];
  ws.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(`${p.method}: ${m.error.message}`)) : p.res(m.result); return; }
    if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    if (m.method === "Network.requestWillBeSent") requests.push(`${m.params.request.method} ${m.params.request.url}`);
  });
  const send = (method, params = {}) => withTimeout(new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej, method }); ws.send(JSON.stringify({ id: i, method, params })); }), T, method);
  const js = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(`JS: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
    return r.result.value;
  };
  return { ws, send, js, errors, requests };
}

// cond 가 참이 될 때까지(최대 ms) — 페이지가 바뀌는 중이면 평가가 실패할 수 있어 삼키고 다시 본다
async function until(js, cond, ms = 8000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if (await js(cond)) return true; } catch { /* 이동 중 */ } await sleep(100); }
  return false;
}

async function main() {
  const c = await connect();
  const { send, js, errors, requests } = c;
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("DOM.enable");
  await send("Network.setCacheDisabled", { cacheDisabled: true });
  await send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false });
  const nav = async (url) => { await send("Page.navigate", { url }); await sleep(300); await until(js, `document.readyState === "complete"`); await sleep(400); };
  const errCount = () => errors.length;

  // ① 홈 상단바 「내 글 점검」 → 점검 화면
  {
    const step = "① 홈 → 내 글 점검";
    await send("Network.clearBrowserCookies");
    await nav(`${BASE}/?skip_about=1`);
    const href = await js(`document.querySelector(".ut-nav a.chk")?.getAttribute("href") || ""`);
    check(step, "상단바 「내 글 점검」이 점검 화면으로", /\/static\/scan\.html/.test(href), href, ".../static/scan.html");
    await nav(href.startsWith("http") ? href : `${BASE}${href}`);
    // 「내 계정」을 정해 둔 방문자면 링크에 ?u= 가 붙어 그 계정이 골라진 채 열린다 · 아니면 목록부터
    if (/[?&]u=/.test(href)) {
      const me = await until(js, `!document.getElementById("picked").hidden && !document.getElementById("scanBtn").disabled`, 4000);
      check(step, "내 계정이 골라진 채 열림 (?u=)", me, href, "골라 둔 모습 · 버튼 켜짐");
    }
    await nav(`${PADO}/static/scan.html`);
    const listed = await until(js, `document.querySelectorAll("#finderList .acct").length >= 12`);
    check(step, "계정 없이 열면 목록 12명 (이름을 몰라도 고른다)", listed, await js(`document.querySelectorAll("#finderList .acct").length`), "≥ 12");
  }

  // ② 계정 고르기 → 예상 시간 → 「공개 글 점검」 (느린 네트워크로 진행 표시까지)
  let nick = "";
  {
    const step = "② 점검";
    nick = await js(`(() => { const b = document.querySelector("#finderList .acct"); const n = b.querySelector(".nm").textContent; b.click(); return n; })()`);
    const picked = await until(js, `!document.getElementById("picked").hidden && !document.getElementById("scanBtn").disabled`, 3000);
    check(step, "고르면 고른 계정이 보이고 버튼이 켜짐", picked, picked, true);
    const est = await until(js, `!!document.querySelector("#picked .est")`, 5000);
    check(step, "고른 계정 옆에 예상 시간", est, est ? await js(`document.querySelector("#picked .est").textContent`) : null, "본문 약 N자 · 점검 예상 약 N초");
    const before = requests.length;
    await send("Network.emulateNetworkConditions", { offline: false, latency: 1500, downloadThroughput: -1, uploadThroughput: -1 });
    await js(`document.getElementById("scanBtn").click(); true`);
    const busy = await until(js, `document.getElementById("scanBtn").classList.contains("is-busy")`, 1000);
    check(step, "누르면 버튼이 「점검 중…」", busy, busy ? await js(`document.getElementById("scanBtn").textContent.trim()`) : null, "점검 중…");
    const lock = await js(`({ q: document.getElementById("userQ").disabled, up: document.getElementById("uploadBtn").disabled, acct: [...document.querySelectorAll("#finderList button")].every((b) => b.disabled) })`);
    check(step, "점검 중엔 검색창 · 계정 · 파일 점검이 잠김 (요청 겹침 방지 · 키보드 포함)", lock.q && lock.up && lock.acct, lock, "모두 disabled");
    const band = await until(js, `(() => { const p = document.getElementById("progress"); return p && !p.hidden; })()`, 1000);
    check(step, "아래 진행 띠가 보임", band, band, true);
    const det = band && await until(js, `document.querySelector("#progress .pbar").classList.contains("det") && /약/.test(document.getElementById("pTime").textContent)`, 1500);
    check(step, "진행 띠 = 예상 시간에 맞춰 차오르는 막대 · 「N초 / 약 N초」", det, band ? await js(`document.getElementById("pTime").textContent`) : null, "det · 약");
    await sleep(200);
    const sent = requests.slice(before).some((r) => /^POST .*\/scan\//.test(r));
    check(step, "점검 요청(POST /scan/…)이 실제로 나감", sent, requests.slice(before).filter((r) => /scan/.test(r)), "POST /scan/<user_ref>");
    const landed = await until(js, `location.pathname.endsWith("/diagnosis.html")`, 120000);   // 실제 엔진은 긴 계정이 1분 가까이 걸린다
    await send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
    check(step, "점검 결과 화면으로 이동", landed, await js(`location.pathname`).catch(() => null), "/static/diagnosis.html");
  }

  // ③ 점검 결과 → 위험 줄이기
  {
    const step = "③ 결과 → 위험 줄이기";
    const shown = await until(js, `document.getElementById("content") && document.getElementById("content").textContent.includes(${JSON.stringify(nick)})`, 5000);
    check(step, "결과 화면에 고른 계정 이름", shown, nick, "포함");
    const risk = await js(`(() => { const m = (document.getElementById("content").textContent.match(/(\\d{1,3})\\s*\\/\\s*100/) || [])[1]; return m ? Number(m) : null; })()`);
    check(step, "결과 화면에 위험도(0~100)", risk !== null && risk >= 0 && risk <= 100, risk, "0~100");
    const title = await js(`(() => { const t = document.querySelector(".post-title"); return t ? parseFloat(getComputedStyle(t).fontSize) : null; })()`);
    check(step, "글 제목 글자 크기가 본문 수준 (veilo.css 이름 겹침 회귀)", title === null || title <= 18, title, "≤ 18px");
    await js(`document.querySelector('a.btn[href="action.html"]').click(); true`);
    const act = await until(js, `location.pathname.endsWith("/action.html") && document.getElementById("content") && document.getElementById("content").textContent.trim().length > 50`, 8000);
    check(step, "「위험 줄이기 →」 → 위험 줄이기 화면 내용", act, await js(`location.pathname`).catch(() => null), "/static/action.html · 내용");
    const rescan = await js(`!!document.getElementById("rescanBtn")`);
    check(step, "「다시 점검」 버튼이 있음", rescan, rescan, true);
  }

  // ④ 파일 올려 점검
  {
    const step = "④ 파일 올려 점검";
    const dir = mkdtempSync(join(tmpdir(), "pado-flow-"));
    const file = join(dir, "flow-sample.txt");
    writeFileSync(file, "오늘은 동네 공원을 걸었다\n주말엔 시장에서 장을 봤다\n퇴근길에 비가 왔다\n", "utf-8");
    await nav(`${PADO}/static/scan.html`);
    const { root } = await send("DOM.getDocument", { depth: -1 });
    const { nodeId } = await send("DOM.querySelector", { nodeId: root.nodeId, selector: "#uploadFile" });
    await send("DOM.setFileInputFiles", { nodeId, files: [file] });
    const before = requests.length;
    await js(`document.getElementById("uploadBtn").click(); true`);
    const landed = await until(js, `location.pathname.endsWith("/diagnosis.html")`, 120000);
    check(step, "업로드 요청(POST /upload)이 나감", requests.slice(before).some((r) => /^POST .*\/upload/.test(r)), requests.slice(before).filter((r) => /upload|estimate/.test(r)), "POST /upload");
    check(step, "업로드 점검 → 결과 화면", landed, await js(`location.pathname`).catch(() => null), "/static/diagnosis.html");
    const named = landed && await until(js, `document.getElementById("content").textContent.includes("flow-sample.txt")`, 4000);
    check(step, "결과 화면 제목 = 파일 이름", named, named, true);
  }

  // ⑤ 없는 계정으로 들어와도 골라 둔 모습 → 「다른 계정」 → 목록
  {
    const step = "⑤ 없는 ?u=";
    await nav(`${PADO}/static/scan.html?u=u_deadbeef00`);
    const p = await until(js, `!document.getElementById("picked").hidden && document.querySelector("#picked b")?.textContent === "u_deadbeef00"`, 4000);
    check(step, "식별자로 골라 둔 모습", p, p, true);
    await js(`document.getElementById("repick").click(); true`);
    const l = await until(js, `document.querySelectorAll("#finderList .acct").length >= 12 && document.getElementById("picked").hidden`, 4000);
    check(step, "「다른 계정」 → 전체 목록", l, l, true);
  }

  check("전체", "스크립트 오류 0", errCount() === 0, errors.slice(0, 5), 0);
  await send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await send("Emulation.clearDeviceMetricsOverride");
  c.ws.close();
}

let fatal = null;
try { await main(); } catch (e) { fatal = String(e && e.stack || e); }
const failed = results.filter((r) => !r.ok);
const ok = !fatal && failed.length === 0 && results.length > 0;
console.log(JSON.stringify({ ok, base: BASE, pado: PADO, total: results.length, failed: failed.length, fatal, results }, null, 2));
process.exit(ok ? 0 : 1);
