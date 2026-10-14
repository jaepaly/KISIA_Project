// 세 화면이 공유하는 최소 유틸. sessionStorage 로 스캔 결과를 넘긴다.

function saveScan(result) {
  sessionStorage.setItem("scanResult", JSON.stringify(result));
}

function loadScan() {
  const raw = sessionStorage.getItem("scanResult");
  return raw ? JSON.parse(raw) : null;
}

// 파일 업로드 결과인가 — 업로드 글은 Veilo 에 없어 글 링크 · 다시 점검 · 「Veilo 에서 고치기」가 깨진다 (B3).
// source 가 없는 옛 결과는 업로드 글 ID(upload_000)로 가린다
function isUpload(data) {
  return !!data && (data.source === "upload" || (data.posts || []).some(p => String(p.post_id).startsWith("upload_")));
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

// ── 진행 표시 — 점검은 한 번의 요청이라 퍼센트는 없다. 단계와 흐른 시간을 아래 띠로 보여 준다 ──
// 내 글 점검(scan.html)과 위험 줄이기의 「다시 점검」(action.html)이 같이 쓴다. 띠가 없는 화면이면 만든다
let _pt = null;
function progressStart(title, note) {
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
  el("pTitle").textContent = title; el("pStage").textContent = ""; el("pTime").textContent = "0초";
  if (note) el("pNote").textContent = note;
  box.hidden = false; document.body.classList.add("busy");
  const t0 = performance.now();
  const stages = [[0, "글 읽는 중"], [2, "개인정보 단서 찾는 중"], [6, "같은 조건의 사람 수 계산 중"], [10, "위험 줄일 방법 확인 중"], [18, "거의 다 됐습니다"]];
  clearInterval(_pt);
  _pt = setInterval(() => {
    const s = (performance.now() - t0) / 1000;
    el("pTime").textContent = `${Math.round(s)}초`;
    const st = stages.filter(([at]) => s >= at).pop(); if (st) el("pStage").textContent = " · " + st[1];
  }, 250);
}
function progressStop() {
  clearInterval(_pt);
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

const TYPE_LABEL = {
  LOC_ADMIN: "지역명", LOC_FACILITY: "장소명", REL_HOME: "집 근처", REL_WORK: "직장 근처", AGE: "나이", SEX: "성별",
  JOB: "직업", FAM: "가족", COMMUTE: "통근", INCOME: "소득",
};

const VERDICT_LABEL = {
  specified: "특정됨",
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
// 두 숫자는 따로 계산한다. 등급 이름 대신 구간(5명 이상 등)만 — 「5명 이상」도 안전하다는 뜻이 아니다(툴팁)
const K_LEVEL_LABEL = {
  VERY_HIGH: ["2명 이하", "같은 조건의 사람 2명 이하 — 한 사람으로 좁혀질 수 있음"],
  HIGH: ["5명 미만", "같은 조건의 사람 2명 초과 5명 미만 — 몇 사람으로 좁혀짐"],
  ACCEPTABLE: ["5명 이상", "같은 조건의 사람 5명 이상 — 다른 글과 합치면 줄어들 수 있음. 노출 위험도와는 따로 계산함"],
  UNKNOWN: ["셀 수 없음", "단서가 부족해 같은 조건의 사람 수를 셀 수 없음"],
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
