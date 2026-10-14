// 소개 화면(/about) 움직임 모드 브라우저 검증 — 실제 크롬에서 계산 스타일 · 캔버스 루프 · 키보드 도달을 본다.
// pytest 에는 넣지 않는다(CI 에 크롬이 없다). 외부 패키지 없음 — Node 22 내장 fetch · WebSocket 으로 CDP 에 붙는다.
//
// 실행 방법
//   1) Veilo 를 띄운다:   PADO_BASE=http://localhost:8020 SNS_PORT=3020 python apps/sns/app.py
//   2) 크롬을 디버깅 포트로 띄운다 (PowerShell · 프로필은 짧은 임시 경로):
//        Start-Process chrome.exe -ArgumentList '--headless=new','--remote-debugging-port=9333','--user-data-dir=C:\Temp\cm','--hide-scrollbars','about:blank'
//   3) node apps/sns/tools/check_motion.mjs [--port 9333] [--base http://localhost:3020]
//   4) 끝나면 2) 에서 띄운 크롬만 끈다 (Start-Process -PassThru 로 받은 Id 로 Stop-Process).
// 결과는 JSON 한 덩어리 { ok, failed, results:[{ mode, check, ok, got, want }] } — 하나라도 실패면 종료 코드 1.
//
// 모드: 첫 접속(쿠키 없음) · 관성 보간 · 기본(1400×900 · 핀) · ?view=static · 동작 줄이기 에뮬레이션 · 움직임 끄기 버튼 · 390px · 1280×640 · 1400×700
// 검사: 첫 접속 홈 → /about · 소개 뒤 홈 · 소개 창(dialog) 없음 · 끝 화면 「Veilo 둘러보기」로 홈 ·
//       관성 보간(휠 한 칸 뒤 수렴 시간 · 스크롤 중 rAF p95 · 수렴 뒤 cur = target · 카드 등장 겹침) ·
//       .ps-sticky position · .reveal opacity · html scroll-behavior · 보간 루프(html[data-ps-loop])가 멈춘 뒤 off · 클릭 물결이 남지 않음 ·
//       핀 장면 내용이 위 바 · 아래 소개 순서에 가리지 않음 · 움직임 토글 뒤 읽던 자리(±1화면) · Tab 으로 소개 순서 · 움직임 버튼 도달 ·
//       밤 막이 짙어지는 동안 좁혀지기 글자 대비(작은 라벨 4.5:1 · 제목·숫자 3:1 — 실제 계산 색 · 막 농도 · 라벨 바탕으로 계산) ·
//       첫 화면(W-HERO): Veilo 로 나가는 링크는 로고 말고 「건너뛰기」 하나 · 스크롤 신호가 40px 뒤 사라짐 · 정지 모드는 멈춘 화살표 ·
//       상단바 1px 선(--line-strong) 위 진행 막대 2px · 밤 장면에서도 선이 보임 · 히어로 = 한 화면(끌어내리는 버튼 없음) · 로고 = 파도풀 ·
//       첫 화면 들판(pado-hero.js): 낱말 · 점이 그려짐 · 돋보기가 마우스를 따라옴 · 가만있으면 떠돎 · 정지 모드는 루프 없음 ·
//       좁혀지기 지도: 배율이 커지고 핀이 카드를 따라 꽂힘 · 네 단계 그림판: 지금 단계 그림이 가장 진함 · 끝 화면 물결(정지 모드는 멈춤)

const arg = (name, fb) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fb; };
const PORT = Number(arg("--port", process.env.CDP_PORT || 9333));
const BASE = arg("--base", process.env.SNS_BASE || "http://localhost:3020").replace(/\/$/, "");
const T = 10000;   // CDP 호출 하나의 타임아웃(ms)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const withTimeout = (p, ms, what) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error(`timeout: ${what}`)), ms))]);

