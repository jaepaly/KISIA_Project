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
  document.querySelectorAll(".ut-card[data-href]").forEach((c) => {
    c.tabIndex = 0;
    c.setAttribute("role", "link");
    c.addEventListener("keydown", (e) => { if (e.key === "Enter") location.href = c.dataset.href; });
  });

  // ── 공개/비공개 토글 — 누르면 아이콘이 톡 튀고 나서 넘어간다 ──
  document.querySelectorAll('form[action$="/visibility"] button').forEach((b) => {
    b.addEventListener("click", () => { b.classList.remove("fx-pop"); void b.offsetWidth; b.classList.add("fx-pop"); });
  });

  // ── 제출 버튼 — 서버가 답할 때까지 스피너 ──
  document.querySelectorAll("form[method=post]").forEach((f) => {
    f.addEventListener("submit", () => {
      const b = f.querySelector("button[type=submit]:not(.ghost)");
      if (b) b.classList.add("fx-busy");
    });
  });
})();
