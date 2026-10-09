// 세 화면이 공유하는 최소 유틸. sessionStorage 로 스캔 결과를 넘긴다.

function saveScan(result) {
  sessionStorage.setItem("scanResult", JSON.stringify(result));
}

function loadScan() {
  const raw = sessionStorage.getItem("scanResult");
  return raw ? JSON.parse(raw) : null;
}

async function showEngineBadge(elId) {
  try {
    const r = await fetch("../api/engine-mode");
    const d = await r.json();
    document.getElementById(elId).textContent =
      (d.mode === "real" ? "엔진 · 실제" : "엔진 · 목") + (d.c1_rules ? " · 명시 규칙 병합" : "");
  } catch (e) {
    document.getElementById(elId).textContent = "엔진 · 확인 불가";
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

// 후보 수 — 「약 4,069명」
function fmtK(k) {
  if (k === null || k === undefined) return "산출 불가";
  return `약 ${Math.round(k).toLocaleString("ko-KR")}명`;
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
      <p>아래 정보는 <b>하나만으로 내 계정이나 연락처에 바로 닿습니다.</b> 위험 점수(같은 조건의 사람 수)와 별개로 가장 먼저 지우세요.</p>
      <ul>${strong.map(row).join("")}</ul></div>`;
  }
  if (weak.length) {
    out += `<div class="card"><h3>링크 확인</h3>
      <p>계정으로 바로 이어지지는 않지만, 주소에 동네·가게·학교 이름이 들어 있으면 단서가 됩니다. 한 번 확인해 보세요.</p>
      <ul>${weak.map(row).join("")}</ul></div>`;
  }
  return out;
}

// 글을 합치면 드러나는 시점 — 서버 timeline(#331). 「3주차 · 7주차 · 9주차」를 합치면 시작한 날이 나온다
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
    const how = { post_date: "글 작성일과 차수(n일차 · n주차)", text: "글에 적은 날짜와 차수(n일차 · n주차)",
      mixed: "글에 적은 날짜 · 글 작성일과 차수(n일차 · n주차)" }[g.anchor] || "날짜와 차수";
    const seen = new Set();
    const items = (g.marks || []).filter(m => !seen.has(m.post_id + m.value) && seen.add(m.post_id + m.value)).slice(0, 5)
      .map(m => `<li><mark>${esc(m.date_value ? m.date_value + " … " + m.value : m.value)}</mark> — 「${esc(postLabel(posts[m.post_id]) || m.post_id)}」</li>`).join("");
    const lead = g.n_posts >= 2 ? `글 ${g.n_posts}편을 합치면` : "이 글 하나로";
    return `<li><p>${lead} ${what}이 <b>${esc(when)}</b>쯤으로 계산됩니다 <small>(${how}로 거꾸로 셈)</small></p><ul>${items}</ul></li>`;
  }).join("");
  return `<div class="card"><h3>글을 합치면 드러나는 시점</h3>
    <p>날짜와 「n일차 · n주차」를 함께 쓰면 언제 시작했는지(입사 · 이사 · 여행 등)가 계산됩니다. 시작한 날은 다른 단서와 합쳐 글쓴이를 좁히는 데 쓰입니다.
    글에서 차수(「n일차 · n주차」)를 지우면 계산되지 않습니다. 글 작성일도 기준이 되므로 본문 날짜만 지워서는 부족하고, 글이 많으면 몇 편만 숨겨도 남은 글로 계산됩니다.</p>
    <ul>${cards}</ul></div>`;
}

const TYPE_LABEL = {
  LOC_ADMIN: "지역", LOC_FACILITY: "장소", REL_HOME: "집 근처", REL_WORK: "직장 근처", AGE: "나이", SEX: "성별",
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
  exact: "정확", range: "범위", decade: "연령대",
};

const ATTR_LABEL = {
  age: "나이", sex: "성별", location: "거주지", occupation: "직업",
  family: "가족", commute: "통근", income: "소득",
};
