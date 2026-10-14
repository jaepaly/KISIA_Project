/* 「파도풀이란?」 소개 장면 (about.html) — motion-core.js 위에서 돈다.
   A #narrow : 글 카드가 하나씩 쌓이고, 조건에 맞는 사람 수(가상 예시)가 로그 단위로 줄며 점이 꺼진다. 「나」 하나만 남는다.
   B #steps  : 네 단계가 차례로 켜진다 (0.24 간격 · 0.18 램프).
   C         : 읽기 진행 막대 · 소개 순서(Page map) · 어두운 구간이면 html.dark-chapter.
   정지 상태(html.ps-static)에서는 모든 장면이 끝난 모습 그대로다 — CSS 가 그렇게 그리고, 여기서는 캔버스만 끝 모습으로 한 번 그린다. */
(function () {
  "use strict";
  const M = window.PadoMotion;
  if (!M) return;
  const { clamp, smooth } = M;
  const root = document.documentElement;
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  // 한 번 쓴 값은 다시 안 쓴다 — 같은 값을 매 프레임 스타일에 쓰지 않게
  const last = new WeakMap();
  function setVar(el, name, v) {
    const r = Math.round(v * 1000) / 1000;
    let m = last.get(el);
    if (!m) { m = {}; last.set(el, m); }
    if (m[name] === r) return;
    m[name] = r;
    el.style.setProperty(name, String(r));
  }

  // ── 연출 A — 글이 쌓일수록 좁혀진다 ─────────────────────────────────────
  const narrow = M.track($("#narrow"));
  const posts = $$(".ps-post", narrow);
  const night = $(".ps-night", narrow);
  const spot = $(".ps-spot", narrow);
  const countEl = $("#psCount");
  const liveEl = $("#psCountLive");
  // 가상 예시 값 — 실제 통계가 아니다 (화면에도 그렇게 적는다)
  const K = [5000000, 400000, 30000, 1800, 90, 6, 1];
  const LOGMAX = Math.log(K[0]);
  // 앞 두 자리만 — 「약 4,278명」보다 「약 4,300명」이 예시답다
  const fmt = (n) => { n = Math.round(n); if (n >= 100) { const q = Math.pow(10, Math.floor(Math.log10(n)) - 1); n = Math.round(n / q) * q; } return n.toLocaleString("ko-KR"); };

  // 캔버스 — 점 하나가 같은 조건의 사람 하나. 값이 바뀔 때만 그리고, 다 바뀌면 멈춘다
  const crowd = (function () {
    const cv = $("#psCrowd");
    if (!cv || !cv.getContext) return null;
    const ctx = cv.getContext("2d");
    const small = !matchMedia("(min-width:768px)").matches;
    const N = small ? 900 : 2000;
    // 자리와 꺼지는 순서는 고정 난수 — 새로고침해도 같은 그림. 0번이 「나」(가운데)
    let seed = 7;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const pts = [];
    pts.push({ x: 0.5, y: 0.5, a: 1, t: 1 });
    while (pts.length < N) {
      const x = rnd(), y = rnd();
      if (Math.hypot(x - 0.5, y - 0.5) < 0.05) continue;   // 「나」 둘레는 비워 둔다
      pts.push({ x, y, a: 0.9, t: 0.9 });
    }
    for (let i = N - 1; i > 1; i--) { const j = 1 + Math.floor(rnd() * i); const tmp = pts[i]; pts[i] = pts[j]; pts[j] = tmp; }

    let w = 0, h = 0, dpr = 1, alive = N, visible = true, raf = 0, dark = false;
    function size() {
      dpr = Math.min(1.5, window.devicePixelRatio || 1);
      w = cv.clientWidth; h = cv.clientHeight;
      cv.width = Math.max(1, Math.round(w * dpr)); cv.height = Math.max(1, Math.round(h * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw();
    }
    function color(name, fb) { return getComputedStyle(cv).getPropertyValue(name).trim() || fb; }
    let ink = "#6B625B", hot = "#C2573A";
    function draw() {
      ctx.clearRect(0, 0, w, h);
      const r = Math.max(1.6, Math.min(w, h) / 170);
      ctx.fillStyle = ink;
      for (let i = 1; i < pts.length; i++) {
        const p = pts[i];
        if (p.a < 0.02) continue;
        ctx.globalAlpha = p.a;
        ctx.fillRect(p.x * w - r / 2, p.y * h - r / 2, r, r);
      }
      ctx.globalAlpha = 1;
      ctx.fillStyle = hot;
      ctx.beginPath(); ctx.arc(w / 2, h / 2, r * 3.2, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = hot; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(w / 2, h / 2, r * 7, 0, Math.PI * 2); ctx.stroke();
    }
    function step() {
      raf = 0;
      let moving = false;
      for (const p of pts) {
        const d = p.t - p.a;
        if (Math.abs(d) > 0.004) { p.a += d * 0.16; moving = true; } else p.a = p.t;
      }
      draw();
      if (moving && visible && !document.hidden) { raf = requestAnimationFrame(step); cv.dataset.loop = "on"; }
      else cv.dataset.loop = "off";   // 수렴 · 화면 밖 · 탭 숨김 → 루프 정지 (성능 확인용 표시)
    }
    function kick() { if (!raf && visible && !document.hidden) raf = requestAnimationFrame(step); }
    // 남는 점 수 = N^(log K / log Kmax) — K 를 로그 공간에서 점 개수로 옮긴다
    function setK(k, instant) {
      const n = Math.max(1, Math.round(Math.pow(N, Math.log(Math.max(1, k)) / LOGMAX)));
      if (n === alive && !instant) return;
      alive = n;
      pts.forEach((p, i) => { p.t = i === 0 ? 1 : (i < n ? 0.85 : 0.12); if (instant) p.a = p.t; });
      if (instant) { draw(); return; }
      kick();
    }
    function setDark(v) {
      if (v === dark) return;
      dark = v;
      ink = color(v ? "--ps-dot-dark" : "--ps-dot", ink);
      hot = color("--ps-hot", hot);
      draw();
    }
    if ("IntersectionObserver" in window) {
      new IntersectionObserver((e) => { visible = e[0].isIntersecting; if (visible) kick(); }).observe(cv);
    }
    document.addEventListener("visibilitychange", () => { if (!document.hidden) kick(); });
    if ("ResizeObserver" in window) new ResizeObserver(size).observe(cv); else size();
    ink = color("--ps-dot", ink); hot = color("--ps-hot", hot);
    return { setK, setDark };
  })();

  let stage = -1;
  function announce(s) {
    if (s === stage) return;
    stage = s;
    if (liveEl) liveEl.textContent = `글 ${s}편 — 예시로 약 ${fmt(K[s])}명 중 한 명`;
  }
  function narrowScene(y, on) {
    if (!narrow) return;
    if (!on) {   // 정지 상태 — 다 켜진 모습
      posts.forEach((el) => setVar(el, "--in", 1));
      if (night) setVar(night, "--d", 0);
      narrow.classList.remove("is-dark");
      countEl.textContent = `약 ${fmt(K[6])}명`;
      announce(6);
      if (crowd) { crowd.setDark(false); crowd.setK(1, true); }
      return;
    }
    const p = M.local(narrow, y);
    const s = clamp(p / 0.86) * 6;           // 0~6 — 끝 14% 는 「나」만 남은 채 멈춤
    posts.forEach((el, i) => setVar(el, "--in", smooth((s - i) / 0.7)));
    const i0 = Math.min(5, Math.floor(s)), f = smooth((s - i0) / 0.7);
    const k = Math.exp(Math.log(K[i0]) + (Math.log(K[i0 + 1]) - Math.log(K[i0])) * f);
    countEl.textContent = `약 ${fmt(k)}명`;
    announce(Math.min(6, Math.floor(s + 0.3)));
    const dark = smooth((p - 0.3) / 0.35) * 0.9;   // 글이 절반쯤 쌓인 뒤 어두워진다
    if (night) setVar(night, "--d", dark);
    if (spot) setVar(spot, "--s", 1 - smooth((p - 0.35) / 0.55));   // 1 → 0 : 스포트라이트가 「나」로 조여 온다
    narrow.classList.toggle("is-dark", dark > 0.5);
    if (crowd) { crowd.setDark(dark > 0.5); crowd.setK(k); }
  }

  // ── 연출 B — 네 단계 점등 ───────────────────────────────────────────────
  const steps = M.track($("#steps"));
  const stepEls = $$(".ps-step", steps);
  const path = $(".ps-path i", steps);
  function stepsScene(y, on) {
    if (!steps) return;
    const w = on ? M.local(steps, y) : 1;
    stepEls.forEach((el, i) => {
      const a = on ? smooth((w - 0.24 * i) / 0.18) : 1;
      setVar(el, "--a", a);
      el.classList.toggle("reached", w >= 0.24 * i);
    });
    if (path) setVar(path, "--w", w);
  }

  // ── 연출 C — 읽기 진행 막대 · 소개 순서 · 어두운 구간 ─────────────────────
  const bar = $("#psBar");
  const secs = $$("[data-ps-section]").map((el) => M.track(el));
  const mapLinks = new Map($$(".ps-map a[data-map]").map((a) => [a.dataset.map, a]));
  // 어두운 정도 — 섹션 위치로 만든 키프레임. 같은 값 두 번 = 멈춤 구간
  const tl = M.createTimeline(() => {
    if (!narrow || !steps) return [];
    const a = M.top(narrow), b = M.release(narrow);
    return [
      { at: a + (b - a) * 0.3, v: { night: 0 } },
      { at: a + (b - a) * 0.65, v: { night: 0.9 } },
      { at: b, v: { night: 0.9 } },
      { at: M.top(steps) - M.view.vh * 0.3, v: { night: 0 } },
    ];
  });
  let darkOn = false, current = null;
  function chromeScene(y, on) {
    if (bar) setVar(bar, "--p", clamp(y / M.view.max));
    const night = on ? (tl.sample(y).night || 0) : 0;
    if ((night > 0.5) !== darkOn) { darkOn = night > 0.5; root.classList.toggle("dark-chapter", darkOn); }
    let cur = secs[0];
    for (const s of secs) if (M.top(s) - y <= M.view.vh * 0.1) cur = s;
    secs.forEach((s) => {
      const a = mapLinks.get(s.id);
      if (!a) return;
      const u = a.querySelector("i");
      const span = Math.max(1, on && s.classList.contains("ps-pin") ? M.release(s) - M.top(s) : M.height(s));
      if (u) setVar(u, "--p", clamp((y - M.top(s) + M.view.vh * 0.1) / span));
    });
    if (cur !== current) {
      current = cur;
      mapLinks.forEach((a, id) => { if (id === cur.id) a.setAttribute("aria-current", "step"); else a.removeAttribute("aria-current"); });
    }
  }

  M.addScene(narrowScene);
  M.addScene(stepsScene);
  M.addScene(chromeScene);
  M.start();
})();
