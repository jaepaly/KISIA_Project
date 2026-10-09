/* 파도풀 글 단위 점검 위젯 — 글쓰기(new.html)·글 본문(post.html) 공용.
   진단은 분석 앱(/check/upload)이 하고 여기서는 띄우기만 한다.
   padoWidget({ btn, out, getText, userRef? }) — userRef 가 있으면 결과 아래에 계정 전체 진단 링크를 단다. */
(function () {
  "use strict";
  const BASE = "/check";
  const COLOR = {
    AGE: "#CFE6F7", SEX: "#F3D9E6", JOB: "#D6ECD9", FAM: "#E5D9F2",
    COMMUTE: "#E1EEEC", INCOME: "#FDE8C9", LOC_ADMIN: "#F9E0B8", LOC_FACILITY: "#EDE8F7"
  };
  const LABEL = {
    AGE: "나이", SEX: "성별", JOB: "직업", FAM: "가족", COMMUTE: "통근",
    INCOME: "소득", LOC_ADMIN: "거주지", LOC_FACILITY: "자주 가는 곳"
  };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const muted = (t) => `<p style="color:var(--ut-ink3);margin:0;">${t}</p>`;
  // 스팬 오프셋은 코드포인트 단위 — 이모지 뒤에서 UTF-16 slice 가 어긋난다
  const cp = (text, a, b) => Array.from(text || "").slice(a, b).join("");

  // 본문 텍스트에 스팬 형광을 입힌 HTML. 줄바꿈은 그대로 둔다 (overlay 가 pre-wrap)
  function markup(text, spans) {
    let out = "", last = 0;
    for (const s of [...spans].sort((a, b) => a.start - b.start)) {
      if (s.start < last) continue;
      out += esc(cp(text, last, s.start))
        + `<mark data-t="${esc(s.type)}" style="background:${COLOR[s.type] || "#F9E0B8"};" title="${esc(LABEL[s.type] || s.type)}">`
        + esc(cp(text, s.start, s.end)) + "</mark>";
      last = s.end;
    }
    return out + esc(cp(text, last));
  }

  async function check(text, signal) {
    const fd = new FormData();
    fd.append("file", new File([text.replace(/\n/g, " ")], "draft.txt", { type: "text/plain" }));
    const r = await fetch(`${BASE}/upload`, { method: "POST", body: fd, signal });
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    const post = (d.posts || [])[0] || {};
    const spans = (((d.spans || {})[post.post_id] || {}).spans || []).filter((s) => s.subject !== "other");
    const k = ((d.specificity || {}).output || {}).k;
    return { spans, k };
  }

  /* 실시간 — 타자가 멈추고 delay 뒤 자동 점검. 서버 보호: 디바운스 · 이전 요청 취소 · minChars 미만 생략 · 같은 글 재요청 안 함.
     padoLive({ textarea, backdrop, chip, warn?, delay=800, minChars=20 }) */
  window.padoLive = function ({ textarea, backdrop, chip, warn, delay = 800, minChars = 20 }) {
    let timer = null, ctrl = null, lastText = null;
    const setChip = (html, cls) => { chip.innerHTML = html; chip.className = "pado-chip" + (cls ? " " + cls : ""); };
    const paint = (text, spans) => { backdrop.innerHTML = markup(text, spans) + "\n"; };
    const sync = () => { backdrop.scrollTop = textarea.scrollTop; backdrop.scrollLeft = textarea.scrollLeft; };

    async function run() {
      const text = textarea.value;
      if (text === lastText) return;
      if (text.trim().length < minChars) {
        lastText = text; paint(text, []); setChip("", ""); if (warn) warn.hidden = true; return;
      }
      if (ctrl) ctrl.abort();
      ctrl = new AbortController();
      setChip("확인 중<span class=\"dots\"></span>", "busy");
      try {
        const { spans, k } = await check(text, ctrl.signal);
        if (textarea.value !== text) return;   // 응답 오는 사이 또 바뀜 — 다음 턴이 처리
        lastText = text;
        paint(text, spans);
        if (!spans.length) {
          setChip("읽히는 단서 없음", "ok"); if (warn) warn.hidden = true;
        } else {
          const types = [...new Set(spans.map((s) => LABEL[s.type] || s.type))];
          setChip(`단서 <b>${spans.length}</b>곳${k ? ` · 약 <b>${Number(k).toLocaleString("ko-KR")}</b>명 중 한 명` : ""}<span class="types">${types.map(esc).join(" · ")}</span>`, "hit");
          if (warn) { warn.hidden = false; warn.innerHTML = `형광으로 칠한 ${spans.length}곳이 나를 드러냅니다. 그대로 올려도 되지만, 한 번 더 보세요.`; }
        }
      } catch (e) {
        if (e.name === "AbortError") return;
        setChip("점검 실패 — 잠시 뒤 다시", "err");
      }
    }
    textarea.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, delay); paint(textarea.value, []); sync(); });
    textarea.addEventListener("scroll", sync);
    if (textarea.value.trim()) run();
    return { run };
  };

  window.padoWidget = function ({ btn, out, getText, userRef }) {
    btn.addEventListener("click", async () => {
      const text = (getText() || "").trim();
      if (!text) { out.innerHTML = muted("본문을 먼저 써 주세요."); return; }
      btn.disabled = true;
      out.innerHTML = '<p style="color:var(--ut-ink3);margin:0;">읽는 중<span data-dots></span></p>';
      let di = 0;
      const dots = setInterval(() => {
        const el = out.querySelector("[data-dots]");
        if (el) el.textContent = [".", "..", "..."][di++ % 3];
      }, 420);
      try {
        const fd = new FormData();
        fd.append("file", new File([text.replace(/\n/g, " ")], "draft.txt", { type: "text/plain" }));
        const r = await fetch(`${BASE}/upload`, { method: "POST", body: fd });
        if (!r.ok) throw new Error(await r.text());
        const d = await r.json();
        const post = (d.posts || [])[0] || {};
        const body = post.body || "";
        const spans = (((d.spans || {})[post.post_id] || {}).spans || []).filter((s) => s.subject !== "other");
        const k = ((d.specificity || {}).output || {}).k;

        if (!spans.length) {
          out.innerHTML = muted("읽히는 단서가 없습니다. 이대로 둬도 괜찮아 보입니다.");
          return;
        }
        let marked = "", last = 0;
        for (const s of [...spans].sort((a, b) => a.start - b.start)) {
          if (s.start < last) continue;
          marked += esc(body.slice(last, s.start))
            + `<mark style="background:${COLOR[s.type] || "#F9E0B8"};border-radius:3px;padding:1px 2px;" title="${LABEL[s.type] || s.type}">`
            + esc(body.slice(s.start, s.end)) + "</mark>";
          last = s.end;
        }
        marked += esc(body.slice(last));
        const types = [...new Set(spans.map((s) => LABEL[s.type] || s.type))];
        out.innerHTML =
          `<p style="margin:0 0 8px;"><b style="font-size:20px;">${spans.length}</b>곳에서 단서가 읽힙니다`
          + (k ? ` · 약 <b>${Number(k).toLocaleString("ko-KR")}</b>명 중 한 명` : "")
          + `</p>`
          + `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">`
          + types.map((t) => `<span style="font-size:11px;font-weight:600;color:var(--ut-ink2);background:var(--ut-panel);border:1px solid var(--ut-line);border-radius:99px;padding:2px 9px;">${esc(t)}</span>`).join("")
          + `</div>`
          + `<div style="white-space:pre-wrap;background:var(--ut-bg);border-radius:10px;padding:12px 14px;line-height:1.85;font-size:13px;">${marked}</div>`
          + `<div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:13px;">`
          + (userRef ? `<a class="fx-link" href="${BASE}/static/scan.html?u=${encodeURIComponent(userRef)}" style="color:var(--ut-earth-ink);">이 계정 전체 진단 →</a>` : "")
          + `<a class="fx-link" href="${BASE}/static/scan.html" style="color:var(--ut-earth-ink);">파도풀 열기 →</a>`
          + `</div>`;
      } catch {
        out.innerHTML = muted("점검에 실패했습니다. 잠시 뒤 다시 눌러 주세요.");
      } finally {
        clearInterval(dots);
        btn.disabled = false;
      }
    });
  };
})();
