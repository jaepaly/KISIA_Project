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
    // 바꿔 쓰기 후보 — span_id 별로 묶는다 (조사까지 맞춘 suggestion · residual_risk none|partial)
    const rewrites = new Map();
    for (const rw of ((d.stage2 || {}).output || {}).rewrites || []) {
      if (!rewrites.has(rw.span_id)) rewrites.set(rw.span_id, []);
      rewrites.get(rw.span_id).push(rw);
    }
    return { spans, k, rewrites };
  }

  // 후보가 없는 유형 — 고치는 방향 한 줄 (분석 앱 action.html MANUAL_TIP 의 짧은 판)
  const TIP = {
    JOB: "업종·가게 이름·하는 일의 세부는 「일하는 곳」 「일」 정도로 넓혀 보세요.",
    LOC_FACILITY: "가게·공원·학교 이름 대신 「근처 공원」 「한 카페」처럼 종류만 남겨 보세요.",
    LOC_ADMIN: "동·구 이름은 시나 도 단위로 넓혀 보세요.",
    AGE: "나이는 「30대」처럼 범위로 바꾸거나 빼 보세요.",
    FAM: "몇째인지, 가족의 나이·학년은 「가족」 「아이」처럼 넓혀 보세요.",
    COMMUTE: "노선·정류장·걸리는 시간은 빼거나 「버스로」 정도만 남겨 보세요.",
    INCOME: "금액·대출이나 수당 종류는 빼거나 「돈」 「비용」처럼 넓혀 보세요.",
    SEX: "호칭(언니·오빠·남편 등)은 성별 단서가 됩니다. 「가족」 「친구」로 바꿔도 뜻이 통하는지 보세요.",
  };
  const cpLen = (s) => Array.from(s || "").length;

  /* 실시간 — 타자가 멈추고 delay 뒤 자동 점검. 서버 보호: 디바운스 · 이전 요청 취소 · minChars 미만 생략 · 같은 글 재요청 안 함.
     padoLive({ textarea, backdrop, chip, warn?, delay=800, minChars=20 }) */
  window.padoLive = function ({ textarea, backdrop, chip, warn, pick, delay = 800, minChars = 20 }) {
    let timer = null, ctrl = null, lastText = null;
    let cur = { spans: [], rewrites: new Map() };   // 마지막 응답 — 형광 누르기가 쓴다
    let undo = null;                                 // { before, after } — 바꾼 직후 되돌리기
    const setChip = (html, cls) => { chip.innerHTML = html; chip.className = "pado-chip" + (cls ? " " + cls : ""); };
    const paint = (text, spans) => { backdrop.innerHTML = markup(text, spans) + "\n"; };
    const sync = () => { backdrop.scrollTop = textarea.scrollTop; backdrop.scrollLeft = textarea.scrollLeft; };
    const hidePick = () => { if (pick) { pick.hidden = true; pick.innerHTML = ""; } };

    async function run() {
      const text = textarea.value;
      if (text === lastText) return;
      if (text.trim().length < minChars) {
        lastText = text; cur = { spans: [], rewrites: new Map() }; paint(text, []); setChip("", ""); if (warn) warn.hidden = true; hidePick(); return;
      }
      if (ctrl) ctrl.abort();
      ctrl = new AbortController();
      setChip("확인 중<span class=\"dots\"></span>", "busy");
      try {
        const { spans, k, rewrites } = await check(text, ctrl.signal);
        if (textarea.value !== text) return;   // 응답 오는 사이 또 바뀜 — 다음 턴이 처리
        lastText = text; cur = { spans, rewrites };
        paint(text, spans);
        if (!spans.length) {
          setChip("읽히는 단서 없음", "ok"); if (warn) warn.hidden = true; hidePick();
        } else {
          const types = [...new Set(spans.map((s) => LABEL[s.type] || s.type))];
          const nCand = spans.filter((s) => rewrites.has(s.span_id)).length;
          setChip(`단서 <b>${spans.length}</b>곳${k ? ` · 약 <b>${Math.round(k).toLocaleString("ko-KR")}</b>명 중 한 명` : ""}<span class="types">${types.map(esc).join(" · ")}</span>`, "hit");
          if (warn) {
            warn.hidden = false;
            warn.innerHTML = `형광으로 칠한 ${spans.length}곳이 나를 드러냅니다. <b>형광 단어를 누르면</b> ${nCand ? `바꿀 후보가 나옵니다(${nCand}곳).` : "고치는 방향을 알려 드립니다."}`;
          }
        }
      } catch (e) {
        if (e.name === "AbortError") return;
        setChip("점검 실패 — 잠시 뒤 다시", "err");
      }
    }

    // ── 형광 누르기 → 후보 패널. textarea 가 위에 있어 클릭은 캐럿 이동이 된다 — 캐럿 위치(코드포인트)로 어느 단서인지 찾는다 ──
    function spanAtCaret() {
      if (!cur.spans.length || textarea.value !== lastText) return null;
      const a = cpLen(textarea.value.slice(0, textarea.selectionStart));
      const b = cpLen(textarea.value.slice(0, textarea.selectionEnd));
      return cur.spans.find((s) => (a >= s.start && a <= s.end) || (a < s.start && b > s.start)) || null;
    }
    function showPick(s) {
      if (!pick) return;
      const cands = cur.rewrites.get(s.span_id) || [];
      const label = LABEL[s.type] || s.type;
      let body;
      if (cands.length) {
        body = `<div class="pado-cands">${cands.map((c, i) => `
          <button type="button" class="pado-cand" data-i="${i}">
            <span class="sug">${esc(c.suggestion)}</span>
            <span class="rr ${c.residual_risk === "none" ? "none" : "part"}">${c.residual_risk === "none" ? "단서가 사라짐" : "약해지지만 남음"}</span>
          </button>`).join("")}</div>`;
      } else {
        body = `<p class="pado-tip">${esc(TIP[s.type] || "이 표현은 빼거나 더 넓은 말로 바꿔 보세요.")}</p>`;
      }
      pick.innerHTML = `
        <div class="pado-pick-h"><span class="t">${esc(label)}</span> <del>${esc(s.text)}</del> <span class="muted">대신</span>
          <button type="button" class="x" aria-label="닫기" data-close>×</button></div>
        ${body}
        <div class="pado-pick-f">
          <button type="button" class="ghost" data-self>직접 고치기</button>
          ${undo ? `<button type="button" class="ghost" data-undo>방금 바꾼 것 되돌리기</button>` : ""}
          <span class="muted">${cands.length ? "안전할수록 원문에서 멀어집니다." : "자동으로 바꿀 말을 정하기 어려운 단서입니다."}</span>
        </div>`;
      pick.hidden = false;
      pick.querySelectorAll(".pado-cand").forEach((b) => b.addEventListener("click", () => apply(s, cands[+b.dataset.i].suggestion)));
      pick.querySelector("[data-close]").addEventListener("click", hidePick);
      pick.querySelector("[data-self]").addEventListener("click", () => selectSpan(s));
      const u = pick.querySelector("[data-undo]"); if (u) u.addEventListener("click", doUndo);
    }
    // 코드포인트 범위 → UTF-16 인덱스로 바꿔 textarea 에 선택
    function utf16Range(s) {
      const arr = Array.from(textarea.value);
      return [arr.slice(0, s.start).join("").length, arr.slice(0, s.end).join("").length];
    }
    function selectSpan(s) {
      const [a, b] = utf16Range(s);
      textarea.focus(); textarea.setSelectionRange(a, b); hidePick();
    }
    function apply(s, suggestion) {
      const before = textarea.value;
      const [a, b] = utf16Range(s);
      textarea.value = before.slice(0, a) + suggestion + before.slice(b);
      undo = { before, after: textarea.value };
      const caret = a + suggestion.length;
      textarea.focus(); textarea.setSelectionRange(caret, caret);
      hidePick();
      textarea.dispatchEvent(new Event("input", { bubbles: true }));   // 형광 지우고 다시 점검
    }
    function doUndo() {
      if (!undo || textarea.value !== undo.after) { undo = null; hidePick(); return; }
      textarea.value = undo.before; undo = null; hidePick();
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    }
    function maybePick() {
      const s = spanAtCaret();
      if (s) showPick(s); else hidePick();
    }

    textarea.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, delay); paint(textarea.value, []); sync(); hidePick(); });
    textarea.addEventListener("scroll", sync);
    textarea.addEventListener("click", maybePick);
    textarea.addEventListener("keyup", (e) => { if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(e.key)) maybePick(); });
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
