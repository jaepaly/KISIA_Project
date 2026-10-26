// 세 화면이 공유하는 최소 유틸. sessionStorage 로 스캔 결과를 넘긴다.

// 같은 Veilo 계정을 다시 점검하면 바로 앞 결과의 요약 하나(scanPrev)를 남긴다 — 위험 줄이기 화면의 「직전 점검 → 이번 점검」 (#385 C3).
// 다른 계정 · 파일 업로드 · 처음 점검이면 버린다. 결과 전체가 아니라 비교할 숫자만 둔다(탭 저장소 용량)
function saveScan(result) {
  let old = null;
  try { old = loadScan(); } catch { /* 깨진 옛 결과 — 비교 없이 */ }
  try {
    if (old && result && !isUpload(old) && !isUpload(result) && old.user_ref && old.user_ref === result.user_ref) {
      sessionStorage.setItem("scanPrev", JSON.stringify(scanSummary(old)));
    } else sessionStorage.removeItem("scanPrev");
  } catch { /* 저장소가 막혀도 점검 결과는 넘긴다 */ }
  // 점검한 시각 — 다음 점검 때 「직전 점검 ○시」로 쓴다(요약을 만드는 시각이 아니라)
  if (result && !result.scanned_at) result.scanned_at = Date.now();
  sessionStorage.setItem("scanResult", JSON.stringify(result));
}

function loadScan() {
  const raw = sessionStorage.getItem("scanResult");
  return raw ? JSON.parse(raw) : null;
}

// 같은 점검 결과를 고쳐 쓴다 — 「내 얘기 아님」으로 다시 센 값. 새 점검이 아니라 직전 점검 요약(scanPrev)은 건드리지 않는다
function updateScan(result) {
  sessionStorage.setItem("scanResult", JSON.stringify(result));
}

// 「내 얘기 아님」으로 뺀 단서 — diagnosis.html 이 /api/recompute 로 다시 센 뒤 결과에 함께 둔다(화면 전용).
// [{axis, value, sources: [{post_id, span_id | geo_tag}]}]. 빈 목록이면 처음 점검 그대로
function clueExclusions(data) {
  return (data && Array.isArray(data.clue_exclusions)) ? data.clue_exclusions : [];
}
function excludedSpanKeys(data) {
  const out = new Set();
  for (const c of clueExclusions(data)) for (const s of c.sources || []) if (s.span_id) out.add(`${s.post_id}|${s.span_id}`);
  return out;
}

// 직전 점검 요약 — 지금 결과와 같은 Veilo 계정일 때만 돌려준다(없으면 null)
function loadPrevScan(data) {
  try {
    const p = JSON.parse(sessionStorage.getItem("scanPrev") || "null");
    return p && data && !isUpload(data) && p.user_ref === data.user_ref ? p : null;
  } catch { return null; }
}

// 비교할 숫자만 — 노출 위험도(위험 줄이기 화면의 「지금」 값) · 같은 조건의 사람 수 · 공개 글 ID · 내 단서 유형별 개수(남의 정보는 뺀다)
function scanSummary(d) {
  const rec = ((d.stage2 || {}).output || {}).recommendation || {};
  const risk = (rec.projected || {}).current_risk ?? ((d.contribution || {}).output || {}).baseline_risk ?? null;
  const types = {};
  for (const e of Object.values(d.spans || {})) {
    for (const s of (e.spans || [])) if (s.subject !== "other") types[s.type] = (types[s.type] || 0) + 1;
  }
  return { user_ref: d.user_ref, at: d.scanned_at || null, risk, k: ((d.specificity || {}).output || {}).k ?? null,
    post_ids: (d.posts || []).map(p => p.post_id), types };
}

// 파일 업로드 결과인가 — 업로드 글은 Veilo 에 없어 글 링크 · 다시 점검 · 「Veilo 에서 고치기」가 깨진다 (B3).
// source 가 없는 옛 결과는 업로드 글 ID(upload_000)로 가린다
function isUpload(data) {
  return !!data && (data.source === "upload" || (data.posts || []).some(p => String(p.post_id).startsWith("upload_")));
}

