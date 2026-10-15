/* 스크롤 연출 공통 엔진 — 소개 화면(about.html · pado-scene.js)이 쓴다.
   원칙: 스크롤 · 크기 변경 → rAF 에 한 번만 → 장면 함수들이 같은 y 로 갱신한다.
   위치 측정(getBoundingClientRect)은 refresh 에서만 — ResizeObserver · resize 가 「다시 재라」고 표시해 둔다.
   프레임 안에서는 읽은 값(캐시)만 쓰고 스타일만 바꾼다 — 쓰고 나서 다시 읽는 강제 레이아웃이 없다.
   움직임을 안 쓰는 경우(움직임 끄기 · 시스템 「동작 줄이기」 · ?view=static · PIN_MQ 밖 = 폭 767px 이하 또는 높이 799px 이하)는
   html.ps-static + html.no-motion 둘 다 — 장면은 「다 켜진 정지 상태」, 공통 효과(.reveal 등장 · 호버 · 부드러운 스크롤 · 클릭 물결)도 끈다.
   PIN_MQ 는 pado-scene.css 의 정지 미디어쿼리와 같은 문자열이다(test_about.py 가 대조한다). 767 은 레이아웃 CSS 의 (max-width:767px) 와 같은 값.
   높이 700 — 1366×768 노트북(브라우저 안 높이 약 650~700)에서도 장면이 고정되게. 700~799 는 pado-scene.css 가 카드 · 제목 · 그림판을
   작게 줄여 좁혀지기 장면 내용 + 위 바(64) + 아래 소개 순서(72)가 한 화면에 들어가게 한다(10/14 · 800 → 700).
   관성 보간 — 휠 한 칸(약 100px)마다 연출 값이 뚝 뛰지 않게, 장면마다 목표(target = 그 장면 진행도)를 두고
   현재 값(cur)이 지수 감쇠로 따라간다: cur += (target − cur)·(1 − e^(−dt·K)). 장면은 cur 로만 그린다.
   네이티브 스크롤은 그대로다(가로채지 않는다) — 늦게 따라오는 것은 연출 값뿐. 수렴(|Δ| < EPS)하거나 탭이 숨으면 루프를 멈춘다.
   정지 상태 · 처음 그림 · 크기 변경 뒤에는 보간 없이 바로 목표로(snap). */
