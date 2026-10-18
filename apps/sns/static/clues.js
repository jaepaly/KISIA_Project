/* 위험 배지 「📍 단서 N곳」 채우기 — 내 계정 공개 글 중 아직 안 센 글(_clue.html 의 [data-clue-need]).
   서버 부담이 핵심 제약이다(글 하나 점검 ≈ 2초 · 운영 서버 하나):
   - 한 번에 하나씩(앞 요청이 끝나야 다음) · 화면 하나에 최대 CLUE_PER_PAGE(5)편
   - 센 값은 Veilo 세션 DB 에 저장(/api/clues/<post_id>) → 다음부터는 점검 없이 배지만
   - 실패하면 조용히 넘어가고, 이 탭에서는 그 글을 다시 부르지 않는다(sessionStorage veilo.clue.fail)
   점검은 글쓰기 실시간 경고와 같은 API(pado.js padoCheck → PADO_BASE/upload)다. */
(function () {
  "use strict";
  const slots = Array.from(document.querySelectorAll("[data-clue-need]"));
  if (!slots.length) return;
  const LIMIT = window.CLUE_PER_PAGE || 5;
  const FAIL_KEY = "veilo.clue.fail";
  let failed = {};
  try { failed = JSON.parse(sessionStorage.getItem(FAIL_KEY) || "{}") || {}; } catch (e) {}
  const markFail = (id) => { failed[id] = 1; try { sessionStorage.setItem(FAIL_KEY, JSON.stringify(failed)); } catch (e) {} };
  const todo = slots.filter((s) => !failed[s.dataset.clueNeed]).slice(0, LIMIT);
  if (!todo.length) return;

  function badge(id, n) {
    const a = document.createElement("a");
    a.className = "clue-badge";
    a.href = "/posts/" + encodeURIComponent(id) + "#pado";
    a.title = "이 글에서 찾은 개인정보 단서 " + n + "곳 — 누르면 이 글 점검";
    a.textContent = "📍 단서 " + n + "곳";
    return a;
  }

  function needPado() {
    if (window.padoCheck) return Promise.resolve();
    return new Promise((ok, no) => {
      const s = document.createElement("script");
      s.src = "/static/pado.js?v=381";
      s.onload = ok; s.onerror = no;
      document.head.appendChild(s);
    });
  }

  async function run() {
    try { await needPado(); } catch (e) { return; }
    for (const slot of todo) {
      const id = slot.dataset.clueNeed;
      try {
        const r = await window.padoCheck(slot.dataset.clueBody || "");
        const n = r.spans.length;
        const save = await fetch("/api/clues/" + encodeURIComponent(id), {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ n: n })
        });
        if (!save.ok) throw new Error(save.status);
        if (n > 0) slot.replaceWith(badge(id, n)); else slot.remove();   // 0곳은 배지 없음 — 안전 단정처럼 읽히지 않게
      } catch (e) {
        markFail(id);
      }
    }
  }
  // 화면 그리기가 먼저 — 브라우저가 한가할 때 시작
  (window.requestIdleCallback || ((f) => setTimeout(f, 300)))(run);
})();
