/* 파도풀 글 단위 점검 위젯 — 글쓰기(new.html)·글 본문(post.html) 공용.
   진단은 분석 앱(PADO_BASE/upload — 기본 /check)이 하고 여기서는 띄우기만 한다.
   padoWidget({ btn, out, getText, userRef? }) — userRef 가 있으면 결과 아래에 계정 전체 진단 링크를 단다. */
(function () {
  "use strict";
  const BASE = window.PADO_BASE || "/check";   // base.html 이 app.py PADO_BASE 를 넣어 준다
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
  // subject unknown — 엔진은 지우지 않고 신뢰도를 절반으로 센다(clues.py). 화면도 지우지 않고 점선 · 옅은 색으로 구분한다 (exp32 사후 분석)
  const maybe = (s) => s.subject === "unknown";
  const MAYBE_HINT = (s) => String(s.type).startsWith("LOC") ? " · 여행지나 영상 속 장소처럼 내 장소가 아닐 수 있어요" : " · 내 정보가 아닐 수 있어요";
  const maybeNote = (spans) => { const n = spans.filter(maybe).length; return n ? ` 점선 ${n}곳은 내 정보인지 불분명해 같은 조건의 사람 수 계산에 낮게 반영합니다.` : ""; };
  const markStyle = (s, alpha) => maybe(s)
    ? `background:${COLOR[s.type] || "#F9E0B8"}${alpha ? "59" : "73"};outline:1px dashed rgba(62,58,54,.4);outline-offset:-1px;`
    : `background:${COLOR[s.type] || "#F9E0B8"}${alpha ? "B3" : ""};`;

  // 스팬 범위 보정 — 엔진이 준 start/end 로 자른 글자가 스팬 text 와 다르면(바꿔 쓰기 뒤 「주간조」가 「조」로 칠해지던 일)
  // 같은 text 가 나오는 자리 중 원래 start 에 가장 가까운 곳으로 옮긴다. 못 찾으면 원래 범위를 그대로 둔다.
  // 엔진 쪽 원인은 따로 본다(콘솔에 남긴다) — 화면은 적어도 엉뚱한 글자를 칠하지 않는다
  function anchor(text, spans) {
    const arr = Array.from(text || "");
    const nfc = (x) => (x || "").normalize("NFC");
    return spans.map((s) => {
      if (!s.text || nfc(arr.slice(s.start, s.end).join("")) === nfc(s.text)) return s;
      const want = Array.from(nfc(s.text)), n = want.length;
      let best = -1;
      for (let i = 0; i + n <= arr.length; i++) {
        if (nfc(arr.slice(i, i + n).join("")) === want.join("") && (best < 0 || Math.abs(i - s.start) < Math.abs(best - s.start))) best = i;
      }
      console.warn("[pado] 스팬 범위가 text 와 다름", { span_id: s.span_id, start: s.start, end: s.end, text: s.text, got: arr.slice(s.start, s.end).join(""), moved_to: best });
      return best < 0 ? s : { ...s, start: best, end: best + n };
    });
  }
  window.padoAnchor = anchor;

  // 본문 텍스트에 스팬 형광을 입힌 HTML. 줄바꿈은 그대로 둔다 (overlay 가 pre-wrap).
  // 형광판이 textarea 위에 있을 때(실시간)는 반투명(alpha)으로 — 실제 글자가 비쳐야 한다
  function markup(text, spans, { alpha = false, hint = "" } = {}) {
    let out = "", last = 0;
    for (const s of [...spans].sort((a, b) => a.start - b.start)) {
      if (s.start < last) continue;
      out += esc(cp(text, last, s.start))
        + `<mark data-t="${esc(s.type)}" data-id="${esc(s.span_id || "")}"${maybe(s) ? ' data-maybe="1"' : ""} style="${markStyle(s, alpha)}" title="${esc(LABEL[s.type] || s.type)}${maybe(s) ? MAYBE_HINT(s) : ""}${hint}">`
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
    const spans = anchor(text, (((d.spans || {})[post.post_id] || {}).spans || []).filter((s) => s.subject !== "other"));
    const spec = ((d.specificity || {}).output || {});
    const k = spec.k;
    // 바꿔 쓰기 후보 — span_id 별로 묶는다 (조사까지 맞춘 suggestion · residual_risk none|partial)
    const rewrites = new Map();
    for (const rw of ((d.stage2 || {}).output || {}).rewrites || []) {
      if (!rewrites.has(rw.span_id)) rewrites.set(rw.span_id, []);
      rewrites.get(rw.span_id).push(rw);
    }
    return { spans, k, rewrites, steps: spec.steps || [], risk: spec.risk, raw: d };
  }

  // 깔때기 조건의 «…» 가 행정코드(3171025000)뿐이면 글에서 찾은 지명으로 바꾼다 — 코드를 화면에 내지 않는다.
  // 파도풀 화면 common.js placeName() 과 같은 규칙: 조건의 value → 그 조건을 낸 글의 본인 지역 단서 → 위치 태그 → 「사는 동네」
  window.padoPlaceName = function (data, text) {
    if (!/^\d{5,10}$/.test(String(text))) return text;
    const conds = (((data || {}).specificity || {}).input || {}).conditions || [];
    const posts = Object.fromEntries(((data || {}).posts || []).map((p) => [p.post_id, p]));
    for (const c of conds) {
      if (String(c.geo_code) !== String(text)) continue;
      if (c.value && !/^\d+$/.test(String(c.value))) return c.value;
      for (const pid of c.source_post_ids || []) {
        const s = ((((data.spans || {})[pid]) || {}).spans || []).find((x) => x.subject !== "other" && String(x.type).startsWith("LOC"));
        if (s) return s.text;
        const p = posts[pid], geo = p && ((p.activity_meta || {}).geo_tag || p.geo_tag);   // 위치 태그는 export 계약대로 activity_meta 안
        if (geo) return geo;
      }
    }
    return "사는 동네";
  };
  window.padoCheck = check;
  // export 형식 그대로(.json) — 위치태그·프로필·사진 캡션까지 /scan 과 같은 파이프라인을 탄다. 계정 글 + 초안 합산용
  window.padoCheckExport = async function (exportObj, signal) {
    const fd = new FormData();
    fd.append("file", new File([JSON.stringify(exportObj)], "draft.json", { type: "application/json" }));
    const r = await fetch(`${BASE}/upload`, { method: "POST", body: fd, signal });
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    const spec = ((d.specificity || {}).output || {});
    return { k: spec.k, steps: spec.steps || [], risk: spec.risk, raw: d };
  };

  // 후보가 없는 유형 — 고치는 방향 한 줄 (분석 앱 action.html MANUAL_TIP 의 짧은 판)
  const TIP = {
    JOB: "업종이나 가게, 회사 이름 대신 「일하는 곳」처럼 써 보세요. 업무 이름과 도구도 구체적으로 적었는지 확인하세요.",
    LOC_FACILITY: "가게나 공원, 학교 이름 대신 「근처 공원」이나 「한 카페」처럼 종류만 써 보세요.",
    LOC_ADMIN: "동이나 구 이름 대신 시나 도 이름을 써 보세요.",
    AGE: "나이는 「30대」처럼 넓게 쓰거나 빼 보세요.",
    FAM: "몇째인지, 나이나 학년을 적는 대신 「가족」이나 「아이」로 써도 뜻이 통하는지 보세요.",
    COMMUTE: "노선이나 정류장 이름, 걸리는 시간은 빼고 「버스로」 정도만 써 보세요.",
    INCOME: "금액이나 대출, 수당의 종류는 빼거나 「돈」, 「비용」처럼 넓게 써 보세요.",
    SEX: "「언니」, 「오빠」, 「남편」 같은 호칭은 성별 단서가 될 수 있습니다. 「가족」이나 「친구」로 바꿔도 뜻이 통하는지 보세요.",
  };
  const cpLen = (s) => Array.from(s || "").length;

  /* 실시간 — 타자가 멈추고 delay 뒤 자동 점검. 서버 보호: 디바운스 · 이전 요청 취소 · minChars 미만 생략 · 같은 글 재요청 안 함.
     padoLive({ textarea, backdrop, chip, warn?, delay=800, minChars=20 }) */
  window.padoLive = function ({ textarea, backdrop, chip, warn, pick, onResult, delay = 800, minChars = 20 }) {
    let timer = null, ctrl = null, lastText = null;
    let cur = { spans: [], rewrites: new Map() };   // 마지막 응답 — 형광 누르기가 쓴다
    let undo = null;                                 // { before, after } — 바꾼 직후 되돌리기
    const setChip = (html, cls) => { chip.innerHTML = html; chip.className = "pado-chip" + (cls ? " " + cls : ""); };
    const paint = (text, spans) => {
      backdrop.innerHTML = markup(text, spans, { alpha: false, hint: spans.length ? " · 누르면 바꿔 쓸 표현 보기" : "" }) + "\n";   // 불투명 + CSS multiply
      // 후보가 있는 형광은 점선 밑줄로 「누를 수 있다」를 미리 보여 준다
      backdrop.querySelectorAll("mark[data-id]").forEach((m) => { if (cur.rewrites.has(m.dataset.id)) m.classList.add("has-cand"); });
    };
    const sync = () => { backdrop.scrollTop = textarea.scrollTop; backdrop.scrollLeft = textarea.scrollLeft; };
    const hidePick = () => {
      if (pick) { pick.hidden = true; pick.innerHTML = ""; }
      backdrop.querySelectorAll("mark.on").forEach((m) => m.classList.remove("on"));
    };

    async function run() {
      const text = textarea.value;
      if (text === lastText) return;
      if (text.trim().length < minChars) {
        lastText = text; cur = { spans: [], rewrites: new Map() }; paint(text, []); setChip("", ""); if (warn) warn.hidden = true; hidePick();
        if (onResult) onResult(null);
        return;
      }
      if (ctrl) ctrl.abort();
      ctrl = new AbortController();
      setChip("확인 중<span class=\"dots\"></span>", "busy");
      try {
        const { spans, k, rewrites, steps, risk } = await check(text, ctrl.signal);
        if (textarea.value !== text) return;   // 응답 오는 사이 또 바뀜 — 다음 턴이 처리
        lastText = text; cur = { spans, rewrites };
        paint(text, spans);   // cur 를 먼저 — paint 가 후보 유무를 본다
        if (onResult) onResult({ spans, k, steps, risk, text });
        if (!spans.length) {
          setChip("개인정보 단서를 찾지 못함", "ok"); if (warn) warn.hidden = true; hidePick();
        } else {
          const types = [...new Set(spans.map((s) => LABEL[s.type] || s.type))];
          const nCand = spans.filter((s) => rewrites.has(s.span_id)).length;
          setChip(`개인정보 단서 <b>${spans.length}</b>곳${k ? ` · 같은 조건의 사람 약 <b>${Math.round(k).toLocaleString("ko-KR")}</b>명` : ""}<span class="types">${types.map(esc).join(" · ")}</span>`, "hit");
          if (warn) {
            warn.hidden = false;
            warn.innerHTML = `색칠한 ${spans.length}곳은 개인정보 단서가 될 수 있습니다. <b>누르면</b> ${nCand ? `바꿔 쓸 표현이 나옵니다(${nCand}곳).` : "직접 고치는 방법을 볼 수 있습니다."} 같은 조건의 사람 수가 적을수록 글쓴이를 좁히기 쉽습니다.${maybeNote(spans)}`;
          }
        }
      } catch (e) {
        if (e.name === "AbortError") return;
        setChip("점검하지 못했습니다. 잠시 뒤 다시 시도해 주세요.", "err");
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
            <span class="rr ${c.residual_risk === "none" ? "none" : "part"}">${c.residual_risk === "none" ? "이 표현의 단서가 사라짐" : "약해지지만 남음"}</span>
          </button>`).join("")}</div>`;
      } else {
        body = `<p class="pado-tip">${esc(TIP[s.type] || "이 표현은 빼거나 더 넓은 말로 바꿔 보세요.")}</p>`;
      }
      pick.innerHTML = `
        <div class="pado-pick-h"><span class="t">${esc(label)}</span> <del>${esc(s.text)}</del> <span class="muted">대신</span>
          <button type="button" class="x" aria-label="닫기" data-close>×</button></div>
        ${maybe(s) ? `<p class="pado-tip" style="margin-top:0;">${esc(MAYBE_HINT(s).replace(/^ · /, ""))}. 내 정보가 아니면 그대로 두셔도 됩니다.</p>` : ""}
        ${body}
        <div class="pado-pick-f">
          <button type="button" class="ghost" data-self>직접 고치기</button>
          ${undo ? `<button type="button" class="ghost" data-undo>방금 바꾼 것 되돌리기</button>` : ""}
          <span class="muted">${cands.length ? "더 넓은 표현으로 바꾸면 원래 뜻도 달라질 수 있습니다." : "바꿔 쓸 표현을 추천하기 어렵습니다."}</span>
        </div>`;
      pick.hidden = false;
      backdrop.querySelectorAll("mark.on").forEach((m) => m.classList.remove("on"));
      const mk = backdrop.querySelector(`mark[data-id="${CSS.escape(s.span_id || "")}"]`); if (mk) mk.classList.add("on");
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
    // 형광판이 위에 있다 — 형광(mark)만 마우스를 받고 나머지는 textarea 로 통과한다. 형광을 누르면 바로 패널 + 캐럿을 그 자리로
    backdrop.addEventListener("click", (e) => {
      const m = e.target.closest("mark[data-id]"); if (!m) return;
      const s = cur.spans.find((x) => x.span_id === m.dataset.id); if (!s) return;
      const [a] = utf16Range(s);
      textarea.focus({ preventScroll: true }); textarea.setSelectionRange(a, a);
      showPick(s);
    });
    if (textarea.value.trim()) run();
    return { run };
  };

  window.padoWidget = function ({ btn, out, getText, userRef }) {
    btn.addEventListener("click", async () => {
      const text = (getText() || "").trim();
      if (!text) { out.innerHTML = muted("본문을 먼저 써 주세요."); return; }
      btn.disabled = true;
      out.innerHTML = '<p style="color:var(--ut-ink3);margin:0;">점검 중<span data-dots></span></p>';
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
        const spans = anchor(body, (((d.spans || {})[post.post_id] || {}).spans || []).filter((s) => s.subject !== "other"));
        const k = ((d.specificity || {}).output || {}).k;

        if (!spans.length) {
          out.innerHTML = muted("이 글에서는 개인정보 단서를 찾지 못했습니다. 다른 공개 글과 함께 보면 결과가 달라질 수 있습니다.");
          return;
        }
        // 오프셋은 코드포인트 단위 — cp() 로 자른다 (UTF-16 slice 는 이모지 뒤에서 어긋난다)
        let marked = "", last = 0;
        for (const s of [...spans].sort((a, b) => a.start - b.start)) {
          if (s.start < last) continue;
          marked += esc(cp(body, last, s.start))
            + `<mark style="${markStyle(s, false)}border-radius:3px;padding:1px 2px;" title="${esc(LABEL[s.type] || s.type)}${maybe(s) ? MAYBE_HINT(s) : ""}">`
            + esc(cp(body, s.start, s.end)) + (maybe(s) ? `<span style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);">(내 정보인지 불분명)</span>` : "") + "</mark>";
          last = s.end;
        }
        marked += esc(cp(body, last));
        const types = [...new Set(spans.map((s) => LABEL[s.type] || s.type))];
        out.innerHTML =
          `<p style="margin:0 0 8px;">개인정보 단서 <b style="font-size:20px;">${spans.length}</b>곳`
          + (k ? ` · 같은 조건의 사람 약 <b>${Math.round(k).toLocaleString("ko-KR")}</b>명` : "")   // 실시간 칩(118행)과 같게 — 사람 수에 소수점을 쓰지 않는다
          + `</p>`
          + `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">`
          + types.map((t) => `<span style="font-size:11px;font-weight:600;color:var(--ut-ink2);background:var(--ut-panel);border:1px solid var(--ut-line);border-radius:99px;padding:2px 9px;">${esc(t)}</span>`).join("")
          + `</div>`
          + `<div style="white-space:pre-wrap;background:var(--ut-bg);border-radius:10px;padding:12px 14px;line-height:1.85;font-size:13px;">${marked}</div>`
          + (spans.some(maybe) ? `<p style="margin:6px 0 0;font-size:12px;color:var(--ut-ink3);">${maybeNote(spans).trim()}</p>` : "")
          + `<div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:13px;">`
          + (userRef ? `<a class="fx-link" href="${BASE}/static/scan.html?u=${encodeURIComponent(userRef)}" style="color:var(--ut-earth-ink);">계정 전체 점검 →</a>` : "")
          + `<a class="fx-link" href="${BASE}/static/scan.html" style="color:var(--ut-earth-ink);">다른 계정 점검 →</a>`
          + `</div>`;
      } catch (e) {
        // 서버의 한국어 사유(429 「지금 다른 점검이 진행 중입니다…」 · 너무 긴 글 등)가 있으면 그대로
        let detail = "";
        try { detail = JSON.parse(e.message).detail; } catch { /* 네트워크 오류 등 */ }
        out.innerHTML = muted(typeof detail === "string" && detail ? `점검하지 못했습니다. ${esc(detail)}` : "점검하지 못했습니다. 잠시 뒤 다시 시도해 주세요.");
      } finally {
        clearInterval(dots);
        btn.disabled = false;
      }
    });
  };
})();