// .txt 업로드는 비어 있지 않은 줄 하나를 글 한 편으로 읽는다(file_adapter) — 파일 하나가 여러 편으로 보이는 이유를 적는다 (#385 B1).
// upload_kind 는 scan.html 이 파일 이름으로 남긴다. .json 은 posts 배열을 그대로 읽어 해당 없음
function uploadSplitNote(data) {
  if (!isUpload(data) || data.upload_kind !== "txt") return "";
  const n = (data.posts || []).length;
  return `파일의 줄 ${n}개를 글 ${n}편으로 나눠 읽었습니다. 빈 줄은 빼고 한 줄을 글 한 편으로 봅니다. 글 한 편을 한 덩어리로 보려면 문단을 한 줄로 이어 쓰세요.`;
}

// 실제 엔진이면 배지를 숨기고, 예시 계산(mock)일 때만 알린다 — 엔진 이름 · 규칙 병합 같은 내부 정보는 화면에 내지 않는다
async function showEngineBadge(elId) {
  const el = document.getElementById(elId);
  try {
    const r = await fetch("../api/engine-mode");
    const d = await r.json();
    el.textContent = d.mode === "real" ? "" : "예시 결과 (시연용 계산)";
  } catch (e) {
    el.textContent = "";
  }
}

// 글 원문·사용자 입력은 반드시 이스케이프해서 넣는다 — 업로드한 글에 <script> 가 있어도 실행되지 않게
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// 스팬 오프셋은 유니코드 문자(코드포인트) 단위다 — JS 문자열 slice 는 UTF-16 이라 이모지 뒤에서 어긋난다
function cpSlice(text, start, end) {
  return Array.from(text || "").slice(start, end).join("");
}

// 같은 조건의 사람 수 — 「약 4,069명」
function fmtK(k) {
  if (k === null || k === undefined) return "계산할 수 없음";
  return `약 ${Math.round(k).toLocaleString("ko-KR")}명`;
}

// 「약 4,069명 중 한 명」 — 사람 수를 말로 (한 명 이하로 좁혀지면 그렇게)
function fmtOneOf(k) {
  if (k === null || k === undefined) return "계산할 수 없음";
  if (Math.round(k) <= 1) return "거의 한 명으로 좁혀짐";
  return `약 ${Math.round(k).toLocaleString("ko-KR")}명 중 한 명`;
}

