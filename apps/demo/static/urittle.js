/* 우리뜰 화면 효과 — 전부 «보이는 것» 만 다룬다. 서버 값은 data-* 로 받고, 여기서는 숫자를 세고 막대를 그린다.
   prefers-reduced-motion 이면 애니메이션 없이 최종 상태로 바로 간다. */
(function () {
  "use strict";
  const RM = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fmt = (n) => Math.round(n).toLocaleString("ko-KR");
  const ease = (t) => 1 - Math.pow(1 - t, 3);
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  // ── 숫자 세기 ────────────────────────────────────────────────────────────
  function countTo(el, to, opts) {
    opts = opts || {};
    const from = opts.from != null ? opts.from : (parseFloat(String(el.dataset.from || "").replace(/,/g, "")) || 0);
    const dur = opts.dur || (Math.abs(to - from) > 1e5 ? 1500 : 1100);
    if (RM || document.hidden || !isFinite(to)) { el.textContent = fmt(to); return; }   // 숨긴 탭은 rAF 가 멈춘다 — 최종값으로
    const t0 = performance.now();
    el.classList.add("counting");
    (function step(now) {
      const p = Math.min(1, (now - t0) / dur);
      el.textContent = fmt(from + (to - from) * ease(p));
      if (p < 1) requestAnimationFrame(step); else el.classList.remove("counting");
    })(t0);
  }
  function runCount(el) {
    if (el.dataset.counted) return;
    el.dataset.counted = "1";
    const to = parseFloat(String(el.dataset.count).replace(/,/g, ""));
    countTo(el, to);
  }

  // ── 링 게이지 ────────────────────────────────────────────────────────────
  const C = 2 * Math.PI * 36;
  function drawRing(svg, risk, css) {
    const pr = $("[data-ring]", svg), num = $("[data-ring-num]", svg);
    svg.classList.remove("hi", "mid", "low"); if (css) svg.classList.add(css);
    if (risk == null || isNaN(risk)) { if (num) num.textContent = "—"; return; }
    if (num) { num.textContent = "0"; countTo(num, risk, { from: 0, dur: 1200 }); }
    requestAnimationFrame(() => { pr.style.strokeDashoffset = String(C * (1 - Math.max(0, Math.min(100, risk)) / 100)); });
  }
  function initRings(root) {
    $$(".ring[data-risk]", root).forEach((svg) => {
      if (svg.dataset.drawn) return; svg.dataset.drawn = "1";
      drawRing(svg, parseFloat(svg.dataset.risk), svg.dataset.css);
    });
  }

  // ── 깔때기 막대 — 로그 척도. 전 국민이 100% ──────────────────────────────
  function initFunnels(root) {
    $$("ul.funnel[data-nation]", root).forEach((ul) => {
      if (ul.dataset.bars) return; ul.dataset.bars = "1";
      const nation = Math.log10(parseFloat(ul.dataset.nation) || 5e7);
      const lis = $$("li[data-n]", ul);
      lis.forEach((li, i) => {
        const n = parseFloat(li.dataset.n);
        const w = n > 0 ? Math.max(1.5, 100 * Math.log10(n + 1) / nation) : 1.5;
        const bar = document.createElement("span");
        bar.className = "bar"; bar.style.width = "100%";
        bar.style.transitionDelay = (RM ? 0 : 90 * i) + "ms";
        li.appendChild(bar);
        const k = $(".k", li);
        if (k && !k.dataset.count) { k.dataset.count = String(n); k.dataset.from = String(n); }
        requestAnimationFrame(() => requestAnimationFrame(() => { bar.style.width = w + "%"; }));
      });
    });
  }

  // ── 스크롤 리빌 ──────────────────────────────────────────────────────────
  const AUTO_RV = ".ut-card,.card,.act,.evi,.rail-card,.ut-pado,.pado-panel,.trap,.hero";
  function reveal(el) {
    if (el.classList.contains("in")) return;
    el.classList.add("in");
    $$("[data-count]", el).forEach(runCount);
    if (el.matches("[data-count]")) runCount(el);
    initRings(el);
  }
  function initReveal() {
    $$(AUTO_RV).forEach((el) => { if (!el.classList.contains("rv")) el.classList.add("rv"); });
    const items = $$(".rv").concat($$("[data-count]").filter((el) => !el.closest(".rv")));
    if (RM || !("IntersectionObserver" in window)) { items.forEach(reveal); return; }
    const io = new IntersectionObserver((ents) => {
      ents.forEach((e) => { if (e.isIntersecting) { reveal(e.target); io.unobserve(e.target); } });
    }, { rootMargin: "0px 0px -6% 0px", threshold: 0.01 });
    items.forEach((el) => io.observe(el));
    // 관찰자가 늦어도(백그라운드 탭·구형 브라우저) 내용이 숨겨진 채 남지 않게 — 화면 안은 즉시, 나머지는 2.5초 뒤
    const vh = innerHeight;
    items.forEach((el) => { if (el.getBoundingClientRect().top < vh * 0.94) reveal(el); });
    setTimeout(() => items.forEach(reveal), 2500);
  }

  // ── 깔때기 ↔ 근거 연결 ───────────────────────────────────────────────────
  function initLinking() {
    const lens = $("#lensSwitch");
    function lensOn() {
      if (lens && lens.getAttribute("aria-checked") !== "true") window.toggleLens(lens);
    }
    $$("[data-span-link]").forEach((li) => {
      const id = li.dataset.spanLink;
      const marks = $$('mark[data-span="' + CSS.escape(id) + '"]');
      if (!marks.length) { li.classList.add("nolink"); return; }
      li.classList.add("linkable");
      li.addEventListener("mouseenter", () => marks.forEach((m) => { m.classList.add("hot"); const c = m.closest(".evi"); c && c.classList.add("hot"); }));
      li.addEventListener("mouseleave", () => marks.forEach((m) => { m.classList.remove("hot"); const c = m.closest(".evi"); c && c.classList.remove("hot"); }));
      li.addEventListener("click", (ev) => {
        if (ev.target.closest("a")) return;
        lensOn();
        marks[0].scrollIntoView({ behavior: RM ? "auto" : "smooth", block: "center" });
        marks.forEach((m) => { m.classList.remove("flash"); void m.offsetWidth; m.classList.add("flash"); });
      });
    });
    $$("mark[data-span]").forEach((m) => {
      const li = $('[data-span-link="' + CSS.escape(m.dataset.span) + '"]');
      if (!li) return;
      m.addEventListener("mouseenter", () => li.classList.add("hot"));
      m.addEventListener("mouseleave", () => li.classList.remove("hot"));
    });
  }
  window.toggleLens = function (btn) {
    const on = btn.getAttribute("aria-checked") !== "true";
    btn.setAttribute("aria-checked", String(on));
    const ev = $("#evidence"); ev && ev.classList.toggle("lens-off", !on);
    const lg = $("#lensLegend"); if (lg) lg.hidden = !on;
  };

  // ── 레일 파도풀 위젯 — 비동기로 k 를 받아 온다 ────────────────────────────
  function initRailWidget() {
    $$("[data-pado-widget]").forEach((w) => {
      const ref = w.dataset.padoWidget, num = $("[data-k]", w), lvl = $("[data-lvl]", w), sub = $("[data-sub]", w), ring = $(".ring", w);
      w.classList.add("loading"); sub && sub.classList.add("shimmer");
      fetch("/u/" + encodeURIComponent(ref) + "/check.json", { headers: { Accept: "application/json" } })
        .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
        .then((d) => {
          w.classList.remove("loading"); sub && sub.classList.remove("shimmer");
          if (num) { num.dataset.from = "0"; countTo(num, d.k, { from: 0, dur: 1400 }); }
          if (lvl) { lvl.textContent = d.label + " · 공개 " + d.n_posts + "편"; lvl.className = "lvl " + d.css; }
          if (sub) sub.innerHTML = "직접 식별자 <b>" + d.n_direct + "건</b>인데 후보가 <b>" + fmt(d.k) + "명</b>까지 좁혀집니다. 조치 " + d.n_actions + "개를 다 하면 <b>" + fmt(d.projected_k) + "명</b>.";
          if (ring) drawRing(ring, d.risk, d.css);
        })
        .catch(() => {
          w.classList.remove("loading"); sub && sub.classList.remove("shimmer");
          if (num) num.textContent = "—";
          if (lvl) { lvl.textContent = "파도풀에 연결하지 못했습니다"; lvl.className = "lvl"; }
        });
    });
  }

  // ── 장식 — 좋아요 · 이웃추가 (저장 안 함) ────────────────────────────────
  function initDecor() {
    $$(".like").forEach((el) => el.addEventListener("click", (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      const b = $("b", el); if (!b) return;
      const on = el.classList.toggle("hit");
      b.textContent = String(parseInt(b.textContent, 10) + (on ? 1 : -1));
      if (!on) el.classList.remove("hit");
    }));
    $$(".ut-follow").forEach((btn) => btn.addEventListener("click", () => {
      const on = btn.classList.toggle("done");
      btn.textContent = on ? "✓ 이웃" : "+ 이웃추가";
    }));
    const top = $(".ut-top");
    if (top) {
      const onScroll = () => top.classList.toggle("scrolled", scrollY > 8);
      addEventListener("scroll", onScroll, { passive: true }); onScroll();
    }
  }

  // ── 조치 체크리스트(레일) → 카드로 ───────────────────────────────────────
  function initActRail() {
    $$("[data-goto]").forEach((a) => a.addEventListener("click", (ev) => {
      const t = $(a.dataset.goto); if (!t) return;
      ev.preventDefault();
      t.scrollIntoView({ behavior: RM ? "auto" : "smooth", block: "start" });
      t.classList.remove("flash"); void t.offsetWidth; t.classList.add("flash");
    }));
  }

  function boot() {
    initFunnels(document);
    initReveal();
    initRings(document);
    initLinking();
    initRailWidget();
    initDecor();
    initActRail();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
