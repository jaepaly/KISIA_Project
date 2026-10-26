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
    // 형광 · 칩 이름은 파도풀 화면과 같게 — 「지역명」 · 「장소명」 (#385 E2). 7개 항목 이름 「거주지」(레일 축)는 따로 둔다
    INCOME: "소득", LOC_ADMIN: "지역명", LOC_FACILITY: "장소명",
    REL_HOME: "집 근처", REL_WORK: "직장 근처"   // 빠져 있어 툴팁 · 칩에 「REL_HOME」 코드가 보이던 것 (분석기 common.js 와 같은 이름)
  };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const muted = (t) => `<p style="color:var(--ut-ink3);margin:0;">${t}</p>`;
  // 스팬 오프셋은 코드포인트 단위 — 이모지 뒤에서 UTF-16 slice 가 어긋난다
  const cp = (text, a, b) => Array.from(text || "").slice(a, b).join("");
  // subject unknown — 엔진은 지우지 않고 신뢰도를 절반으로 센다(clues.py). 화면도 지우지 않고 옅은 형광 + 점선 밑줄로 구분한다 (exp32 사후 분석 · 모양은 veilo.css mark[data-maybe])
  const maybe = (s) => s.subject === "unknown";
  const MAYBE_HINT = (s) => String(s.type).startsWith("LOC") ? " · 여행지나 영상 속 장소처럼 내 장소가 아닐 수 있어요"
    : s.type === "AGE" ? " · 지난 시절의 나이처럼 지금 나이가 아닐 수 있어요" : " · 내 정보가 아닐 수 있어요";   // AGE unknown = 과거 나이 (exp36)
  const maybeNote = (spans) => { const n = spans.filter(maybe).length; return n ? ` 점선 밑줄 ${n}곳은 내 정보인지 불분명해 같은 조건의 사람 수 계산에 낮게 반영합니다.` : ""; };
  const markStyle = (s, alpha) => maybe(s)
    ? `background:${COLOR[s.type] || "#F9E0B8"}${alpha ? "59" : "73"};`
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

  // ── 점검 대기표 (#385 E9 · E10) — 파도풀 화면(분석 앱 common.js scanTicket · watchQueue)과 같은 방식.
  //    점검 POST 에 X-Scan-Ticket 을 싣고, 기다리는 동안 /api/scan-queue 로 1초마다 차례를 묻는다(서버는 점검을 하나씩만 돌린다)
  function ticket() {
    const a = new Uint8Array(12);
    (window.crypto || {}).getRandomValues ? crypto.getRandomValues(a) : a.forEach((_, i) => { a[i] = Math.random() * 256; });
    return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
  }
  // 앞 물음이 끝난 뒤 다음을 예약한다(응답 순서가 뒤집히지 않게). 돌려준 함수를 부르면 멈춘다 — 끝난 점검의 늦은 응답은 버린다
  function watchQueue(t, onAhead) {
    let stopped = false, timer = null, ac = null;
    const ask = async () => {
      ac = new AbortController();
      try {
        const r = await fetch(`${BASE}/api/scan-queue?ticket=${encodeURIComponent(t)}`, { signal: ac.signal });
        if (r.ok) { const q = await r.json(); if (!stopped) onAhead(q.waiting ? Math.max(1, q.ahead) : 0); }
      } catch { /* 못 물으면 그대로 · 취소도 여기로 */ }
      if (!stopped) timer = setTimeout(ask, 1000);
    };
    timer = setTimeout(ask, 400);   // 바로 자리를 잡은 점검은 줄에 없다 — 첫 물음은 조금 뒤에
    return () => { stopped = true; clearTimeout(timer); if (ac) ac.abort(); };
  }
  // 점검 요청 하나 — path 는 BASE 뒤(/upload · /scan/<계정>). onAhead 를 주면 앞사람 수를 알려 준다.
  // 실패하면 Error(본문) + status — 429 를 따로 보인다 (#385 E12)
  async function send(path, fd, signal, onAhead) {
    const t = ticket();
    const stop = onAhead ? watchQueue(t, onAhead) : null;
    try {
      const r = await fetch(`${BASE}${path}`, { method: "POST", body: fd || undefined, signal, headers: { "X-Scan-Ticket": t } });
      if (!r.ok) { const e = new Error(await r.text()); e.status = r.status; throw e; }
      return await r.json();
    } finally { if (stop) stop(); }
  }
  window.padoPost = send;
  // 서버의 한국어 사유(JSON detail) — 없으면(nginx 429 · 네트워크 오류) 빈 문자열
  const detailOf = (e) => { try { const d = JSON.parse(e.message).detail; return typeof d === "string" ? d : ""; } catch { return ""; } };
  // 429 — 고정 문구만 쓴다. 서버 사유(「잠시 뒤 다시 시도해 주세요」)를 붙이면 「30초 뒤 확인」과 겹친다 (#385 E12).
  // 30초 뒤 한 번 자동으로 다시 확인한다. 429 가 아닌 오류는 서버 사유를 먼저 쓴다
  const BUSY_MSG = "요청이 많아 잠깐 쉬고 있어요 — 30초 뒤 다시 확인할게요";
  const RETRY_MS = 30000;

  // 진행 표시 — 「내 글 점검」(분석 앱 common.js progressStart)과 같은 단계 이름 + 흐른 시간 (#385 E9).
  // est(초)를 주면 그 비율로 단계를 넘기고 「3초 / 약 20초」. 앞에 다른 점검이 있으면 paint({ ahead }) — 차례가 오면 0초부터 다시
  const STAGES = ["글 읽는 중", "개인정보 단서 찾는 중", "같은 조건의 사람 수 계산 중", "위험 줄일 방법 확인 중", "거의 다 됐습니다"];
  const fmtSec = (s) => { s = Math.max(1, Math.round(s)); return s < 60 ? `${s}초` : `${Math.floor(s / 60)}분 ${s % 60 ? (s % 60) + "초" : ""}`.trim(); };
  window.padoFmtSec = fmtSec;
  function progress(paint, est) {
    const has = typeof est === "number" && est > 0;
    const at = has ? [0, 0.1, 0.35, 0.6, 0.85].map((f) => f * est) : [0, 2, 6, 10, 18];
    let t0 = performance.now(), ahead = 0, waited = false;
    const tick = () => {
      if (ahead > 0) { waited = true; paint({ ahead }); return; }
      if (waited) { waited = false; t0 = performance.now(); }
      const s = (performance.now() - t0) / 1000;
      let i = 0; at.forEach((t, j) => { if (s >= t) i = j; });
      const time = !has ? `${Math.round(s)}초` : s <= est ? `${Math.round(s)}초 / 약 ${fmtSec(est)}` : `${Math.round(s)}초 · 예상보다 오래 걸리고 있어요`;
      paint({ stage: STAGES[i], time });
    };
    tick();
    const iv = setInterval(tick, 250);
    return { setAhead: (n) => { ahead = n; tick(); }, stop: () => clearInterval(iv) };
  }
  window.padoProgress = progress;
  const aheadMsg = (n) => `앞에 ${n}건 — 차례가 되면 바로 시작해요`;
  window.padoAheadMsg = aheadMsg;

  async function check(text, signal, onAhead) {
    const fd = new FormData();
    fd.append("file", new File([text.replace(/\n/g, " ")], "draft.txt", { type: "text/plain" }));
    const d = await send("/upload", fd, signal, onAhead);
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
  window.padoCheckExport = async function (exportObj, signal, onAhead) {
    const fd = new FormData();
    fd.append("file", new File([JSON.stringify(exportObj)], "draft.json", { type: "application/json" }));
    const d = await send("/upload", fd, signal, onAhead);
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
  // 시 · 도 이름(「제주」 · 「서울특별시」 · 「경기도에서」)에는 「시나 도 이름을 써 보세요」가 맞지 않는다 (#385 E7)
  const JOSA = "(?:에서는|에서도|에서|으로는|으로|이에요|이에|이랑|하고|까지|부터|에는|에도|은|는|이|가|을|를|에|도|의|로|랑|와|과)";
  const SIDO = new RegExp("^(?:(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주|충청북|충청남|전라북|전라남|경상북|경상남)"
    + "(?:특별시|광역시|특별자치시|특별자치도|도|시)?|\\S+(?:특별시|광역시|특별자치시|특별자치도))" + JOSA + "?$");
  const isSido = (t) => SIDO.test(String(t || "").replace(/\s+/g, ""));
  const TIP_SIDO = "이미 넓은 지역 이름이에요. 다른 글과 합치면 좁혀질 수 있어요";
  // 지명 뒤 조사 떼기 — 레일의 「」 표시용(형광 경계는 그대로 · #385 E13). 끝에서만 떼고, 지명 자체를 자르지 않게
  // 한 글자 조사(이 · 가 · 에 · 로 …)는 남는 말이 동 · 구 · 시 · 역처럼 지명 끝 글자로 끝날 때만 뗀다(「종로」 · 「을지로」를 지키려고)
  const JOSA_TAIL = new RegExp(JOSA + "$");
  window.padoBarePlace = function (t) {
    const s = String(t || ""), m = s.match(JOSA_TAIL);
    if (!m) return s;
    const rest = s.slice(0, -m[0].length);
    if (Array.from(rest).length < 2) return s;
    if (m[0].length >= 2 || /[동구시군읍면리도역]$/.test(rest) || (m[0] !== "도" && isSido(rest))) return rest;   // 「강원도」 · 「제주도」의 도는 지명
    return s;
  };
  const cpLen = (s) => Array.from(s || "").length;

  /* 실시간 — 타자가 멈추고 delay 뒤 자동 점검. 서버 보호: 디바운스 · 이전 요청 취소 · minChars 미만 생략 · 같은 글 재요청 안 함.
     padoLive({ textarea, backdrop, chip, warn?, delay=800, minChars=20 }) */
  window.padoLive = function ({ textarea, backdrop, chip, warn, pick, onResult, delay = 800, minChars = 20 }) {
    let timer = null, ctrl = null, lastText = null;
    let retry = null, retried = null;   // 429 뒤 자동 재시도 — 같은 글은 한 번만 (#385 E12)
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
        if (ctrl) { ctrl.abort(); ctrl = null; }   // 점검 중에 글을 줄였으면 앞 요청 · 대기표 표시 · 429 재시도를 같이 멈춘다
        clearTimeout(retry); retry = null;
        lastText = text; cur = { spans: [], rewrites: new Map() }; paint(text, []); setChip("", ""); if (warn) warn.hidden = true; hidePick();
        if (onResult) onResult(null);
        return;
      }
      if (ctrl) ctrl.abort();
      ctrl = new AbortController();
      clearTimeout(retry); retry = null;
      setChip("확인 중<span class=\"dots\"></span>", "busy");
      // 앞에 다른 점검(기존 공개 글 점검 등)이 있으면 기다리는 이유를 보인다 (#385 E10)
      const mine = ctrl;
      let waiting = false;   // 바뀔 때만 다시 그린다 — 1초마다 그리면 점 애니메이션이 처음부터 다시 돈다
      const onAhead = (n) => {
        if (mine !== ctrl || (n > 0) === waiting) return;
        waiting = n > 0;
        setChip(waiting ? "확인 중 — 앞에 다른 점검이 있어요" : "확인 중<span class=\"dots\"></span>", "busy");
      };
      try {
        const { spans, k, rewrites, steps, risk } = await check(text, ctrl.signal, onAhead);
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
        if (mine !== ctrl || textarea.value !== text) return;   // 늦게 온 오류 — 지금 글과 상관없다
        if (e.status === 429) {
          if (retried !== text) {   // 30초 뒤 한 번만 — 그사이 글을 고치면 input 이 새로 점검한다
            retried = text;
            setChip(BUSY_MSG, "err");
            retry = setTimeout(() => { retry = null; if (textarea.value === text) run(); }, RETRY_MS);
          } else {
            setChip("요청이 많아 잠깐 쉬고 있어요. 글을 고치면 다시 확인할게요.", "err");
          }
          return;
        }
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
        const tip = s.type === "LOC_ADMIN" && isSido(s.text) ? TIP_SIDO : TIP[s.type];
        body = `<p class="pado-tip">${esc(tip || "이 표현은 빼거나 더 넓은 말로 바꿔 보세요.")}</p>`;
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

    textarea.addEventListener("input", () => { clearTimeout(timer); clearTimeout(retry); retry = null; timer = setTimeout(run, delay); paint(textarea.value, []); sync(); hidePick(); });
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
    let retry = null;   // 429 뒤 30초 자동 재시도 — 한 번만 (#385 E12)
    btn.addEventListener("click", () => go(false));
    async function go(isRetry) {
      clearTimeout(retry); retry = null;
      const text = (getText() || "").trim();
      if (!text) { out.innerHTML = muted("본문을 먼저 써 주세요."); return; }
      btn.disabled = true;
      // 「점검 중…」만 보이던 것 — 단계 이름 + 흐른 시간, 앞에 다른 점검이 있으면 차례 (#385 E9)
      const prog = progress(({ ahead, stage, time }) => {
        out.innerHTML = muted(ahead ? esc(aheadMsg(ahead)) : `${esc(stage)} · ${esc(time)}`);
      });
      try {
        const fd = new FormData();
        fd.append("file", new File([text.replace(/\n/g, " ")], "draft.txt", { type: "text/plain" }));
        const d = await send("/upload", fd, undefined, prog.setAhead);
        prog.stop();
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
            + `<mark${maybe(s) ? ' data-maybe="1"' : ""} style="${markStyle(s, false)}border-radius:3px;padding:1px 2px;" title="${esc(LABEL[s.type] || s.type)}${maybe(s) ? MAYBE_HINT(s) : ""}">`
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
        prog.stop();
        if (e.status === 429 && !isRetry) {   // 요청이 많음 — 30초 뒤 한 번 자동으로 다시 (그사이 버튼을 누르면 그게 먼저)
          out.innerHTML = muted(BUSY_MSG);
          retry = setTimeout(() => go(true), RETRY_MS);
          return;
        }
        if (e.status === 429) { out.innerHTML = muted("요청이 많아 잠깐 쉬고 있어요. 조금 뒤 다시 눌러 주세요."); return; }
        // 429 가 아닌 오류 — 서버의 한국어 사유(너무 긴 글 등)가 있으면 그대로
        const detail = detailOf(e);
        out.innerHTML = muted(detail ? `점검하지 못했습니다. ${esc(detail)}` : "점검하지 못했습니다. 잠시 뒤 다시 시도해 주세요.");
      } finally {
        btn.disabled = false;
      }
    }
  };
})();