// ── 진행 표시 — 점검은 한 번의 요청이라 서버가 진행률을 주지 않는다. 단계와 흐른 시간을 아래 띠로 보여 준다 ──
// 내 글 점검(scan.html)과 위험 줄이기의 「다시 점검」(action.html)이 같이 쓴다. 띠가 없는 화면이면 만든다.
// est(초)를 주면 예상을 범위로 보인다 — 「3초 / 약 20초~50초」(서버 /sns/estimate · /api/scan-estimate — 글자 수 × 이 서버의 실측 속도).
// 범위 위쪽은 est 의 2배(짧으면 +10초) — 같은 서버 · 같은 날에도 2배쯤 달라졌다(integration-W08 v2 재검증 · t3 버스트 크레딧).
// 업로드는 글자 수를 파일 크기로 어림해 더 틀린다 · 예상보다 오래 걸린다는 지적 (#385 B7). 막대는 위쪽 끝에 맞춰 90%까지 차오른다.
// 위쪽을 넘기면 막대는 멈춘 채 「예상보다 오래 걸리고 있습니다」를 눈에 띄게. est 가 없으면 예전처럼 오가는 막대.
// 단계 이름은 서버가 알려 주는 실제 단계가 아니라 흐른 시간으로 바꾸는 표시다 — 실제 진행처럼 「○단계」로 보이지 않게 둔다
let _pt = null;
function fmtSec(s) { s = Math.max(1, Math.round(s)); return s < 60 ? `${s}초` : `${Math.floor(s / 60)}분 ${s % 60 ? (s % 60) + "초" : ""}`.trim(); }
// 점검 대기표 — 점검 POST 에 X-Scan-Ticket 으로 싣고, 기다리는 동안 /api/scan-queue 로 1초마다 차례를 묻는다(서버는 점검을 하나씩만 돌린다).
// 쓰는 법: const t = scanTicket(); fetch(url, { method: "POST", headers: { "X-Scan-Ticket": t } }) 와 함께 watchQueue(t)
let _qt = null, _qa = null, _qgen = 0, _queue = { ahead: 0, wasWaiting: false };
function scanTicket() {
  const a = new Uint8Array(12);
  (window.crypto || {}).getRandomValues ? crypto.getRandomValues(a) : a.forEach((_, i) => { a[i] = Math.random() * 256; });
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}
// 앞 물음이 끝난 뒤 다음을 예약한다(응답 순서가 뒤집히지 않게) · 점검마다 세대 번호 — 끝난 점검의 늦은 응답은 버린다(Codex P2)
function watchQueue(ticket) {
  stopQueue();
  const gen = ++_qgen;
  const ask = async () => {
    _qa = new AbortController();
    try {
      const r = await fetch(`../api/scan-queue?ticket=${encodeURIComponent(ticket)}`, { signal: _qa.signal });
      if (r.ok) { const q = await r.json(); if (gen === _qgen) _queue.ahead = q.waiting ? Math.max(1, q.ahead) : 0; }
    } catch { /* 못 물으면 띠만 그대로 · 취소도 여기로 */ }
    if (gen === _qgen) _qt = setTimeout(ask, 1000);
  };
  _qt = setTimeout(ask, 400);   // 바로 자리를 잡은 점검은 줄에 없다 — 첫 물음은 조금 뒤에
}
function stopQueue() {
  _qgen++;
  clearTimeout(_qt); _qt = null;
  if (_qa) { _qa.abort(); _qa = null; }
  _queue = { ahead: 0, wasWaiting: false };
}
function progressStart(title, note, est) {
  let box = document.getElementById("progress");
  if (!box) {
    box = document.createElement("div");
    box.className = "progress"; box.id = "progress"; box.hidden = true;
    box.innerHTML = `<div class="progress-in"><div class="pbar"><i></i></div>
      <div class="ptext"><b id="pTitle">읽는 중</b><span id="pStage"></span><span class="pt" id="pTime">0초</span></div>
      <p class="muted" id="pNote">글이 많거나 길면 1분 가까이 걸립니다. 창을 닫지 말고 기다려 주세요.</p></div>`;
    document.body.appendChild(box);
  }
  const el = (id) => document.getElementById(id);
  const bar = box.querySelector(".pbar");
  const hasEst = typeof est === "number" && est > 0;
  const hi = hasEst ? Math.max(est * 2, est + 10) : 0;
  const range = hasEst ? `약 ${fmtSec(est)}~${fmtSec(hi)}` : "";
  const over = (on) => { for (const id of ["pTime", "pNote"]) { el(id).style.color = on ? "var(--red)" : ""; el(id).style.fontWeight = on ? "600" : ""; } };
  let isOver = false;
  bar.classList.toggle("det", hasEst); bar.classList.remove("wait"); bar.style.setProperty("--p", "0");
  el("pTitle").textContent = title; el("pStage").textContent = ""; el("pTime").textContent = hasEst ? `0초 / ${range}` : "0초";
  over(false);
  const baseNote = note || (hasEst ? `글 길이로 어림한 예상 시간은 ${range}입니다. 서버 상황에 따라 더 걸릴 수 있습니다. 창을 닫지 말고 기다려 주세요.` : "");
  if (baseNote) el("pNote").textContent = baseNote;
  box.hidden = false; document.body.classList.add("busy");
  let t0 = performance.now();
  // 단계 — 예상 시간이 있으면 그 비율로(0 · 10 · 35 · 60 · 85%), 없으면 예전 초 기준
  const at = hasEst ? [0, 0.1, 0.35, 0.6, 0.85].map((f) => f * hi) : [0, 2, 6, 10, 18];
  const names = ["글 읽는 중", "개인정보 단서 찾는 중", "같은 조건의 사람 수 계산 중", "위험 줄일 방법 확인 중", "거의 다 됐습니다"];
  clearInterval(_pt);
  _pt = setInterval(() => {
    // 앞사람이 있으면 띠를 멈추고 차례를 보인다 — 띠가 예상 시간에 다 찬 뒤 오래 멈춰 있지 않게(E 리뷰 #368). 차례가 오면 0초부터 다시
    if (_queue.ahead > 0) {
      _queue.wasWaiting = true;
      bar.classList.add("wait"); bar.style.setProperty("--p", "0");
      el("pTime").textContent = "기다리는 중";
      el("pStage").textContent = ` · 앞에 ${_queue.ahead}명 — 차례가 되면 바로 시작합니다`;
      return;
    }
    if (_queue.wasWaiting) { _queue.wasWaiting = false; t0 = performance.now(); bar.classList.remove("wait"); }
    const s = (performance.now() - t0) / 1000;
    if (hasEst) {
      const late = s > hi;
      el("pTime").textContent = late ? `${fmtSec(s)} · 예상보다 오래 걸리고 있습니다` : `${Math.round(s)}초 / ${range}`;
      bar.style.setProperty("--p", String(Math.min(0.9, (s / hi) * 0.9)));
      if (late !== isOver) {
        isOver = late; over(late);
        el("pNote").textContent = late
          ? `예상(${range})보다 오래 걸리고 있습니다. 점검은 아직 진행 중입니다 — 서버가 붐비거나 글이 길면 더 걸립니다. 창을 닫지 말고 기다려 주세요. 끝나면 바로 결과로 넘어갑니다.`
          : baseNote;
      }
    } else el("pTime").textContent = `${Math.round(s)}초`;
    let i = 0; at.forEach((t, j) => { if (s >= t) i = j; });
    el("pStage").textContent = " · " + names[i];
  }, 250);
}
function progressStop() {
  clearInterval(_pt);
  stopQueue();
  const box = document.getElementById("progress");
  if (box) box.hidden = true;
  document.body.classList.remove("busy");
}

