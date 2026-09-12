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
          if (sub) sub.innerHTML = "이름·전화번호 <b>" + d.n_direct + "건</b>인데 나일 수 있는 사람이 <b>" + fmt(d.k) + "명</b>까지 줄어요. 조치 " + d.n_actions + "개를 다 하면 <b>" + fmt(d.projected_k) + "명</b>이 돼요.";
          if (ring) drawRing(ring, d.risk, d.css);
        })
        .catch(() => {
          w.classList.remove("loading"); sub && sub.classList.remove("shimmer");
          if (num) num.textContent = "—";
          if (lvl) { lvl.textContent = "파도풀에 연결하지 못했어요"; lvl.className = "lvl"; }
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
      btn.textContent = on ? "✓ 이웃" : "+ 이웃추가";
    }));
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

  // ── 점검 화면의 네 걸음(탭) — 한 번에 한 카드만. 해시로 어디든 바로 갈 수 있다 ──────────
  const TAB_NAMES = { sum: "요약", funnel: "어떻게 좁혀지나", evidence: "근거 문장", actions: "이렇게 하면 넓어져요" };
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
    // 투어 말풍선 — 가리키던 곳이 다른 탭으로 숨으면 아래에 띄우고, 다시 보이면 제자리로
    const tm = $(".tour-mark:not(.done)"), ts = $(".tour-spot");
    if (tm && ts) { if (ts.offsetParent === null) tm.classList.add("floating"); else { tm.classList.remove("floating"); place(tm, ts); } }
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
        + (i < tabs.length - 1 ? '<button type="button" class="next">다음: ' + TAB_NAMES[tabs[i + 1]] + " →</button>" : '<span style="margin-left:auto">여기가 마지막이에요. 조치를 누르면 1번부터 다시 계산돼요</span>');
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

  // ── 투어 — 처음 온 사람을 시연 순서대로 데려간다. 상태는 localStorage, 페이지가 바뀌어도 이어진다 ──
  const TOUR_KEY = "pado_tour";
  const TOUR = [
    { page: (p) => p === "/", target: '.rail-nb a[href="/u/u_1a2e7dcc"]',
      title: "① 마당일기 님의 블로그로", text: "68세 할머니의 글 18편이에요. 이름도 지명도 한 번 안 나와요. 그런데도 사람이 좁혀지는지 볼게요.",
      advance: "click" },
    { page: (p) => p === "/u/u_1a2e7dcc", target: ".ut-pado a.go",
      title: "② 내 글 점검", text: "Veilo 가 이 계정의 공개 글만 파도풀에 보내요. 파도풀은 저장하지 않고 결과만 돌려줘요.",
      advance: "click" },
    { page: (p) => p === "/u/u_1a2e7dcc/check", target: "#sum .hero", when: () => !$(".delta-banner"),
      title: "③ 이름도 전화번호도 없는데 421명", text: "이름과 전화번호만 찾는 검사기라면 «안전»이에요. 파도풀은 글들을 합쳐서 봐서 전 국민 5,100만 명 중 421명까지 좁혀요.",
      advance: "next" },
    { page: (p) => p === "/u/u_1a2e7dcc/check", target: "#funnel ul.funnel", when: () => !$(".delta-banner"),
      title: "④ 어떻게 좁혀지나", text: "말투 → 면사무소 → 위치태그 → 「예순여덟」. 단계마다 실제 주민등록 인구예요. 줄을 누르면 그 문장으로 가요.",
      advance: "next" },
    { page: (p) => p === "/u/u_1a2e7dcc/check", target: "#evidence .evi:first-child", when: () => !$(".delta-banner"),
      title: "⑤ 근거 문장", text: "숫자가 나온 자리예요. 글은 원문 그대로이고 색칠된 부분이 신상이 드러나는 표현, 점선은 잡았지만 걸러낸 표현이에요. 갈색 칩은 말투로 잡은 지역이고요.",
      advance: "next" },
    { page: (p) => p === "/u/u_1a2e7dcc/check", target: '#actions form[action$="/geo_tag"] button',
      when: () => !$(".delta-banner") && !!$('#actions form[action$="/geo_tag"] button'),   // 태그를 이미 지웠으면 건너뛴다
      title: "⑥ 가장 가벼운 조치 하나", text: "글을 지우지 않고 위치태그만 꺼요. 눌러 보세요. 화면이 다시 계산돼요.",
      advance: "click" },
    { page: (p) => p === "/u/u_1a2e7dcc/check", target: ".delta-banner", when: () => !!$(".delta-banner"),
      title: "⑦ 421 → 111,069", text: "글은 하나도 안 지웠어요. 사라진 단서는 아래 표에 취소선으로 남아요.",
      advance: "next" },
    { page: (p) => p === "/u/u_1a2e7dcc/check", target: ".ut-nav a.write, .ut-tabs a[href='/new']",
      title: "⑧ 이번엔 올리기 전에", text: "체험 계정으로 아무 글이나 써 볼게요. 올리기 전에 한 번 점검해요.",
      advance: "click" },
    { page: (p) => p === "/new", target: 'button[formaction="/check-draft"]', when: () => !$("#draftSpans"),
      title: "⑨ 예문을 넣고 점검", text: "본문에 예문을 넣어 뒀어요. 「난 김해시 진영읍에 산다. 쉰셋이 되니 무릎이 아프다.」 작성자는 체험 계정이에요. 이 버튼을 누르면 올리기 전에 점검해요.",
      advance: "click", hint: "👆 이 버튼을 누르면 이어져요",
      onShow: () => { const t = $("#body"); if (t && !t.value.trim()) { t.value = "난 김해시 진영읍에 산다. 쉰셋이 되니 무릎이 아프다."; t.dispatchEvent(new Event("input")); } const s = $("#author_id"); if (s && s.querySelector('option[value="GUEST"]')) s.value = "GUEST"; } },
    { page: (p) => p === "/check-draft" || p === "/new", target: "#draftPreview mark[data-span], #draftPreview .fixed[data-span]", when: () => !!$("#draftSpans"), place: "above",
      title: "⑩ 색칠된 표현을 눌러 보세요", text: "지우지 않고 넓히는 안(진영읍 → 김해시 → 경남)과 각각의 숫자, 그리고 「그대로 두기」가 나와요. 고르는 건 글쓴이예요. 한 번 고른 표현도 다시 눌러 바꿀 수 있어요.",
      advance: "next" },
    { page: (p) => p === "/check-draft" || p === "/new", target: "#cmpBtn", when: () => !!$("#draftSpans") && !!$("#cmpBtn") && !$("#cmpTbl tbody tr"),
      title: "⑪ 같은 글을 다른 사람이 올리면?", text: "파도풀은 글 한 편이 아니라 «이미 올린 글까지 합쳐서» 봐요. 그래서 같은 문장이라도 누가 올리느냐에 따라 숫자가 달라요. 눌러서 비교해 보세요.",
      advance: "click", hint: "👆 이 버튼을 누르면 이어져요" },
    { page: (p) => p === "/check-draft" || p === "/new", target: "#cmpTbl", when: () => !!$("#cmpTbl tbody tr"),
      title: "⑫ 사람마다 다른 숫자", text: "체험 계정은 이 글 하나뿐이라 넓고, 글이 많은 계정은 이미 좁혀진 위에 얹혀요. 그래서 파도풀은 계정 단위로 봐요.",
      advance: "done" },
  ];
  function tourState() { try { return JSON.parse(localStorage.getItem(TOUR_KEY) || "null"); } catch (e) { return null; } }
  function tourSave(s) { try { if (s) localStorage.setItem(TOUR_KEY, JSON.stringify(s)); else localStorage.removeItem(TOUR_KEY); } catch (e) {} }
  window.padoTourStart = function () { tourSave({ step: 0 }); if (location.pathname !== "/") location.href = "/"; else renderTour(); };
  // 처음부터 — 투어 상태만이 아니라 글 데이터(끈 태그·비공개·고친 본문·새 글)도 시딩 값으로 되돌린다
  window.padoTourReset = function () {
    tourSave(null);
    const f = document.createElement("form"); f.method = "post"; f.action = "/demo/reset"; f.style.display = "none";
    document.body.appendChild(f); f.submit();
  };
  window.padoTourRefresh = function () { renderTour(); };   // 페이지를 안 바꾸고 화면이 바뀌었을 때(작성자 비교 표)
  window.padoTourStop = function () { tourSave({ done: true }); const c = $(".tour-mark"); c && c.remove(); const h = $(".tour-hole"); h && h.remove(); $$(".tour-spot").forEach((e) => e.classList.remove("tour-spot")); updateTourLinks(); updateWelcome(null); };
  // 첫 방문 카드 — 투어 중엔 한 줄 진행바로 접힌다 (시작을 눌렀는데 아무것도 안 바뀌면 눌린 줄 모른다)
  function updateWelcome(step) {
    const slot = $(".welcome-bar-slot"); if (!slot) return;
    let bar = $(".welcome-bar", slot);
    if (step == null) { bar && bar.remove(); return; }
    if (!bar) { bar = document.createElement("div"); bar.className = "welcome-bar"; slot.appendChild(bar); }
    bar.innerHTML = '<span class="n">▶ 3분 체험 진행 중</span><span class="p">' + (step + 1) + " / " + TOUR.length + '</span><span class="t">밝게 뚫린 곳을 따라가세요</span><button type="button" onclick="padoTourStop()">그만하기</button>';
  }
  function updateTourLinks() {
    const s = tourState();
    $$("[data-tour-welcome]").forEach((el) => { el.hidden = !!s; });   // 첫 방문(상태 없음)에만 모달. 시작·둘러보기·처음부터 가 상태를 정한다
    document.body.classList.toggle("welcome-open", !s && !!$("[data-tour-welcome]"));
    $$("[data-tour-restart]").forEach((el) => { el.hidden = !(s && s.done); });
  }
  function renderTour() {
    const s = tourState();
    updateTourLinks();
    const stale = $(".tour-mark"); stale && stale.remove();
    $$(".tour-spot").forEach((e) => e.classList.remove("tour-spot"));
    if (!s || s.done || s.step == null) { const h = $(".tour-hole"); h && h.remove(); updateWelcome(null); return; }
    const p = location.pathname;
    let i = s.step;
    // 현재 페이지에 맞는 단계로 — 앞 단계를 건너뛰었으면 따라잡고, 조건(when)이 안 맞으면 기다린다
    while (i < TOUR.length && !(TOUR[i].page(p) && (!TOUR[i].when || TOUR[i].when()))) {
      if (TOUR[i].page(p)) { i++; continue; }
      const later = TOUR.slice(i).findIndex((t) => t.page(p) && (!t.when || t.when()));
      if (later < 0) return;   // 이 페이지엔 할 일이 없다 — 사용자가 딴 데로 갔다. 원래 단계로 돌아오면 이어진다
      i += later;
    }
    if (i >= TOUR.length) { window.padoTourStop(); return; }
    if (i !== s.step) tourSave({ step: i });
    const st = TOUR[i];
    const visible = (el) => el && el.offsetParent !== null;
    let target = $$(st.target).find(visible) || null;
    if (!target) {   // 다른 탭(점검의 네 걸음) 안에 있으면 그 탭을 켠다
      const cand = $$(st.target)[0];
      if (cand && tabOf(cand)) { showTab(tabOf(cand), { keepScroll: true }); target = $$(st.target).find(visible) || null; }
    }
    st.onShow && st.onShow();
    const card = document.createElement("div");
    card.className = "tour-mark";
    if (st.place) card.dataset.place = st.place;
    card.innerHTML = '<div class="tt"><span class="n">' + (i + 1) + "/" + TOUR.length + "</span><span class=\"ti\">" + st.title + '</span><button type="button" class="fold" data-fold title="접기 / 펼치기" aria-label="접기">▾</button></div><div class="tx">' + st.text + "</div>"
      + '<div class="bt"><button type="button" class="skip" data-skip>건너뛰기</button>'
      + (st.advance === "next" ? '<button type="button" class="go" data-next>다음 →</button>' : st.advance === "done" ? '<button type="button" class="go" data-next>체험 끝 ✓</button>'
         : '<span class="hint">' + (target ? (st.hint || "👆 위 버튼을 누르면 이어져요") : "이 화면에는 그 버튼이 없어요. 건너뛰기를 눌러 주세요") + "</span>") + "</div>";
    document.body.appendChild(card);
    card.querySelector("[data-fold]").addEventListener("click", () => {      // 뒤가 안 보이면 접는다 — 링은 그대로라 뭘 누를지는 안 잃는다
      const f = card.classList.toggle("folded"); card.querySelector("[data-fold]").textContent = f ? "▸" : "▾";
      const t = $(".tour-spot"); t && place(card, t);
    });
    card.querySelector("[data-skip]").addEventListener("click", () => window.padoTourStop());
    const nextBtn = card.querySelector("[data-next]");
    nextBtn && nextBtn.addEventListener("click", () => { if (st.advance === "done") { window.padoTourStop(); finishTour(); } else { tourSave({ step: i + 1 }); renderTour(); } });
    if (target) {
      target.classList.add("tour-spot");
      spotlight(target);
      const clickEl = st.clickTarget ? ($$(st.clickTarget).find(visible) || null) : target;
      if (st.advance === "click" && clickEl) {
        clickEl.classList.add("tour-spot");
        clickEl.addEventListener("click", () => tourSave({ step: i + 1 }), { once: true });
      }
      place(card, target);
      target.scrollIntoView({ behavior: RM ? "auto" : "smooth", block: "center" });
      setTimeout(() => { place(card, target); spotlight(target); }, RM ? 0 : 500);
      setTimeout(() => spotlight(target), RM ? 0 : 900);
    } else {
      card.classList.add("floating");
      const hole = $(".tour-hole"); hole && hole.classList.remove("on");
    }
    updateWelcome(i);
  }
  let holeTimer = null;
  function spotlight(target, follow) {
    let hole = $(".tour-hole");
    if (!hole) { hole = document.createElement("div"); hole.className = "tour-hole"; document.body.appendChild(hole); }
    const r = target.getBoundingClientRect(), pad = 8;
    hole.style.transition = follow ? "none" : "";   // 스크롤을 따라갈 땐 전환 없이 — 전환이 있으면 구멍이 뒤늦게 따라온다
    hole.style.top = (r.top - pad) + "px"; hole.style.left = (r.left - pad) + "px";
    hole.style.width = (r.width + pad * 2) + "px"; hole.style.height = (r.height + pad * 2) + "px";
    if (follow) return;                              // 따라가기만 — 켜진 시간(1.1초)은 늘리지 않는다
    hole.classList.add("on");
    clearTimeout(holeTimer);
    holeTimer = setTimeout(() => hole.classList.remove("on"), 1100);   // 잠깐만 어둡게 — 계속 두면 다른 데를 안 둘러본다
  }
  function place(card, target) {
    const r = target.getBoundingClientRect();
    const w = card.offsetWidth, h = card.offsetHeight;
    let top = scrollY + r.bottom + 12, left = scrollX + r.left;
    const wantAbove = card.dataset.place === "above" && r.top - 12 - h > 0;
    if (wantAbove || (r.bottom + 12 + h > innerHeight && r.top - 12 - h > 0)) { top = scrollY + r.top - 12 - h; card.classList.add("above"); } else card.classList.remove("above");
    left = Math.max(8, Math.min(left, scrollX + innerWidth - w - 8));
    card.style.top = top + "px"; card.style.left = left + "px";
  }
  function finishTour() {
    const d = document.createElement("div");
    d.className = "tour-mark floating done";
    d.innerHTML = '<div class="tt">🌊 체험 끝</div><div class="tx">이제 자유롭게 둘러보세요. 다른 인물도 보고(느린 기록은 위치태그 하나가 20만 → 5명), 고친 표현을 골라 저장해 보고, 비공개도 눌러 보세요. 파도풀은 권하기만 하고, 누르는 건 Veilo 예요.</div><div class="bt"><button type="button" class="go" data-x>닫기</button></div>';
    document.body.appendChild(d);
    d.querySelector("[data-x]").addEventListener("click", () => d.remove());
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

  function boot() {
    // 새로고침은 «처음부터» — 심사자가 F5 를 누르면 첫 화면 모달로 돌아간다 (글 데이터는 그대로, 투어 상태만 지운다)
    try {
      const nav = performance.getEntriesByType("navigation")[0];
      if (nav && nav.type === "reload" && !sessionStorage.getItem("pado_reload_done")) {
        sessionStorage.setItem("pado_reload_done", "1"); tourSave(null);
        if (location.pathname !== "/" || location.search) { location.replace("/"); return; }
      }
      sessionStorage.removeItem("pado_reload_done");
    } catch (e) {}
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
    renderTour();
    const follow = () => { const c = $(".tour-mark:not(.floating)"), t = $(".tour-spot"); if (c && t) { place(c, t); spotlight(t); } };
    addEventListener("resize", follow);
    addEventListener("scroll", () => { const t = $(".tour-spot"), h = $(".tour-hole"); if (t && h && h.classList.contains("on")) spotlight(t, true); }, { passive: true });
    // 모달: 바깥 클릭·Esc 는 「그냥 둘러볼게요」
    const ov = $("[data-tour-welcome]");
    if (ov) { ov.addEventListener("click", (e) => { if (e.target === ov) window.padoTourStop(); });
      addEventListener("keydown", (e) => { if (e.key === "Escape" && !ov.hidden) window.padoTourStop(); }); }
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(initMore);   // 웹폰트가 늦게 오면 줄 높이가 바뀐다
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
