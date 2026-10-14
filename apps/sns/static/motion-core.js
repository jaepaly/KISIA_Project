/* 스크롤 연출 공통 엔진 — 소개 화면(about.html · pado-scene.js)이 쓴다.
   원칙: 스크롤 · 크기 변경 → rAF 에 한 번만 → 장면 함수들이 같은 y 로 갱신한다.
   위치 측정(getBoundingClientRect)은 refresh 에서만 — ResizeObserver · resize 가 「다시 재라」고 표시해 둔다.
   프레임 안에서는 읽은 값(캐시)만 쓰고 스타일만 바꾼다 — 쓰고 나서 다시 읽는 강제 레이아웃이 없다.
   움직임을 안 쓰는 경우(움직임 끄기 · 시스템 「동작 줄이기」 · ?view=static · 폭 760px 이하)는
   html.ps-static — 장면은 「다 켜진 정지 상태」로 그린다. 760 은 CSS 의 @media (max-width:760px) 와 같은 값이다. */
(function () {
  "use strict";
  const root = document.documentElement;
  const KEY = "padopool_motion";
  const WIDE = matchMedia("(min-width:761px)");
  const RM = matchMedia("(prefers-reduced-motion: reduce)");
  const STATIC = new URLSearchParams(location.search).get("view") === "static";

  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const smooth = (t) => { t = clamp(t); return t * t * (3 - 2 * t); };

  let paused = false;
  try { paused = localStorage.getItem(KEY) === "off"; } catch (e) {}

  function pinned() { return !paused && !STATIC && !RM.matches && WIDE.matches; }

  // ── 측정 캐시 ──
  const geo = new Map();   // el → { top, h }
  const view = { vh: innerHeight, max: 1 };
  const refreshHooks = [];
  const scenes = [];
  let dirty = true, queued = false;

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

  function frame() {
    queued = false;
    if (dirty) { dirty = false; refresh(); }
    const y = scrollY;
    const on = pinned();
    for (const fn of scenes) fn(y, on, view);
  }
  function schedule() { if (!queued) { queued = true; requestAnimationFrame(frame); } }
  function invalidate() { dirty = true; schedule(); }

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
    root.classList.toggle("ps-static", !pinned());
    root.classList.toggle("no-motion", paused || RM.matches);
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
  (WIDE.addEventListener ? WIDE.addEventListener("change", onMedia) : WIDE.addListener(onMedia));
  (RM.addEventListener ? RM.addEventListener("change", onMedia) : RM.addListener(onMedia));

  function wireToggles() {
    document.querySelectorAll("[data-motion-toggle]").forEach((b) => {
      if (STATIC) { b.hidden = true; return; }   // 주소로 정지 화면을 고른 경우 — 켜도 움직이지 않으니 버튼을 두지 않는다
      b.addEventListener("click", () => setPaused(!paused));
    });
  }

  window.PadoMotion = {
    clamp, smooth, local, top, height, release, track, pinned, schedule, invalidate, createTimeline, view,
    addScene(fn) { scenes.push(fn); schedule(); },
    onRefresh(fn) { refreshHooks.push(fn); },
    start() { wireToggles(); applyMode(false); },
  };
})();