// 서버가 만든 설명 문장(추천 근거 rationale)을 화면 용어로 — 「명시 단서」 → 「직접 쓴 정보」 (문구 통일 §8 · M1)
function uiText(s) {
  return String(s || "").replace(/명시 단서/g, "직접 쓴 정보").replace(/명시적 단서/g, "직접 쓴 정보");
}

// 글의 위치 태그 — export 계약(sns-minimal-spec)은 posts[].activity_meta.geo_tag 다. 최상위 geo_tag 는 없다 (B4)
function geoTagOf(post) {
  return (post && ((post.activity_meta || {}).geo_tag || post.geo_tag)) || null;
}

// 깔때기 조건의 «…» 가 행정코드(3171025000)뿐이면 글에서 찾은 지명으로 바꾼다 — 코드를 화면에 내지 않는다.
// 조건(specificity.input.conditions)의 geo_code → 그 조건을 낸 글의 본인 지역 단서 → 위치 태그 순. 못 찾으면 「사는 동네」
function placeName(data, text) {
  if (!/^\d{5,10}$/.test(String(text))) return text;
  const conds = ((data.specificity || {}).input || {}).conditions || [];
  const posts = Object.fromEntries((data.posts || []).map(p => [p.post_id, p]));
  for (const c of conds) {
    if (String(c.geo_code) !== String(text)) continue;
    if (c.value && !/^\d+$/.test(String(c.value))) return c.value;
    for (const pid of c.source_post_ids || []) {
      const s = (((data.spans || {})[pid] || { spans: [] }).spans || [])
        .find(x => x.subject !== "other" && String(x.type).startsWith("LOC"));
      if (s) return s.text;
      const geo = geoTagOf(posts[pid]);
      if (geo) return geo;
    }
  }
  return "사는 동네";
}

// 글의 채널별 원문 — 스팬의 text_id 와 같은 이름 (title · body · photo_caption:N)
function channelsOf(post) {
  const out = [];
  if (post.title) out.push(["title", post.title]);
  out.push(["body", post.body || ""]);
  (post.photos || []).forEach((ph, i) => {
    const cap = ph && typeof ph === "object" ? ph.caption : ph;
    if (cap) out.push([`photo_caption:${i}`, cap]);
  });
  return out;
}

// 사용자에게 보여 줄 글 이름 — 제목, 없으면 본문 첫 구절 (글 ID 는 사람이 못 알아본다)
function postLabel(post) {
  if (!post) return "";
  if (post.title) return post.title;
  const body = (post.body || "").replace(/\s+/g, " ").trim();
  return body.length > 24 ? body.slice(0, 24) + "…" : body;
}

// 계정 링크 · 이메일 · 전화 · @아이디 — 서버 direct_identifiers (없으면 빈 목록)
function directIdentifiers(data) {
  const posts = Object.fromEntries((data.posts || []).map(p => [p.post_id, p]));
  const out = [];
  for (const [postId, list] of Object.entries(data.direct_identifiers || {})) {
    for (const f of list) out.push({ ...f, post_id: postId, post: posts[postId] });
  }
  return out;
}

// strong — 계정 링크 · 이메일 · 전화 · @아이디. 일반 링크(strong=false)는 계정에 닿지 않아 확인 권고로만 (Codex 10/8)
function strongIdentifiers(data) {
  return directIdentifiers(data).filter(f => f.strong !== false);
}

