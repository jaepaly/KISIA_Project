/* Veilo 화면 효과 — 전부 «보이는 것» 만 다룬다. 서버 값은 data-* 로 받고, 여기서는 숫자를 세고 막대를 그린다.
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
        revealMark(marks[0]);
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
          if (lvl) { lvl.textContent = d.label + ", 공개 글 " + d.n_posts + "편"; lvl.className = "lvl " + d.css; }
          if (sub) sub.innerHTML = "이름과 전화번호 <b>" + d.n_direct + "건</b> / 같은 조건의 사람 약 <b>" + fmt(d.k) + "명</b> / 추천 방법 " + d.n_actions + "개를 모두 적용하면 약 <b>" + fmt(d.projected_k) + "명</b>";
          if (ring) drawRing(ring, d.risk, d.css);
        })
        .catch(() => {
          w.classList.remove("loading"); sub && sub.classList.remove("shimmer");
          if (num) num.textContent = "—";
          if (lvl) { lvl.textContent = "파도풀에 연결하지 못했습니다."; lvl.className = "lvl"; }
        });
    });
  }

  // ── 장식 — 좋아요 · 이웃추가 (저장 안 함) ────────────────────────────────
  function initDecor() {
    // 카드 전체 클릭 — 안의 버튼·링크·폼은 제 역할 그대로
    $$(".ut-card[data-href]").forEach((c) => c.addEventListener("click", (e) => {
      if (e.target.closest("a,button,form,input,.like")) return;
      location.href = c.dataset.href;
    }));
    $$(".like").forEach((el) => el.addEventListener("click", (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      const b = $("b", el); if (!b) return;
      const on = el.classList.toggle("hit");
      b.textContent = String(parseInt(b.textContent, 10) + (on ? 1 : -1));
      if (!on) el.classList.remove("hit");
    }));
    $$(".ut-follow").forEach((btn) => btn.addEventListener("click", () => {
      const on = btn.classList.toggle("done");
      btn.textContent = on ? "✓ 이웃" : "+ 이웃 추가";
    }));
    // 점검 중 표시 — 파도풀 호출은 0.7초(규칙)에서 3~10초(Claude 켬)까지 걸린다. 누르자마자 가운데에 원이 돌고 글이 뜬다
    const busy = (msg) => {
      if ($(".ut-busy")) return;
      const o = document.createElement("div"); o.className = "ut-busy";
      o.innerHTML = '<div class="box"><div class="spin"></div><b></b><span>공개 글의 개인정보 단서를 찾고 있습니다.</span></div>';
      o.querySelector("b").textContent = msg || "파도풀로 점검 중…";   // data-busy 문구는 글자로만 — HTML 로 해석하지 않는다
      document.body.appendChild(o);
    };
    const unbusy = () => { const o = $(".ut-busy"); o && o.remove(); };
    document.addEventListener("click", (e) => {
      const el = e.target.closest("[data-busy]"); if (!el || e.defaultPrevented) return;
      if (el.tagName === "A" && (e.metaKey || e.ctrlKey || el.target === "_blank")) return;
      // 보내는 폼이 「본문을 적어 주세요」 같은 검사에 걸리면 아무 일도 안 일어난다 — 그때 원만 돌면 멈춘 것처럼 보인다
      const form = el.form || (el.tagName === "BUTTON" ? el.closest("form") : null);
      if (form && typeof form.checkValidity === "function" && !el.formNoValidate && !form.noValidate
          && !form.checkValidity()) return;
      setTimeout(() => busy(el.dataset.busy), 0);
    });
    document.addEventListener("invalid", unbusy, true);     // 뒤늦게 걸려도 원을 치운다
    addEventListener("pageshow", () => { const o = $(".ut-busy"); o && o.remove(); });   // 뒤로가기(bfcache)로 돌아오면 지운다

    // 「점검」은 «내가 눌러서 지금 도는 일» 로 읽혀야 한다. 화면이 눈 깜짝할 새 뜨면 눌리기 전부터
    // 있던 화면처럼 보인다. 그렇다고 가짜로 늦추지는 않는다 — 실제로 걸린 시간을 재서 **모자란 만큼만** 채운다.
    // (숫자·깔때기는 누를 때마다 진짜로 다시 센다. 미리 만들어 둔 것은 「다르게 쓰기」 문구뿐이다.)
    const MIN_CHECK_MS = 1400;      // 「눌렀더니 돌았다」 로 읽히는 최소치. 예전(3~8초)보다 한참 짧다
    if (document.body.classList.contains("check-page")) {
      let took = 0;
      try {
        const e = performance.getEntriesByType("navigation")[0];
        took = e ? e.responseEnd - e.startTime : 0;
      } catch (err) { took = 0; }
      const left = Math.round(MIN_CHECK_MS - took);
      if (took > 0 && left > 120) {
        busy("파도풀로 점검 중…");
        setTimeout(() => { const o = $(".ut-busy"); o && o.remove(); }, left);
      }
    }
    // ⋯ 메뉴 — 글 화면 오른쪽 위. 바깥 클릭·Esc 로 닫힌다
    $$("[data-menu]").forEach((m) => {
      const btn = $("[data-menu-btn]", m), pop = $(".ut-menu-pop", m);
      const set = (on) => { pop.hidden = !on; btn.setAttribute("aria-expanded", String(on)); };
      btn.addEventListener("click", (e) => { e.stopPropagation(); set(pop.hidden); });
      document.addEventListener("click", (e) => { if (!m.contains(e.target)) set(false); });
      document.addEventListener("keydown", (e) => { if (e.key === "Escape") set(false); });
    });
    // 모바일 드로어 — 사이드바를 ☰ 로 연다 (핸드오프: 모바일은 사이드바를 접고 드로어로)
    const side = $("[data-drawer-panel]"), scrim = $("[data-drawer-close]");
    const drawer = (on) => { if (!side) return; side.classList.toggle("open", on); if (scrim) scrim.hidden = !on; };
    $$("[data-drawer]").forEach((b) => b.addEventListener("click", () => drawer(!side.classList.contains("open"))));
    scrim && scrim.addEventListener("click", () => drawer(false));
    side && side.addEventListener("click", (e) => { if (e.target.closest("a")) drawer(false); });
    const top = $(".ut-top");
    if (top) {
      const onScroll = () => top.classList.toggle("scrolled", scrollY > 8);
      addEventListener("scroll", onScroll, { passive: true }); onScroll();
    }
  }

  // ── 모바일 상단바 · 맨 위로 (#385 B4 · B5) ──────────────────────────────────
  // 좁은 화면에서 아래로 내리면 상단바를 접고, 조금이라도 올리면 다시 편다. 하단 메뉴(.ut-tabs)는 그대로.
  // 넓은 화면 · 소개 화면(ps-page · 자체 헤더와 sticky 장면이 상단바 높이에 맞춰 있다)은 건드리지 않는다.
  // 화면 높이 1.5배 아래로 내려가면 「맨 위로」 버튼 — 모바일은 하단 메뉴 위쪽에 뜬다(veilo.css .ut-totop)
  function initMobileChrome() {
    const top = $(".ut-top"), mq = matchMedia("(max-width:767px)");
    const intro = document.documentElement.classList.contains("ps-page");
    let lastY = scrollY;
    const keepTop = () => !mq.matches || intro || scrollY < top.offsetHeight * 2 ||
      top.contains(document.activeElement) || !!$(".ut-menu-pop:not([hidden])", top);
    const onTop = () => {
      const y = scrollY, dy = y - lastY;
      if (keepTop()) top.classList.remove("hide-up");
      else if (dy > 4) top.classList.add("hide-up");
      else if (dy < -4) top.classList.remove("hide-up");
      if (Math.abs(dy) > 4 || keepTop()) lastY = y;
    };
    if (top) {
      addEventListener("scroll", onTop, { passive: true });
      top.addEventListener("focusin", () => top.classList.remove("hide-up"));   // 키보드로 상단바에 들어오면 편다
      (mq.addEventListener ? mq.addEventListener("change", onTop) : mq.addListener(onTop));
    }
    if (intro) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ut-totop";
    btn.hidden = true;
    btn.setAttribute("aria-label", "맨 위로 가기");
    btn.innerHTML = '<span aria-hidden="true">↑</span> 맨 위로';
    document.body.appendChild(btn);
    const onBtn = () => { btn.hidden = scrollY < innerHeight * 1.5; };
    addEventListener("scroll", onBtn, { passive: true });
    addEventListener("resize", onBtn, { passive: true });
    onBtn();
    btn.addEventListener("click", () => {
      const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
      scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
      if (top) top.classList.remove("hide-up");
      // 포커스도 맨 위로 — 키보드 · 화면 낭독기 사용자가 버튼 자리에 남지 않게
      const logo = top && $(".ut-logo", top);
      if (logo) logo.focus({ preventScroll: true });
    });
  }

  // ── 점검 화면의 네 걸음(탭) — 한 번에 한 카드만. 해시로 어디든 바로 갈 수 있다 ──────────
  const TAB_NAMES = { sum: "요약", funnel: "어떻게 좁혀지나", evidence: "근거 문장", actions: "위험 줄이기" };
  function tabList() { return $$(".pado-tabs a[data-tab]").map((a) => a.dataset.tab); }
  function showTab(name, opts) {
    opts = opts || {};
    const tabs = tabList(); if (!tabs.length || !tabs.includes(name)) return false;
    $$(".card[data-tab]").forEach((c) => { c.hidden = c.dataset.tab !== name; });
    $$(".pado-tabs a[data-tab]").forEach((a) => {
      a.classList.toggle("on", a.dataset.tab === name);
      if (tabs.indexOf(a.dataset.tab) < tabs.indexOf(name)) a.classList.add("seen");
    });
    const card = $('.card[data-tab="' + name + '"]');
    if (card) { $$(".rv", card).forEach(reveal); if (card.classList.contains("rv")) reveal(card); }
    try { history.replaceState(null, "", "#" + (card ? card.id : name)); } catch (e) {}
    if (!opts.keepScroll) { const bar = $(".pado-tabs"); if (bar && bar.getBoundingClientRect().top < 0) bar.scrollIntoView({ behavior: RM ? "auto" : "smooth", block: "start" }); }
    return true;
  }
  function tabOf(el) { const c = el && el.closest && el.closest(".card[data-tab]"); return c ? c.dataset.tab : null; }
  function showTabFor(el, opts) { const t = tabOf(el); if (t && $('.card[data-tab="' + t + '"]').hidden) showTab(t, opts); }
  window.padoShowTab = showTab;
  function initTabs() {
    const tabs = tabList(); if (!tabs.length) return;
    $$(".pado-tabs a[data-tab]").forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); showTab(a.dataset.tab); }));
    // 카드마다 «이전 / 다음» 줄
    $$(".card[data-tab]").forEach((card) => {
      const i = tabs.indexOf(card.dataset.tab);
      const nav = document.createElement("div"); nav.className = "tab-nav";
      nav.innerHTML = '<button type="button" class="prev"' + (i === 0 ? " disabled" : "") + '>← 이전</button>'
        + '<span class="pos">' + (i + 1) + " / " + tabs.length + "</span>"
        + (i < tabs.length - 1 ? '<button type="button" class="next">다음: ' + TAB_NAMES[tabs[i + 1]] + " →</button>" : '<span style="margin-left:auto">바꾼 뒤 다시 점검하면 결과를 확인할 수 있습니다.</span>');
      card.appendChild(nav);
      const prev = $(".prev", nav), next = $(".next", nav);
      prev && prev.addEventListener("click", () => showTab(tabs[i - 1]));
      next && next.addEventListener("click", () => showTab(tabs[i + 1]));
    });
    // 해시로 들어오면 그 카드부터 (#actions · #act-2 · #evidence-card)
    const h = (location.hash || "").slice(1);
    let start = tabs[0];
    if (h) { const el = document.getElementById(h); const t = el && (el.dataset.tab || tabOf(el)); if (t && tabs.includes(t)) start = t; }
    showTab(start, { keepScroll: true });
    if (h && h !== start) { const el = document.getElementById(h); el && setTimeout(() => el.scrollIntoView({ behavior: RM ? "auto" : "smooth", block: "start" }), 50); }
  }

  // ── 근거 문장 — 카드 접기 · 나머지 펼치기 ────────────────────────────────
  function initEvidence() {
    $$("[data-evi-toggle]").forEach((w) => w.addEventListener("click", (e) => { if (e.target.closest("a")) return; w.parentElement.classList.toggle("folded"); }));
    $$("[data-evi-fold]").forEach((b) => b.addEventListener("click", () => {
      const all = b.dataset.eviFold === "all";
      $$("#evidence .evi").forEach((c) => c.classList.toggle("folded", all));
      if (!all) expandEvidence();
    }));
    const more = $("[data-evi-more]"); more && more.addEventListener("click", expandEvidence);
  }
  function expandEvidence() { const ev = $("#evidence"); ev && ev.classList.remove("collapsed"); const m = $("[data-evi-more]"); m && m.remove(); }
  function revealMark(mark) {   // 다른 탭·접힌 카드·숨긴 나머지 안의 표현으로 갈 때
    showTabFor(mark, { keepScroll: true });
    const card = mark.closest(".evi"); if (card) { card.classList.remove("folded"); if (card.classList.contains("extra")) expandEvidence(); }
  }

  // ── 조치 ③ 표현 바꾸기 — 후보 칩 한 줄, 고른 것만 펼친다 ──────────────────
  function initRewriteChips() {
    $$("[data-rw-group]").forEach((g) => {
      const act = g.closest(".act");
      const opts = $$("[data-rw-opt]", act);
      const chips = $$("button[data-rw]", g);
      const pick = (i) => { chips.forEach((c) => c.classList.toggle("on", c.dataset.rw === String(i))); opts.forEach((o) => { o.hidden = o.dataset.rwOpt !== String(i); }); };
      chips.forEach((c) => c.addEventListener("click", () => pick(c.dataset.rw)));
      pick(0);
    });
  }

  // ── 조치 체크리스트(레일) → 카드로 ───────────────────────────────────────
  function initActRail() {
    $$("[data-goto]").forEach((a) => a.addEventListener("click", (ev) => {
      const t = $(a.dataset.goto); if (!t) return;
      ev.preventDefault();
      showTabFor(t, { keepScroll: true });
      t.scrollIntoView({ behavior: RM ? "auto" : "smooth", block: "start" });
      t.classList.remove("flash"); void t.offsetWidth; t.classList.add("flash");
    }));
  }

  // ── 「더 보기」 — 미리보기가 실제로 잘린 글에만 붙인다 (… 만으로는 글이 거기서 끝나는지 알 수 없다) ──
  function initMore() {
    $$(".ut-excerpt").forEach((el) => {
      if (el.nextElementSibling && el.nextElementSibling.classList.contains("ut-more")) return;
      if (el.scrollHeight > el.clientHeight + 2) {
        const m = document.createElement("span");
        m.className = "ut-more"; m.textContent = "더 보기 →";
        el.insertAdjacentElement("afterend", m);
      }
    });
  }

  // ── 조치(비공개 · 위치 · 프로필 · 새 글 · 되돌리기)를 하면 글쓰기 화면의 「기존 공개 글」 점검 캐시를 지운다 ──
  // new.html 이 sessionStorage "veilo.scan.<user_ref>" 에 한 번 센 결과를 둔다 — 지우지 않으면 조치 뒤에도 옛 숫자가 나온다 (B5)
  function initFreshScan() {
    const clear = () => {
      try { Object.keys(sessionStorage).filter((k) => k.indexOf("veilo.scan.") === 0).forEach((k) => sessionStorage.removeItem(k)); } catch (e) {}
    };
    document.addEventListener("submit", (e) => { const f = e.target; if (f && (f.method || "").toLowerCase() === "post") clear(); }, true);
    // 조치 뒤 ?done=… 로 돌아온다 — 띠를 보여 준 뒤 주소에서 떼어 새로고침해도 다시 안 나오게 한다
    const u = new URL(location.href);
    if (u.searchParams.has("done")) {
      clear();
      u.searchParams.delete("done");
      try { history.replaceState(null, "", u.pathname + (u.search || "") + u.hash); } catch (e) {}
    }
  }

  function boot() {
    initFreshScan();
    initMore();
    initFunnels(document);
    initReveal();
    initRings(document);
    initLinking();
    initRailWidget();
    initDecor();
    initTabs();
    initEvidence();
    initRewriteChips();
    initActRail();
    initMobileChrome();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(initMore);   // 웹폰트가 늦게 오면 줄 높이가 바뀐다
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