(function () {
  "use strict";
  const root = document.documentElement;
  root.classList.add("js");   // .reveal 은 html.js 일 때만 숨는다 (veilo.css) — 스크립트가 안 돌면 글이 숨은 채 남지 않게
  const KEY = "padopool_motion";
  const PIN_MQ = "(min-width:768px) and (min-height:700px)";
  const PIN = matchMedia(PIN_MQ);
  // 휴대폰(폭 767 이하) — 장면을 고정하진 않지만 움직임은 켠다(흐름 모드 · html.ps-flow). 좁혀지기 · 네 단계가 스크롤에 맞춰 반응한다 (10/14)
  const FLOW = matchMedia("(max-width:767px)");
  const RM = matchMedia("(prefers-reduced-motion: reduce)");
  const STATIC = new URLSearchParams(location.search).get("view") === "static";

  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const smooth = (t) => { t = clamp(t); return t * t * (3 - 2 * t); };

  let paused = false;
  try { paused = localStorage.getItem(KEY) === "off"; } catch (e) {}

  function pinned() { return !paused && !STATIC && !RM.matches && PIN.matches; }
  // 모드 — pin(고정 장면) · flow(휴대폰 · 고정 없이 움직임) · still(정지 — 움직임 끔 · 동작 줄이기 · ?view=static · 낮은 데스크톱)
  function mode() { return pinned() ? "pin" : (!paused && !STATIC && !RM.matches && FLOW.matches ? "flow" : "still"); }
  const flowScenes = [];

  // ── 측정 캐시 ──
  const geo = new Map();   // el → { top, h }
  const view = { vh: innerHeight, max: 1 };
  const refreshHooks = [];
  const scenes = [];
  let dirty = true, queued = false;
  // 관성 보간 — K 가 클수록 빨리 따라간다. K=9: 95% 0.33초 · 99% 0.51초 (휠 한 칸 뒤 실측은 check_motion 이 잰다)
  const K = 9, EPS = 0.0005;
  let lastT = 0, snap = true, running = false;

  function track(el) { if (el && !geo.has(el)) { geo.set(el, { top: 0, h: 0 }); if (ro) ro.observe(el); dirty = true; } return el; }
  function g(el) { return geo.get(el) || { top: 0, h: 0 }; }
  function top(el) { return g(el).top; }
  function height(el) { return g(el).h; }
  function release(el) { const m = g(el); return m.top + m.h - view.vh; }
  // 핀 장면 안에서의 진행도 0~1 — 바깥 섹션의 위쪽이 화면 위에 닿을 때 0, 아래쪽이 화면 아래에 닿을 때 1
  function local(el, y) { const m = g(el); return clamp((y - m.top) / Math.max(1, m.h - view.vh)); }

  function refresh() {
    const sy = scrollY;
    view.vh = innerHeight;
    view.max = Math.max(1, root.scrollHeight - view.vh);
    geo.forEach((m, el) => { const r = el.getBoundingClientRect(); m.top = r.top + sy; m.h = r.height; });
    refreshHooks.forEach((fn) => fn(view));
  }

  function frame(t) {
    queued = false;
    if (dirty) { dirty = false; refresh(); snap = true; }
    const y = scrollY;
    const on = pinned();
    if (!on && mode() === "flow") for (const fn of flowScenes) fn(y, view);
    // dt — 쉬다가 다시 도는 첫 프레임(마지막 프레임이 0.1초보다 전)은 한 프레임(1/60)으로 친다
    const dt = lastT && t - lastT < 100 ? (t - lastT) / 1000 : 1 / 60;
    lastT = t;
    const a = 1 - Math.exp(-dt * K);
    let moving = false;
    for (const s of scenes) {
      if (s.el) {
        const target = on ? local(s.el, y) : 1;
        if (snap || !on) s.cur = target;
        else {
          s.cur += (target - s.cur) * a;
          if (Math.abs(target - s.cur) < EPS) s.cur = target; else moving = true;
        }
        s.target = target;
        s.fn(s.cur, on, view);
      } else s.fn(y, on, view);
    }
    snap = false;
    setRunning(moving && !document.hidden);
    if (running) schedule();
  }
  // 루프가 도는지 — html[data-ps-loop] (성능 확인용 표시 · check_motion 이 읽는다)
  function setRunning(v) { if (v !== running) { running = v; root.dataset.psLoop = v ? "on" : "off"; } }
  root.dataset.psLoop = "off";
  function schedule() { if (!queued) { queued = true; requestAnimationFrame(frame); } }
  function invalidate() { dirty = true; schedule(); }
  // 탭이 숨으면 브라우저가 rAF 를 멈춘다 — 돌아오면 남은 거리만큼 다시 이어서 보간
  document.addEventListener("visibilitychange", () => { if (document.hidden) setRunning(false); else { lastT = 0; schedule(); } });

  const ro = "ResizeObserver" in window ? new ResizeObserver(invalidate) : null;
  if (ro) ro.observe(document.body);
  addEventListener("scroll", schedule, { passive: true });
  addEventListener("resize", invalidate, { passive: true });
  addEventListener("load", invalidate);

  // ── 타임라인 — 키프레임 [{at, v:{...}}] 를 측정 뒤에만 다시 만든다. 같은 at 이 두 번이면 그 사이는 멈춤 구간 ──
  function createTimeline(build) {
    let keys = [], sig = "";
    refreshHooks.push(() => {
      const next = build();
      const s = next.map((k) => Math.round(k.at)).join(",");
      if (s !== sig) { sig = s; keys = next; }
    });
    return {
      sample(y) {
        if (!keys.length) return {};
        if (y <= keys[0].at) return keys[0].v;
        for (let i = 1; i < keys.length; i++) {
          const a = keys[i - 1], b = keys[i];
          if (y <= b.at) {
            const t = smooth((y - a.at) / Math.max(1, b.at - a.at));
            const out = {};
            for (const k in b.v) out[k] = a.v[k] + (b.v[k] - a.v[k]) * t;
            return out;
          }
        }
        return keys[keys.length - 1].v;
      },
    };
  }

  // ── 모드 전환 — 정지 ↔ 움직임. 읽던 섹션과 그 안의 비율을 기억했다가 높이가 바뀐 뒤 같은 자리로 ──
  const sections = () => Array.from(document.querySelectorAll("[data-ps-section]"));
  function readingSpot() {
    const list = sections();
    let cur = null;
    for (const s of list) if (s.getBoundingClientRect().top <= innerHeight * 0.1) cur = s;
    if (!cur) return null;
    const r = cur.getBoundingClientRect();
    return { el: cur, ratio: clamp(-r.top / Math.max(1, r.height)) };
  }
  function applyMode(keepSpot) {
    const spot = keepSpot ? readingSpot() : null;
    const m = mode(), still = m !== "pin";
    root.classList.toggle("ps-static", still);              // 고정 장면이 아니다(레이아웃은 흐르는 쪽)
    root.classList.toggle("ps-flow", m === "flow");         // 휴대폰 흐름 모드 — 움직임은 켠다
    root.classList.toggle("no-motion", m === "still");      // 정지 상태는 이 클래스 하나로 공통 효과까지 끈다 (veilo.css · fx.css · fx.js)
    snap = true;   // 모드가 바뀌면 보간 없이 바로 그 자리 모습으로
    document.dispatchEvent(new CustomEvent("padomotion", { detail: { still: m === "still", mode: m } }));
    document.querySelectorAll("[data-motion-toggle]").forEach((b) => {
      b.setAttribute("aria-pressed", String(!paused));
      b.textContent = paused ? "움직임 켜기" : "움직임 끄기";
    });
    if (spot) {
      const r = spot.el.getBoundingClientRect();
      const y = r.top + scrollY + spot.ratio * r.height;
      scrollTo({ top: y, behavior: "instant" });
    }
    invalidate();
  }
  function setPaused(v) {
    paused = v;
    try { localStorage.setItem(KEY, v ? "off" : "on"); } catch (e) {}
    applyMode(true);
  }
  const onMedia = () => applyMode(true);
  (PIN.addEventListener ? PIN.addEventListener("change", onMedia) : PIN.addListener(onMedia));
  (RM.addEventListener ? RM.addEventListener("change", onMedia) : RM.addListener(onMedia));
  (FLOW.addEventListener ? FLOW.addEventListener("change", onMedia) : FLOW.addListener(onMedia));

  function wireToggles() {
    document.querySelectorAll("[data-motion-toggle]").forEach((b) => {
      if (STATIC) { b.hidden = true; return; }   // 주소로 정지 화면을 고른 경우 — 켜도 움직이지 않으니 버튼을 두지 않는다
      b.addEventListener("click", () => setPaused(!paused));
    });
  }

  window.PadoMotion = {
    mode,
    // addFlowScene(fn) — 휴대폰 흐름 모드에서만 fn(y, view) 로 스크롤마다 부른다(장면이 고정되지 않아 요소 자리로 직접 진행을 잰다)
    addFlowScene(fn) { flowScenes.push(fn); schedule(); },
    clamp, smooth, local, top, height, release, track, pinned, PIN_MQ, schedule, invalidate, createTimeline, view,
    // addScene(fn, el) — el 을 주면 fn(cur, on, view) 로 그 장면의 보간된 진행도(0~1)를 받는다. 정지 상태면 cur = 1.
    //                    el 이 없으면 fn(y, on, view) — 스크롤 위치를 그대로 따라야 하는 것(읽기 진행 막대 등)
    addScene(fn, el) { scenes.push({ fn, el: el || null, cur: 0, target: 0 }); schedule(); },
    // 디버그 · 측정용 — 보간 중인 장면의 { target, cur } (check_motion 이 읽는다)
    probe() { return scenes.filter((s) => s.el).map((s) => ({ id: s.el.id, target: s.target, cur: s.cur })); },
    onRefresh(fn) { refreshHooks.push(fn); },
    start() { wireToggles(); applyMode(false); },
  };
})();