function renderDirectIdentifiers(data, heading) {
  const all = directIdentifiers(data);
  const row = f => `<li><b>${esc(f.label)}</b> <code>${esc(f.value)}</code> — 「${esc(postLabel(f.post) || f.post_id)}」</li>`;
  const strong = all.filter(f => f.strong !== false);
  const weak = all.filter(f => f.strong === false);
  let out = "";
  if (strong.length) {
    out += `<div class="card warn"><h3>${heading}</h3>
      <p>아래 정보는 <b>하나만으로 계정이나 연락처로 바로 이어집니다.</b> 노출 위험도나 같은 조건의 사람 수와 상관없이 먼저 지우는 것을 권합니다.</p>
      <ul>${strong.map(row).join("")}</ul></div>`;
  }
  if (weak.length) {
    out += `<div class="card"><h3>링크 확인</h3>
      <p>링크 주소에 동네나 가게, 학교 이름이 들어 있는지 확인해 보세요. 개인정보 단서가 될 수 있습니다.</p>
      <ul>${weak.map(row).join("")}</ul></div>`;
  }
  return out;
}

// 글에서 짐작할 수 있는 시작일 — 서버 timeline(#331). 「3주차 · 7주차 · 9주차」를 합치면 시작한 날이 나온다
function _ymd(iso) {
  const [y, m, d] = String(iso).split("-").map(Number);
  return `${y}년 ${m}월 ${d}일`;
}

function renderTimeline(data) {
  const groups = data.timeline || [];
  if (!groups.length) return "";
  const posts = Object.fromEntries((data.posts || []).map(p => [p.post_id, p]));
  const cards = groups.map(g => {
    const when = g.start ? _ymd(g.start) : `${_ymd(g.start_range[0])} ~ ${_ymd(g.start_range[1])} 사이`;
    // 많이 쓴 말부터 — 「워홀」이 「청소」보다 앞에 오게
    const freq = {};
    for (const m of (g.marks || [])) freq[m.event] = (freq[m.event] || 0) + 1;
    const words = (g.words || []).filter(w => w !== "?").sort((a, b) => (freq[b] || 0) - (freq[a] || 0));
    const shown = words.slice(0, 3).map(esc).join(" · ") + (words.length > 3 ? ` 외 ${words.length - 3}개` : "");
    const what = words.length ? `「${shown}」 시작일` : "무언가를 시작한 날";
    const how = { post_date: "글 작성일과 「n일차」 또는 「n주차」 표현", text: "글에 적은 날짜와 「n일차」 또는 「n주차」 표현",
      mixed: "글의 날짜와 작성일, 「n일차」 또는 「n주차」 표현" }[g.anchor] || "날짜와 「n일차」 또는 「n주차」 표현";
    const seen = new Set();
    const items = (g.marks || []).filter(m => !seen.has(m.post_id + m.value) && seen.add(m.post_id + m.value)).slice(0, 5)
      .map(m => `<li><mark>${esc(m.date_value ? m.date_value + " … " + m.value : m.value)}</mark> — 「${esc(postLabel(posts[m.post_id]) || m.post_id)}」</li>`).join("");
    const lead = g.n_posts >= 2 ? `글 ${g.n_posts}편을 합치면` : "이 글 하나로";
    return `<li><p>${lead} ${what}이 <b>${esc(when)}</b>쯤으로 짐작됩니다 <small>(${how}에서 거꾸로 셈)</small></p><ul>${items}</ul></li>`;
  }).join("");
  return `<div class="card"><h3>글에서 짐작할 수 있는 시작일</h3>
    <p>글의 날짜와 「n일차」, 「n주차」 표현으로 입사나 이사, 여행을 시작한 날을 짐작할 수 있습니다. 시작한 날은 다른 단서와 합쳐져 글쓴이를 좁히는 데 쓰입니다.
    이런 표현을 지우면 시작일이 드러날 위험을 줄일 수 있습니다. 본문 날짜만 지우거나 일부 글만 숨겨도 다른 글에 단서가 남을 수 있습니다.</p>
    <ul>${cards}</ul></div>`;
}

