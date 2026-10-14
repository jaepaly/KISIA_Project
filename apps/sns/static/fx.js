/* Veilo 마이크로 인터랙션 — 클릭 물결 · data-href 카드 이동 · 토글 아이콘 팝 · 제출 스피너.
   보이는 것만 다룬다. 서버 값은 건드리지 않는다. */
(function () {
  "use strict";
  const RM = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ── 클릭 물결 — 버튼·카드·탭 어디든 누른 자리에서 퍼진다 ──
  const RIPPLE = "button,.ut-btn,.ut-nav a,.ut-tabs a,.ut-card[data-href],.rail-card a,a.fx-btn";
  document.addEventListener("pointerdown", (e) => {
    if (RM || e.button !== 0) return;
    const el = e.target.closest(RIPPLE);
    if (!el || el.disabled) return;
    const r = el.getBoundingClientRect();
    const d = Math.max(r.width, r.height) * 2;
    const s = document.createElement("span");
    s.className = "fx-ripple";
    s.style.cssText = `width:${d}px;height:${d}px;left:${e.clientX - r.left - d / 2}px;top:${e.clientY - r.top - d / 2}px`;
    if (getComputedStyle(el).position === "static") el.style.position = "relative";
    el.appendChild(s);
    s.addEventListener("animationend", () => s.remove());
  }, { passive: true });

  // ── data-href 카드 — 안쪽 링크·버튼·폼을 누르면 그쪽이 우선 ──
  document.addEventListener("click", (e) => {
    const card = e.target.closest(".ut-card[data-href]");
    if (!card || e.target.closest("a,button,form,input,select,textarea,label,mark")) return;
    if (e.metaKey || e.ctrlKey) { window.open(card.dataset.href, "_blank"); return; }
    location.href = card.dataset.href;
  });
  function wireCards(root) {
    (root || document).querySelectorAll(".ut-card[data-href]:not([tabindex])").forEach((c) => {
      c.tabIndex = 0;
      c.setAttribute("role", "link");
      c.addEventListener("keydown", (e) => { if (e.key === "Enter") location.href = c.dataset.href; });
    });
  }
  wireCards();

  // ── 피드 무한 스크롤 — .fx-more 가 보이면 다음 장을 받아 이어 붙인다. 실패하면 버튼이 남는다 ──
  function initMore() {
    const more = document.querySelector(".fx-more[data-next]");
    if (!more || more.dataset.busy) return;
    const btn = more.querySelector("button");
    async function load() {
      if (more.dataset.busy) return;
      more.dataset.busy = "1";
      btn.classList.add("fx-busy");
      try {
        const url = more.dataset.next + (more.dataset.next.includes("?") ? "&" : "?") + "partial=1";
        const r = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
        if (!r.ok) throw new Error(r.status);
        const tpl = document.createElement("template");
        tpl.innerHTML = await r.text();
        const frag = tpl.content;
        wireCards(frag);
        const fresh = Array.from(frag.querySelectorAll(".rv"));
        more.replaceWith(frag);
        // veilo.js 의 관찰자는 처음 있던 카드만 본다 — 새 카드는 여기서 한 박자씩 띄워 드러낸다
        requestAnimationFrame(() => fresh.forEach((el, i) => setTimeout(() => el.classList.add("in"), RM ? 0 : i * 45)));
        initMore();
      } catch {
        delete more.dataset.busy;
        btn.classList.remove("fx-busy");
        btn.textContent = "다시 시도";
      }
    }
    btn.addEventListener("click", load);
    if (RM || !("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver((ents) => {
      if (ents.some((x) => x.isIntersecting)) { io.disconnect(); load(); }
    }, { rootMargin: "0px 0px 600px 0px" });
    io.observe(more);
  }
  initMore();

  // ── 공개/비공개 토글 — 누르면 아이콘이 톡 튀고 나서 넘어간다 ──
  document.querySelectorAll('form[action$="/visibility"] button').forEach((b) => {
    b.addEventListener("click", () => { b.classList.remove("fx-pop"); void b.offsetWidth; b.classList.add("fx-pop"); });
  });

  // ── 제출 버튼 — 서버가 답할 때까지 스피너 ──
  document.querySelectorAll("form[method=post]").forEach((f) => {
    f.addEventListener("submit", (e) => {
      // 다른 처리(글쓰기의 「단서가 칠해진 채 올리기」 확인)가 제출을 멈췄으면 스피너를 돌리지 않는다
      setTimeout(() => {
        if (e.defaultPrevented) return;
        const b = f.querySelector("button[type=submit]:not(.ghost)");
        if (b) b.classList.add("fx-busy");
      }, 0);
    });
  });
})();