// ── CDP ──
async function connect() {
  const list = await withTimeout(fetch(`http://127.0.0.1:${PORT}/json`).then((r) => r.json()), T, "list targets");
  let page = list.find((t) => t.type === "page");
  if (!page) page = await withTimeout(fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: "PUT" }).then((r) => r.json()), T, "new target");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await withTimeout(new Promise((res, rej) => { ws.addEventListener("open", res, { once: true }); ws.addEventListener("error", rej, { once: true }); }), T, "ws open");
  let id = 0;
  const pending = new Map();
  const waiters = [];
  ws.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(`${p.method}: ${m.error.message}`)) : p.res(m.result); }
    else if (m.method) for (let i = waiters.length - 1; i >= 0; i--) if (waiters[i].method === m.method) { waiters[i].res(m.params); waiters.splice(i, 1); }
  });
  const send = (method, params = {}) => withTimeout(new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej, method }); ws.send(JSON.stringify({ id: i, method, params })); }), T, method);
  const once = (method, ms = T) => withTimeout(new Promise((res) => waiters.push({ method, res })), ms, `event ${method}`);
  const js = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(`JS: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
    return r.result.value;
  };
  return { ws, send, once, js };
}

const results = [];
const measure = {};   // 관성 보간 실측 (보고서용 — 통과 여부와 따로 출력)
function check(mode, name, ok, got, want) { results.push({ mode, check: name, ok: !!ok, got, want }); }

async function main() {
  const c = await connect();
  const { send, once, js } = c;
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Page.bringToFront");
  await send("Emulation.setFocusEmulationEnabled", { enabled: true });

  async function open(path, { w = 1400, h = 900, mobile = false, reduced = false, motion = "on" } = {}) {
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile });
    await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: reduced ? "reduce" : "no-preference" }] });
    // 움직임 설정(localStorage)은 같은 출처에서만 쓸 수 있다 — 한 번 열고 쓴 뒤 다시 연다
    let load = once("Page.loadEventFired");
    await send("Page.navigate", { url: `${BASE}/about` });
    await load;
    await js(`localStorage.setItem("padopool_motion", ${JSON.stringify(motion)}); true`);
    load = once("Page.loadEventFired");
    await send("Page.navigate", { url: `${BASE}${path}` });
    await load;
    await sleep(700);
  }
  // 보간 루프가 멈출 때까지(= 연출 값이 목표에 닿을 때까지) 기다린다
  const settle = async () => { for (let i = 0; i < 40; i++) { if ((await js(`document.documentElement.dataset.psLoop`)) !== "on") return; await sleep(50); } };
  const scrollTo = async (y) => { await js(`window.scrollTo({ top: ${Math.round(y)}, behavior: "instant" }); true`); await sleep(80); await settle(); };
  // 섹션 안 비율 p 자리의 스크롤 값 (핀 장면은 풀리는 지점까지를 0~1 로)
  const posOf = (sel, p) => js(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); const top = el.getBoundingClientRect().top + scrollY;
    return Math.round(top + ${p} * Math.max(0, el.offsetHeight - innerHeight)); })()`);
  const state = () => js(`(() => { const cs = (s, p) => { const el = document.querySelector(s); return el ? getComputedStyle(el)[p] : null; };
    return { cls: document.documentElement.className, sticky: cs(".ps-sticky", "position"), reveal: cs(".reveal", "opacity"),
      scroll: getComputedStyle(document.documentElement).scrollBehavior, loop: document.documentElement.dataset.psLoop,
      pinned: window.PadoMotion ? window.PadoMotion.pinned() : null, vh: innerHeight }; })()`);
  async function loopStops(mode) {
    let loop = null;
    for (let i = 0; i < 20; i++) { loop = await js(`document.documentElement.dataset.psLoop`); if (loop === "off") break; await sleep(250); }
    check(mode, "보간 루프 data-ps-loop 멈춘 뒤 off", loop === "off", loop, "off");
  }
  // 물결 — pointerdown 을 n 번 보내고 남은 .fx-ripple 수
  const ripple = (n) => js(`(() => { const b = document.querySelector("[data-motion-toggle]:not([hidden])") || document.querySelector(".ut-top a");
    const r = b.getBoundingClientRect();
    for (let i = 0; i < ${n}; i++) b.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, clientX: r.left + 4, clientY: r.top + 4 }));
    return document.querySelectorAll(".fx-ripple").length; })()`);
  const ripples = () => js(`document.querySelectorAll(".fx-ripple").length`);
  // Tab 을 눌러 가며 소개 순서 링크 · 움직임 버튼에 닿는지
  async function tabReach(mode, { map = true, motion = true } = {}) {
    await js(`window.scrollTo(0, 0); document.activeElement && document.activeElement.blur(); true`);
    const seen = { map: false, motion: false, skip: false };
    for (let i = 0; i < 60 && !(seen.map && seen.motion && seen.skip); i++) {
      await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
      await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
      const f = await js(`(() => { const a = document.activeElement; return { map: !!a.closest(".ps-map a"), motion: a.matches("[data-motion-toggle]"), skip: a.matches(".ps-skipnav") }; })()`);
      seen.map ||= f.map; seen.motion ||= f.motion; seen.skip ||= f.skip;
    }
    check(mode, "Tab 으로 「건너뛰기」 도달", seen.skip, seen.skip, true);
    if (map) check(mode, "Tab 으로 소개 순서 링크 도달", seen.map, seen.map, true);
    if (motion) check(mode, "Tab 으로 움직임 버튼 도달", seen.motion, seen.motion, true);
  }
  // 핀 장면 내용이 위 바 · 아래 소개 순서에 가리지 않는지 (핀일 때만 의미가 있다)
  const clipping = () => js(`(() => { const top = document.getElementById("utTop")?.getBoundingClientRect().bottom || 0;
    const map = document.querySelector(".ps-map"); const mapTop = map && getComputedStyle(map).display !== "none" ? map.getBoundingClientRect().top : innerHeight;
    const r = document.querySelector("#narrow .ps-sticky > .ps-in").getBoundingClientRect();
    return { top: Math.round(r.top), bottom: Math.round(r.bottom), barBottom: Math.round(top), mapTop: Math.round(mapTop) }; })()`);

  // 첫 화면(스크롤 0) — 화면 안에 보이는 링크 중 Veilo 로 나가는 것(# 앵커가 아닌 것 · 로고 제외) · 스크롤 신호 상태
  const heroState = () => js(`(() => {
    const vis = (el) => { const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth && cs.visibility !== "hidden" && Number(cs.opacity) > 0; };
    const exits = [...document.querySelectorAll("a[href]")].filter((a) => !a.getAttribute("href").startsWith("#") && !a.classList.contains("ut-logo") && vis(a))
      .map((a) => ({ text: a.textContent.trim(), href: a.getAttribute("href"), label: a.getAttribute("aria-label") }));
    const cue = document.getElementById("psCue"), ci = cue.querySelector("i"), cs = getComputedStyle(cue);
    return { y: scrollY, exits, cue: { opacity: Number(cs.opacity), visibility: cs.visibility, anim: getComputedStyle(ci).animationName, gone: cue.classList.contains("is-gone") } }; })()`);
  async function heroChecks(mode, { animated }) {
    await js(`window.scrollTo({ top: 0, behavior: "instant" }); true`);
    await sleep(450);
    const h = await heroState();
    check(mode, "첫 화면 Veilo 로 나가는 링크 = 「건너뛰기」 하나 (로고 제외)", h.exits.length === 1 && h.exits[0].text === "건너뛰기" && h.exits[0].label === "소개 건너뛰고 Veilo 로", h.exits, "[건너뛰기]");
    check(mode, "스크롤 신호 보임 (스크롤 0)", h.cue.opacity === 1 && h.cue.visibility === "visible", h.cue, "opacity 1");
    check(mode, animated ? "스크롤 신호 화살표 오르내림" : "스크롤 신호 화살표 정지", animated ? h.cue.anim === "ps-bob" : h.cue.anim === "none", h.cue.anim, animated ? "ps-bob" : "none");
    await js(`window.scrollTo({ top: 41, behavior: "instant" }); true`);
    await sleep(450);
    const g = await heroState();
    check(mode, "40px 넘게 내리면 스크롤 신호 사라짐", g.cue.gone && g.cue.opacity === 0 && g.cue.visibility === "hidden", g.cue, "is-gone · opacity 0 · hidden");
    await js(`window.scrollTo({ top: 0, behavior: "instant" }); true`);
    await sleep(450);
    const b = await heroState();
    check(mode, "맨 위로 돌아오면 스크롤 신호 다시", !b.cue.gone && b.cue.opacity === 1, b.cue, "보임");
  }

  // 정지 모드 공통 검사
  async function staticChecks(mode, s) {
    await heroChecks(mode, { animated: false });
    check(mode, "html 에 ps-static · no-motion", /\bps-static\b/.test(s.cls) && /\bno-motion\b/.test(s.cls), s.cls, "ps-static no-motion");
    check(mode, ".ps-sticky position", s.sticky === "static", s.sticky, "static");
    check(mode, ".reveal opacity (스크롤 전)", s.reveal === "1", s.reveal, "1");
    check(mode, "html scroll-behavior", s.scroll === "auto", s.scroll, "auto");
    const hs = await js(`window.PadoHero ? window.PadoHero.probe() : null`);
    check(mode, "들판 루프 없음 (한 장면만)", hs && !hs.running, hs, "running false");
    const wave = await js(`getComputedStyle(document.querySelector(".ps-waves .w1")).animationName`);
    check(mode, "끝 화면 물결 멈춤", wave === "none", wave, "none");
    await scrollTo(await posOf("#narrow", 0.5));
    await loopStops(mode);
    const n = await ripple(3);
    check(mode, "클릭 물결 안 생김", n === 0, n, 0);
  }

  // ⓪ 첫 접속 — 쿠키 없는 방문자가 홈으로 오면 /about · 소개를 본 뒤엔 홈 · 다른 경로는 안 보냄 · 소개 창 없음
  {
    const mode = "첫 접속";
    await send("Network.enable");
    await send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false });
    await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
    const nav = async (path) => { const load = once("Page.loadEventFired"); await send("Page.navigate", { url: `${BASE}${path}` }); await load; await sleep(300); return js(`location.pathname + location.search`); };
    const fresh = async (path) => { await send("Network.clearBrowserCookies"); return nav(path); };
    const DLG = `document.querySelectorAll("dialog, #intro, [data-intro-open], [data-intro-close]").length`;
    let at = await fresh("/");
    check(mode, "쿠키 없음 홈 → /about", at === "/about", at, "/about");
    let n = await js(DLG);
    check(mode, "소개 창(dialog) 없음 · /about", n === 0, n, 0);
    at = await nav("/");
    check(mode, "소개를 연 뒤 홈은 홈", at === "/", at, "/");
    n = await js(DLG);
    check(mode, "소개 창(dialog) 없음 · 홈", n === 0, n, 0);
    const links = await js(`document.querySelectorAll('a[href="/about"]').length`);
    check(mode, "홈의 「파도풀이란?」 링크 → /about (상단바 · 레일 · 피드 위)", links >= 3, links, "≥ 3");
    at = await fresh("/new");
    check(mode, "쿠키 없음 /new → 그대로", at === "/new", at, "/new");
    at = await fresh("/?skip_about=1");
    check(mode, "?skip_about=1 → 홈", at === "/?skip_about=1", at, "/?skip_about=1");
    at = await nav("/");
    check(mode, "?skip_about=1 뒤 쿼리 없이도 홈", at === "/", at, "/");
    // 소개 끝까지 내려가 큰 버튼으로 Veilo 에 들어간다
    await fresh("/");
    await js(`window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" }); true`);
    await sleep(900);
    const end = await js(`(() => { const a = document.querySelector("#end .ps-go"); const r = a.getBoundingClientRect();
      return { href: a.getAttribute("href"), inView: r.top >= 0 && r.bottom <= innerHeight, h: document.querySelector("#end h2").textContent, x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
    check(mode, "끝 화면 제목 「이제 Veilo 에서 직접 해 보세요」", /이제 Veilo 에서\s*직접 해 보세요/.test(end.h), end.h, "이제 Veilo 에서 직접 해 보세요");
    check(mode, "끝 화면 「Veilo 둘러보기」 버튼이 화면 안", end.inView, end, "inView");
    const load = once("Page.loadEventFired");
    for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: end.x, y: end.y, button: "left", clickCount: 1 });
    await load; await sleep(300);
    at = await js(`location.pathname`);
    check(mode, "「Veilo 둘러보기」 → 홈", at === "/", at, "/");
  }

  // ①-a 관성 보간 — 휠 한 칸 뒤 연출 값이 목표에 수렴하는 시간 · 스크롤 중 rAF 간격 p95 · 카드 등장 겹침

  {
    const mode = "관성 보간 1400×900";
    await open("/about");
    // 페이지 안 기록기 — 매 rAF 마다 좁혀지기 장면의 { target, cur } · scroll 이벤트 시각
    const REC = (ms) => `new Promise((res) => { const fr = [], sc = []; const t0 = performance.now();
      const on = () => sc.push(performance.now() - t0); addEventListener("scroll", on, { passive: true });
      const tick = (t) => { const p = window.PadoMotion.probe().find((x) => x.id === "narrow"); fr.push({ t: t - t0, target: p.target, cur: p.cur });
        if (t - t0 < ${ms}) requestAnimationFrame(tick); else { removeEventListener("scroll", on); res({ fr, sc }); } };
      requestAnimationFrame(tick); })`;
    const runs = [];
    for (const p0 of [0.2, 0.45, 0.7]) {
      await scrollTo(await posOf("#narrow", p0));
      const c = await js(`(() => { const r = document.querySelector("#narrow .ps-stage").getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
      await js(`window.__p = ${REC(1500)}; true`);
      await send("Input.dispatchMouseEvent", { type: "mouseWheel", x: c.x, y: c.y, deltaX: 0, deltaY: 100 });
      const { fr, sc } = await js(`window.__p`);
      if (!sc.length) { runs.push({ p0, err: "scroll 없음" }); continue; }
      const t0 = sc[0], T = fr[fr.length - 1].target;
      const c0 = (fr.find((f) => f.t >= t0) || fr[0]).cur;
      const step = Math.abs(T - c0) || 1e-9;
      // q 만큼 다가간 뒤 다시 벗어나지 않는 첫 프레임 (scroll 첫 이벤트 기준 ms)
      const at = (q) => { let tt = null; for (const f of fr) { if (f.t < t0) continue; if (Math.abs(T - f.cur) <= (1 - q) * step) { if (tt === null) tt = f.t; } else tt = null; } return tt === null ? null : Math.round(tt - t0); };
      const f = fr.find((f) => f.t >= t0 && f.cur === T);
      runs.push({ p0, step: Math.round(step * 10000) / 10000, scrollMs: Math.round(sc[sc.length - 1] - t0), t90: at(0.9), t95: at(0.95), t98: at(0.98), stop: f ? Math.round(f.t - t0) : null });
    }
    measure.wheel = runs;
    check(mode, "휠 한 칸 뒤 95% 수렴 150~450ms (목표 250~400)", runs.every((r) => r.t95 !== null && r.t95 >= 150 && r.t95 <= 450), runs, "t95 150~450ms");
    check(mode, "휠 한 칸 뒤 루프 멈춤 (cur = target)", runs.every((r) => r.stop !== null && r.stop <= 1200), runs.map((r) => r.stop), "≤ 1200ms");
    // 연속 스크롤 — 휠 30칸을 40ms 간격으로 보내는 동안 rAF 간격
    await scrollTo(await posOf("#narrow", 0.05));
    await js(`window.__p = new Promise((res) => { const d = []; let prev = 0; const t0 = performance.now();
      const tick = (t) => { if (prev) d.push(t - prev); prev = t; if (t - t0 < 2000) requestAnimationFrame(tick); else res(d); }; requestAnimationFrame(tick); }); true`);
    for (let i = 0; i < 30; i++) { await send("Input.dispatchMouseEvent", { type: "mouseWheel", x: 700, y: 450, deltaX: 0, deltaY: 100 }); await sleep(40); }
    const d = (await js(`window.__p`)).sort((a, b) => a - b);
    const q = (x) => Math.round(d[Math.min(d.length - 1, Math.floor(x * d.length))] * 10) / 10;
    const raf = { frames: d.length, p50: q(0.5), p95: q(0.95), p99: q(0.99), max: Math.round(d[d.length - 1] * 10) / 10 };
    measure.raf = raf;
    check(mode, "연속 스크롤 중 rAF 간격 p95 ≤ 20ms", raf.p95 <= 20, raf, "p95 ≤ 20ms (60Hz = 16.7)");
    await settle();
    const pr = await js(`window.PadoMotion.probe()`);
    check(mode, "수렴 뒤 모든 장면 cur = target", pr.length === 2 && pr.every((x) => x.cur === x.target), pr, "cur === target");
    // 카드 등장 구간 겹침 — 좁혀지기 0.05~0.85 를 훑으며 반쯤 나온 카드가 2장 이상인 지점 수
    let overlap = 0;
    for (let p = 0.05; p <= 0.85; p += 0.04) {
      await scrollTo(await posOf("#narrow", p));
      const k = await js(`[...document.querySelectorAll("#narrow .ps-post")].filter((el) => { const v = Number(el.style.getPropertyValue("--in")); return v > 0.05 && v < 0.95; }).length`);
      if (k >= 2) overlap++;
    }
    check(mode, "카드 등장 구간이 겹친다 (반쯤 나온 카드 2장 이상 지점)", overlap >= 5, overlap, "≥ 5 지점");
  }

  // ① 기본 — 1400×900 핀
  {
    const mode = "기본 1400×900";
    await open("/about");
    let s = await state();
    check(mode, "html 에 정지 클래스 없음", !/ps-static|no-motion/.test(s.cls), s.cls, "ps-page js");
    check(mode, ".ps-sticky position", s.sticky === "sticky", s.sticky, "sticky");
    check(mode, ".reveal opacity (스크롤 전 숨김)", Number(s.reveal) < 0.01, s.reveal, "< 0.01 (전환 끝자락 값 허용)");
    check(mode, "html scroll-behavior", s.scroll === "smooth", s.scroll, "smooth");
    await heroChecks(mode, { animated: true });
    // 상단바 선 · 진행 막대 · 소개 순서 · 다음 장면 걸침
    const top0 = await js(`(() => { const t = document.getElementById("utTop"), cs = getComputedStyle(t), tr = t.getBoundingClientRect();
      const b = document.querySelector(".ps-progress").getBoundingClientRect(), hero = document.getElementById("hero").getBoundingClientRect();
      const map = document.querySelector(".ps-map").getBoundingClientRect();
      const a = (cs.borderBottomColor.match(/[\\d.]+/g) || []).map(Number);
      return { line: cs.borderBottomColor, lineW: cs.borderBottomWidth, alpha: a.length > 3 ? a[3] : 1, barH: Math.round(b.height), barBottom: Math.round(b.bottom), topBottom: Math.round(tr.bottom),
        heroBottom: Math.round(hero.bottom), mapTop: Math.round(map.top), vh: innerHeight, logo: document.querySelector(".ut-logo .wm").textContent,
        current: document.querySelector(".ps-map a[aria-current]")?.dataset.map }; })()`);
    check(mode, "상단바 아래 1px 선이 처음부터 또렷 (알파 ≥ 0.2)", top0.lineW === "1px" && top0.alpha >= 0.2, top0, "1px · α ≥ .2");
    check(mode, "진행 막대 2px 가 상단바 선 위", top0.barH === 2 && Math.abs(top0.barBottom - top0.topBottom) <= 1, top0, "높이 2 · 아래 끝 = 상단바 아래 끝 ±1");
    check(mode, "첫 화면 소개 순서 현재 = 01 파도풀", top0.current === "hero", top0.current, "hero");
    check(mode, "히어로 = 한 화면 (아래 끝 = 화면 아래 ±2)", Math.abs(top0.heroBottom - top0.vh) <= 2, top0, "heroBottom ≈ vh");
    check(mode, "로고 = 파도풀", top0.logo === "파도풀", top0.logo, "파도풀");
    const jump = await js(`document.querySelectorAll("#hero a[href^='#'], .ps-down").length`);
    check(mode, "히어로에 끌어내리는 버튼 없음", jump === 0, jump, 0);
    // 첫 화면 들판 — 낱말 · 점 · 돋보기가 마우스를 따라온다 · 가만있으면 떠돈다
    const hp = () => js(`window.PadoHero ? window.PadoHero.probe() : null`);
    let h0 = await hp();
    check(mode, "들판 낱말 ≥ 8 · 점 ≥ 300", h0 && h0.words >= 8 && h0.dots >= 300, h0, "words ≥ 8 · dots ≥ 300");
    check(mode, "들판 루프 돎 (첫 화면 · 움직임 모드)", h0 && h0.running, h0 && h0.running, true);
    const ink = await js(`(() => { const c = document.getElementById("psField"), x = c.getContext("2d").getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < x.length; i += 4) if (x[i] > 0) n++; return n; })()`);
    check(mode, "들판 캔버스에 그림이 있음", ink > 1000, ink, "> 1000 픽셀");
    const t1 = await js(`(() => { const r = document.getElementById("psField").getBoundingClientRect(); return { x: Math.round(r.left + r.width * 0.8), y: Math.round(r.top + r.height * 0.75) }; })()`);
    for (let i = 0; i < 6; i++) { await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: t1.x - 30 + i * 5, y: t1.y }); await sleep(30); }
    await sleep(900);
    h0 = await hp();
    const cr = await js(`(() => { const r = document.getElementById("psField").getBoundingClientRect(); return { l: r.left, t: r.top }; })()`);
    const off = Math.round(Math.hypot(h0.lx + cr.l - t1.x, h0.ly + cr.t - t1.y));
    check(mode, "돋보기가 마우스를 따라옴 (0.9초 뒤 ±24px)", off <= 24, { off, h0, t1 }, "≤ 24");
    await sleep(3200);
    const a1 = await hp(); await sleep(600); const a2 = await hp();
    const drift = Math.round(Math.hypot(a2.lx - a1.lx, a2.ly - a1.ly));
    check(mode, "가만있으면 돋보기가 떠돎 (2.5초 뒤)", drift >= 2, drift, "≥ 2px / 0.6초");
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 5, y: 5 });
    // 좁혀지기 지도 — 처음엔 배율 1 · 핀 없음 → 끝엔 배율 ≥ 1.5 · 핀 다섯 개 다
    const mapAt = async (p) => { await scrollTo(await posOf("#narrow", p));
      return js(`({ z: Number(document.querySelector("#narrow .ps-stage").style.getPropertyValue("--z")), pins: [...document.querySelectorAll("#narrow .ps-pinm")].map((e) => Number(e.style.getPropertyValue("--in"))) })`); };
    const m0 = await mapAt(0.02), m1 = await mapAt(0.95);
    check(mode, "지도 처음: 배율 < 1.05 · 핀 없음", m0.z < 1.05 && m0.pins.every((v) => v < 0.1), m0, "z < 1.05 · pins < .1");
    check(mode, "지도 끝: 배율 ≥ 1.5 · 핀 다섯 개", m1.z >= 1.5 && m1.pins.length === 5 && m1.pins.every((v) => v > 0.9), m1, "z ≥ 1.5 · pins > .9");
    // 네 단계 그림판 — 진행도마다 가장 진한 그림 = 그때 켜진 마지막 단계
    const visAt = async (p) => { await scrollTo(await posOf("#steps", p));
      return js(`(() => { const f = [...document.querySelectorAll("#steps .ps-vis-i")].map((e) => Number(e.style.getPropertyValue("--f") || 0)); return { f, top: f.indexOf(Math.max(...f)) }; })()`); };
    const vs = [];
    for (const [p, want] of [[0.05, 0], [0.42, 1], [0.66, 2], [0.98, 3]]) { const v = await visAt(p); vs.push({ p, want, ...v }); }
    check(mode, "네 단계 그림판: 지금 단계 그림이 가장 진함", vs.every((v) => v.top === v.want && v.f[v.top] > 0.6), vs, "0 → 1 → 2 → 3");
    // 단계 사이 머무는 구간 — 칸(1/4) 뒤쪽 60% 에서는 스크롤해도 단계 값 · 선이 그대로
    const holdAt = async (p) => { await scrollTo(await posOf("#steps", p)); await sleep(700); await settle();
      return js(`({ a: [...document.querySelectorAll("#steps .ps-step")].map((e) => Number(e.style.getPropertyValue("--a"))), w: Number(document.querySelector("#steps .ps-path i").style.getPropertyValue("--w")) })`); };
    const hA = await holdAt(0.19), hB = await holdAt(0.24);
    check(mode, "네 단계: 단계 사이에 멈추는 구간 (진행도 0.19 ~ 0.24 동안 값 그대로)", JSON.stringify(hA) === JSON.stringify(hB) && hA.a[0] === 1 && hA.a[1] === 0, { hA, hB }, "같음 · 1단계만 켜짐");
    // 밤 장면 — 상단바 선이 밝은 색으로 보인다
    await scrollTo(await posOf("#narrow", 0.8));
    await sleep(500);
    const dk = await js(`(() => { const a = (getComputedStyle(document.getElementById("utTop")).borderBottomColor.match(/[\\d.]+/g) || []).map(Number);
      const k = /^color\\(/.test(getComputedStyle(document.getElementById("utTop")).borderBottomColor) ? 255 : 1;   // color-mix 는 color(srgb 0~1 / a) 로 나온다
      return { dark: document.documentElement.classList.contains("dark-chapter"), rgb: a.slice(0, 3).map((v) => Math.round(v * k)), alpha: a.length > 3 ? a[3] : 1 }; })()`);
    check(mode, "밤 장면에서도 상단바 선이 보임 (밝은 선 · 알파 ≥ 0.25)", dk.dark && dk.rgb[0] > 150 && dk.alpha >= 0.25, dk, "dark-chapter · 밝은 선");
    await js(`history.replaceState(null, "", location.pathname); true`);
    for (const p of [0.1, 0.5, 0.9]) {
      await scrollTo(await posOf("#narrow", p));
      const k = await clipping();
      check(mode, `핀 내용 안 가림 (좁혀지기 ${p})`, k.top >= k.barBottom && k.bottom <= k.mapTop, k, "top ≥ barBottom · bottom ≤ mapTop");
    }
    // 밤 막 전환 구간을 훑으며 글자 대비 — 글자 뒤 바탕 = 종이 위에 밤 막(opacity) · 그 위에 라벨 바탕(::before opacity)
    const CONTRAST = `(() => {
      const rgb = (s) => (s.match(/[\\d.]+/g) || []).map(Number);
      const over = (top, a, bot) => bot.map((v, i) => top[i] * a + v * (1 - a));
      const lum = (c) => { const [r, g, b] = c.slice(0, 3).map((v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
      const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
      const paper = rgb(getComputedStyle(document.body).backgroundColor);
      const nightEl = document.querySelector("#narrow .ps-night"), ns = getComputedStyle(nightEl);
      const behind = over(rgb(ns.backgroundColor), Number(ns.opacity), paper);
      const out = { d: Number(ns.opacity), small: 99, large: 99, worst: "" };
      const one = (sel, big) => document.querySelectorAll(sel).forEach((el) => {
        const pb = getComputedStyle(el, "::before"); let bg = behind;
        if (pb.content !== "none" && pb.backgroundColor) bg = over(rgb(pb.backgroundColor), Number(pb.opacity), behind);
        const c = rgb(getComputedStyle(el).color); const fg = c.length > 3 ? over(c, c[3], bg) : c;
        const r = ratio(fg, bg); const k = big ? "large" : "small";
        if (r < out[k]) { out[k] = Math.round(r * 100) / 100; if (r < (big ? 3 : 4.5)) out.worst = sel; }
      });
      one("#narrow .ps-narrow-txt > .eyebrow", false); one("#narrow .ps-count .eyebrow", false); one("#narrow .ps-count .ps-note", false);
      one("#narrow .ps-h2", true); one("#narrow .ps-count .num", true);
      return out; })()`;
    const sweep = { small: 99, large: 99, at: [] };
    for (let p = 0.4; p <= 0.62; p += 0.01) {
      await scrollTo(await posOf("#narrow", p));
      const r = await js(CONTRAST);
      sweep.small = Math.min(sweep.small, r.small); sweep.large = Math.min(sweep.large, r.large);
      if (r.worst) sweep.at.push({ p: Math.round(p * 100) / 100, ...r });
    }
    check(mode, "밤 막 전환 중 작은 라벨 대비 ≥ 4.5", sweep.small >= 4.5, sweep, "≥ 4.5");
    check(mode, "밤 막 전환 중 제목·숫자 대비 ≥ 3", sweep.large >= 3, sweep.large, "≥ 3");
    await loopStops(mode);
    const made = await ripple(1);
    await sleep(1100);
    const left = await ripples();
    check(mode, "클릭 물결 생겼다 지워짐", made === 1 && left === 0, { made, left }, { made: 1, left: 0 });
    await scrollTo(await posOf("#end", 0));
    await sleep(900);
    s = await state();
    check(mode, ".reveal opacity (화면에 든 뒤)", s.reveal === "1", s.reveal, "1");
    await tabReach(mode);
  }

  // ② 움직임 끄기 버튼 — 토글 뒤 읽던 자리 유지(±1화면) · 물결 정리
  {
    const mode = "움직임 끄기 버튼";
    await open("/about");
    await scrollTo(await posOf("#narrow", 0.6));
    const spot = () => js(`(() => { let cur = null; for (const s of document.querySelectorAll("[data-ps-section]")) if (s.getBoundingClientRect().top <= innerHeight * 0.1) cur = s;
      const r = cur.getBoundingClientRect(); return { id: cur.id, ratio: Math.min(1, Math.max(0, -r.top / r.height)), y: scrollY, h: r.height, top: r.top + scrollY, vh: innerHeight }; })()`);
    const click = async () => {
      const r = await js(`(() => { const r = document.querySelector("[data-motion-toggle]").getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
      for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: r.x, y: r.y, button: "left", clickCount: 1 });
      await sleep(600);
    };
    for (const [label, want] of [["끄기", true], ["다시 켜기", false]]) {
      const before = await spot();
      await click();
      const s = await state();
      const after = await spot();
      // 앞에서 읽던 섹션 · 비율이 가리키는 문서 위치와 지금 스크롤의 차이
      const expect = after.top + before.ratio * after.h;
      const diff = Math.round(Math.abs(after.y - expect));
      check(mode, `${label} 뒤 정지 상태 = ${want}`, /\bno-motion\b/.test(s.cls) === want && /\bps-static\b/.test(s.cls) === want, s.cls, want ? "ps-static no-motion" : "정지 클래스 없음");
      check(mode, `${label} 뒤 같은 섹션`, before.id === after.id, { before: before.id, after: after.id }, before.id);
      check(mode, `${label} 뒤 스크롤 위치 차이 ±1화면`, diff <= after.vh, diff, `≤ ${after.vh}`);
      check(mode, `${label} 뒤 남은 물결 0`, (await ripples()) === 0, await ripples(), 0);
      if (want) {
        check(mode, ".ps-sticky position", s.sticky === "static", s.sticky, "static");
        check(mode, ".reveal opacity", s.reveal === "1", s.reveal, "1");
        check(mode, "html scroll-behavior", s.scroll === "auto", s.scroll, "auto");
        const n = await ripple(5);
        check(mode, "끈 상태에서 클릭 물결 안 쌓임", n === 0, n, 0);
        await loopStops(mode);
      } else {
        check(mode, ".ps-sticky position", s.sticky === "sticky", s.sticky, "sticky");
      }
    }
  }

  // ③ ?view=static
  {
    const mode = "?view=static";
    await open("/about?view=static");
    const s = await state();
    await staticChecks(mode, s);
    const hidden = await js(`document.querySelector("[data-motion-toggle]").hidden`);
    check(mode, "움직임 버튼 숨김", hidden === true, hidden, true);
    await tabReach(mode, { motion: false });
  }

  // ④ 동작 줄이기 에뮬레이션
  {
    const mode = "prefers-reduced-motion";
    await open("/about", { reduced: true });
    await staticChecks(mode, await state());
    await tabReach(mode);
  }

  // ⑤ 390px — 모바일은 다 켜진 정지 상태 · 소개 순서는 숨김
  {
    const mode = "390×844";
    await open("/about", { w: 390, h: 844, mobile: true });
    await staticChecks(mode, await state());
    // 지도 핀이 무대 밖으로 잘리지 않는다 (배율 1.6 · 오른쪽 핀은 라벨이 왼쪽으로 — Codex 10/14)
    await scrollTo(await posOf("#narrow", 0));
    const pinOut = await js(`(() => { const s = document.querySelector("#narrow .ps-stage").getBoundingClientRect();
      return [...document.querySelectorAll("#narrow .ps-pinm")].map((e) => { const r = e.getBoundingClientRect(); return { t: e.textContent.trim(), out: Math.round(Math.max(s.left - r.left, r.right - s.right, s.top - r.top, r.bottom - s.bottom)) }; }).filter((x) => x.out > 0); })()`);
    check(mode, "지도 핀이 무대 안 (잘린 핀 0)", pinOut.length === 0, pinOut, "[]");
  }

  // ⑥ 낮은 데스크톱 — 핀 조건(높이 800) 밖이면 정지 흐름
  for (const [w, h] of [[1280, 640], [1400, 700]]) {
    const mode = `${w}×${h}`;
    await open("/about", { w, h });
    const s = await state();
    check(mode, "pinned() false", s.pinned === false, s.pinned, false);
    await staticChecks(mode, s);
    await tabReach(mode);
  }

  await send("Emulation.setEmulatedMedia", { features: [] });
  await send("Emulation.clearDeviceMetricsOverride");
  c.ws.close();
}

let fatal = null;
try { await main(); } catch (e) { fatal = String(e && e.stack || e); }
const failed = results.filter((r) => !r.ok);
const ok = !fatal && failed.length === 0 && results.length > 0;
console.log(JSON.stringify({ ok, base: BASE, total: results.length, failed: failed.length, fatal, measure, results }, null, 2));
process.exit(ok ? 0 : 1);