// 해외 거주 — 서버 residence. 본인 거주 표현(「미국에서 지내다 보니」 「미국생활」)이 여러 글에 있으면 사는 곳은 국내 인구 기준으로
// 추정하지 않는다(위치 단서를 사람 수 · 노출 위험도 · 거주지 판정에서 뺀다). residence 가 없는 옛 결과 · 목은 국내로 본다
function isOverseas(data) {
  return !!(data && data.residence && data.residence.overseas);
}

// 해외 거주로 보이면 같은 조건의 사람 수 · 노출 위험도 숫자를 화면에 내지 않는다 — 국내 주민등록 인구(약 5,100만 명)로 센 숫자라
// 현지에서 실제로 좁혀지는 정도보다 훨씬 커 보인다(해외 한인 거주지 + 성별 + 자녀가 현지에선 몇 사람인데 숫자는 수백만).
// 응답의 계약 칸(specificity · contribution · stage2)은 그대로 두고 화면에서만 감춘다
function hideNumbers(data) {
  return isOverseas(data);
}

// 숫자 자리에 놓는 안내 — 점검 결과 첫 카드 · 위험 줄이기 첫 카드
function overseasNumbersNote() {
  return `<p><span class="badge unknown">숫자로 보여 드리지 않음</span> 해외에 사시는 것으로 보여, 같은 조건의 사람 수와 노출 위험도를 숫자로 보여 드리지 않습니다.</p>
    <p class="note">이 숫자는 국내 주민등록 인구로 셉니다. 해외에서는 같은 지역에 사는 한국인이 훨씬 적어서, 같은 단서로도 몇 사람으로 좁혀질 수 있습니다. 국내 기준 숫자를 보여 드리면 실제보다 안전해 보일 수 있습니다. 아래 항목별 판정과 근거로 직접 확인해 주세요.</p>`;
}

function renderOverseasNote(data) {
  if (!isOverseas(data)) return "";
  const r = data.residence;
  const posts = Object.fromEntries((data.posts || []).map(p => [p.post_id, p]));
  const seen = new Set();
  const ev = (r.evidence || []).filter(e => !seen.has(e.post_id) && seen.add(e.post_id)).slice(0, 2)
    .map(e => `<mark>${esc(e.value)}</mark> — 「${esc(postLabel(posts[e.post_id]) || e.post_id)}」`);
  const n = (r.n_posts || {}).residence || 0;
  return `<div class="card tip"><b>해외에 사시는 것으로 보여 사는 곳은 국내 인구 기준으로 추정하지 않았습니다. 나머지 단서는 그대로 점검했습니다.</b>
    <p>글에 적은 지명은 그대로 표시하지만 사는 곳 판정에서는 뺐습니다. 해외에 살지 않는데 이렇게 나왔다면 아래 근거가 된 표현을 확인해 주세요.</p>
    ${ev.length ? `<p class="muted">이렇게 판단한 근거${n > ev.length ? ` (글 ${n}편 중 일부)` : ""}</p><ul>${ev.map(x => `<li>${x}</li>`).join("")}</ul>` : ""}</div>`;
}

const TYPE_LABEL = {
  LOC_ADMIN: "지역명", LOC_FACILITY: "장소명", REL_HOME: "집 근처", REL_WORK: "직장 근처", AGE: "나이", SEX: "성별",
  JOB: "직업", FAM: "가족", COMMUTE: "통근", INCOME: "소득",
};

// 「특정됨」은 「나를 특정했다」로 읽힐 수 있어 「직접 드러남」으로 (#385 E11-1)
const VERDICT_LABEL = {
  specified: "직접 드러남",
  narrowed: "좁혀짐",
  weak_signal: "약한 신호",
  abstain: "판단 보류",
};

const GRAIN_LABEL = {
  sido: "시도", sigungu: "시군구", eupmyeondong: "읍면동",
  exact: "정확한 값", range: "범위", decade: "연령대",
};

// k 등급 — 코드 값은 영문 상수, 화면 문구는 여기서 (필드-대조표 §3 · 경계는 plan.md §13.1)
// 배지는 「같은 조건의 사람 수」만 말한다 — 「위험 낮은 편」이라 쓰면 옆의 노출 위험도(95/100)와 부딪힌다 (UX N1 · M1).
// 두 숫자는 따로 계산한다. 배지에는 뜻만 쓰고 숫자 구간(5명 이상 등)은 툴팁으로 — 옆의 「약 N명 중 한 명」과 숫자 둘이 나란히 보여 헷갈렸다 (#385 E1)
// 「5명 이상」도 안전하다는 뜻이 아니다(툴팁)
const K_LEVEL_LABEL = {
  VERY_HIGH: ["한 사람으로 좁혀질 수 있음", "같은 조건의 사람 2명 이하"],
  HIGH: ["몇 사람으로 좁혀짐", "같은 조건의 사람 2명 초과 5명 미만"],
  ACCEPTABLE: ["한 사람으로 바로 좁혀지진 않음", "같은 조건의 사람 5명 이상 — 다른 글과 합치면 줄어들 수 있음. 노출 위험도와는 따로 계산함"],
  UNKNOWN: ["사람 수를 셀 수 없음", "단서가 부족해 같은 조건의 사람 수를 셀 수 없음"],
};

const ATTR_LABEL = {
  age: "나이", sex: "성별", location: "거주지", occupation: "직업",
  family: "가족", commute: "통근", income: "소득",
};

// Veilo 상단바 · 하단 탭바의 링크와 그림 — Veilo 주소(head.js VEILO_BASE)를 붙인다. 인스턴스는 "" 라 같은 도메인 루트
document.querySelectorAll("[data-veilo-href]").forEach((a) => { a.href = (window.VEILO_BASE || "") + a.dataset.veiloHref; });
document.querySelectorAll("[data-veilo-src]").forEach((img) => { img.src = (window.VEILO_BASE || "") + img.dataset.veiloSrc; });
// 상단바 「내 계정」 아바타 — Veilo 세션의 내 계정(GET VEILO_BASE/api/me). Veilo base.html 의 아바타와 같은 모양.
// 운영은 같은 도메인이라 쿠키가 따라간다. 로컬 분리 실행에서 쿠키나 CORS 로 막히면 자리를 숨긴 채 둔다(오류 없이)
(function acctAvatar() {
  const slot = document.getElementById("acctSlot");
  if (!slot || !window.fetch) return;
  const base = window.VEILO_BASE || "";
  fetch(base + "/api/me", { credentials: "include" })
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => {
      const me = j && j.me;
      if (!me || !me.user_ref) return;
      const a = document.createElement("a");
      a.className = "avatar me-av";
      a.href = `${base}/u/${encodeURIComponent(me.user_ref)}`;
      a.title = `내 계정 — ${me.nickname}` + (me.changes ? ` · 바꾼 것 ${me.changes}개` : "");
      a.setAttribute("aria-label", `내 계정 ${me.nickname}`);
      a.style.background = `hsl(${me.hue},45%,86%)`;
      a.style.color = `hsl(${me.hue},35%,32%)`;
      a.textContent = Array.from(me.nickname || "?")[0];
      if (me.changes) {
        const n = document.createElement("span");
        n.className = "me-n";
        n.textContent = me.changes;
        a.appendChild(n);
      }
      slot.replaceWith(a);
    })
    .catch(() => {});
})();
// 상단바 스크롤 그림자 — Veilo base.html 과 같은 동작
(function () {
  const top = document.getElementById("utTop");
  if (!top) return;
  const apply = () => top.classList.toggle("scrolled", window.scrollY > 8);
  apply();
  window.addEventListener("scroll", apply, { passive: true });
})();

// 「Veilo로 돌아가기」 — Veilo 주소는 head.js 의 VEILO_BASE (config.js SNS_PUBLIC 에서). 빈 값이면 같은 도메인 루트 (인스턴스)
// 점검한 계정이 있으면 그 사람 프로필로 보낸다 — 비공개로 바꾸기 같은 실제 변경은 거기서 한다 (M2).
// 주소의 ?u= (Veilo 프로필에서 넘어옴) → 저장된 점검 결과 순. 파일 업로드 결과는 Veilo 계정이 아니라 홈으로
(function backToVeilo() {
  const base = window.VEILO_BASE || "";
  const scan = loadScan();
  const u = new URLSearchParams(location.search).get("u") || (scan && !isUpload(scan) ? scan.user_ref : null);
  const nick = scan && scan.user_ref === u ? scan.nickname : "";
  document.querySelectorAll("a.back-sns").forEach((a) => {
    a.href = u ? `${base}/u/${encodeURIComponent(u)}` : `${base}/`;
    a.textContent = u ? `← ${nick ? nick + "님 " : ""}Veilo 프로필로` : "← Veilo로 돌아가기";
  });
})();
