/* 「파도풀이란?」 소개 장면 (about.html) — motion-core.js 위에서 돈다.
   A #narrow : 글 카드가 하나씩 쌓이고, 조건에 맞는 사람 수(가상 예시)가 로그 단위로 줄며 점이 꺼진다. 「나」 하나만 남는다.
               점은 가상의 동네 지도 위에 있다 — 「나」(가운데)에서 먼 점부터 꺼지고, 지도가 가운데로 다가간다(배율 --z 1 → ZMAX).
               카드가 나올 때 그 글이 가리키는 곳에 핀(.ps-pinm[data-card])이 꽂힌다.
               카드 · 숫자 · 점 · 밤 막이 모두 같은 진행도(motion-core 의 관성 보간 cur)를 쓴다. 카드 등장 구간은 겹친다
               (앞 카드가 다 나오기 전에 다음이 시작 — 계단처럼 안 보이게) · 숫자 = 나온 카드 수만큼 로그 공간에서 보간.
   B #steps  : 네 단계가 한 단계씩 켜진다 — 스크롤은 「몇 단계까지 왔나」만 정하고, 보이는 단계는 한 번에 한 단계씩 비슷한 빠르기로 따라간다(0.44초 · 뒤처지면 0.3초)
               (빨리 내려도 1 → 2 → 3 → 4 가 차례로). 그림판(.ps-vis-i)은 지금 단계 그림만(--f) · 그림 안 움직임(--t) · 전환은 CSS 시간
   C         : 읽기 진행 막대 · 소개 순서(Page map) · 어두운 구간이면 html.dark-chapter · 첫 화면 스크롤 신호(40px 넘게 내리면 숨김).
   정지 상태(html.ps-static)에서는 모든 장면이 끝난 모습 그대로다 — CSS 가 그렇게 그리고, 여기서는 캔버스만 끝 모습으로 한 번 그린다. */
(function () {
  "use strict";
  const M = window.PadoMotion;
  if (!M) return;
  const { clamp, smooth } = M;
  const root = document.documentElement;
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  // 한 번 쓴 값은 다시 안 쓴다 — 같은 값을 매 프레임 스타일에 쓰지 않게
  const last = new WeakMap();
  function setVar(el, name, v) {
    const r = Math.round(v * 1000) / 1000;
    let m = last.get(el);
    if (!m) { m = {}; last.set(el, m); }
    if (m[name] === r) return;
    m[name] = r;
    el.style.setProperty(name, String(r));
  }

  // ── 연출 A — 글이 쌓일수록 좁혀진다 ─────────────────────────────────────
  const narrow = M.track($("#narrow"));
  const posts = $$(".ps-post", narrow);
  const stageEl = $(".ps-stage", narrow);
  const pins = $$(".ps-pinm", narrow).map((el) => ({ el, i: +el.dataset.card }));
  const ZMAX = 1.6;   // 지도 최대 배율 — 핀(가운데에서 가장 먼 것이 약 30%)이 화면 안에 남는 값
  // 무대 크기(px) — 핀이 배율만큼 transform 으로 움직일 거리. 크기가 바뀔 때만 쓴다(프레임마다 재지 않는다)
  if (stageEl && "ResizeObserver" in window) {
    new ResizeObserver((e) => { const r = e[0].contentRect; stageEl.style.setProperty("--sw", String(Math.round(r.width))); stageEl.style.setProperty("--sh", String(Math.round(r.height))); }).observe(stageEl);
  }
  const night = $(".ps-night", narrow);
  const spot = $(".ps-spot", narrow);
  const countEl = $("#psCount");
  const liveEl = $("#psCountLive");
  // 가상 예시 값 — 실제 통계가 아니다 (화면에도 그렇게 적는다)
  const K = [5000000, 400000, 30000, 1800, 90, 6, 1];
  const LOGMAX = Math.log(K[0]);
  // 앞 두 자리만 — 「약 4,278명」보다 「약 4,300명」이 예시답다
  const fmt = (n) => { n = Math.round(n); if (n >= 100) { const q = Math.pow(10, Math.floor(Math.log10(n)) - 1); n = Math.round(n / q) * q; } return n.toLocaleString("ko-KR"); };

  // 캔버스 — 점 하나가 같은 조건의 사람 하나. 진행도가 바뀔 때만 그린다(따로 도는 루프 없음 · 화면 밖이면 미룸)
  const crowd = (function () {
    const cv = $("#psCrowd");
    if (!cv || !cv.getContext) return null;
    const ctx = cv.getContext("2d");
    const small = !matchMedia("(min-width:768px)").matches;
    const N = small ? 900 : 2000;
    // 자리와 꺼지는 순서는 고정 난수 — 새로고침해도 같은 그림. 0번이 「나」(가운데)
    // 꺼지는 순서 = 「나」에서 먼 점부터(거리 + 약간의 흔들림) — 지도 위에서 범위가 「나」 쪽으로 오그라든다
    let seed = 7;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const pts = [];
    while (pts.length < N - 1) {
      const x = rnd(), y = rnd();
      if (Math.hypot(x - 0.5, y - 0.5) < 0.05) continue;   // 「나」 둘레는 비워 둔다
      pts.push({ x, y, key: Math.hypot(x - 0.5, y - 0.5) + rnd() * 0.22 });
    }
    pts.sort((a, b) => a.key - b.key);
    pts.unshift({ x: 0.5, y: 0.5, key: 0 });

    let w = 0, h = 0, dpr = 1, nf = N, z = 1, drawn = -1, drawnZ = -1, visible = true, dirty = false, dark = false;
    function size() {
      dpr = Math.min(1.5, window.devicePixelRatio || 1);
      w = cv.clientWidth; h = cv.clientHeight;
      cv.width = Math.max(1, Math.round(w * dpr)); cv.height = Math.max(1, Math.round(h * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw();
    }
    function color(name, fb) { return getComputedStyle(cv).getPropertyValue(name).trim() || fb; }
    let ink = "#6B625B", hot = "#C2573A";
    // 점 i 의 밝기 — 남는 점 수 nf(소수) 둘레 폭 band 안에서 0.85 → 0.12 로 부드럽게. 따로 도는 루프 없이 진행도에 바로 묶는다
    function alpha(i) {
      const band = Math.max(2, nf * 0.3);
      return 0.12 + 0.73 * smooth((nf - i) / band + 0.5);
    }
    function draw() {
      if (!visible) { dirty = true; return; }   // 화면 밖이면 그리지 않고, 다시 보일 때 한 번
      dirty = false; drawn = nf; drawnZ = z;
      ctx.clearRect(0, 0, w, h);
      const r = Math.max(1.6, Math.min(w, h) / 170);
      ctx.fillStyle = ink;
      for (let i = 1; i < pts.length; i++) {
        const p = pts[i];
        const x = ((p.x - 0.5) * z + 0.5) * w, y = ((p.y - 0.5) * z + 0.5) * h;   // 지도 배율을 따라 가운데에서 퍼진다
        if (x < -r || y < -r || x > w + r || y > h + r) continue;
        ctx.globalAlpha = alpha(i);
        ctx.fillRect(x - r / 2, y - r / 2, r, r);
      }
      ctx.globalAlpha = 1;
      ctx.fillStyle = hot;
      ctx.beginPath(); ctx.arc(w / 2, h / 2, r * 3.2, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = hot; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(w / 2, h / 2, r * 7, 0, Math.PI * 2); ctx.stroke();
    }
    // 남는 점 수 = N^(log K / log Kmax) — K 를 로그 공간에서 점 개수로 옮긴다. 0.05개 · 배율 0.002 넘게 바뀔 때만 다시 그린다
    function setK(k, zoom) {
      const n = Math.max(1, Math.pow(N, Math.log(Math.max(1, k)) / LOGMAX));
      const zz = zoom || 1;
      if (Math.abs(n - drawn) < 0.05 && Math.abs(zz - drawnZ) < 0.002) return;
      nf = n; z = zz;
      draw();
    }
    function setDark(v) {
      if (v === dark) return;
      dark = v;
      ink = color(v ? "--ps-dot-dark" : "--ps-dot", ink);
      hot = color("--ps-hot", hot);
      draw();
    }
    if ("IntersectionObserver" in window) {
      new IntersectionObserver((e) => { visible = e[0].isIntersecting; if (visible && dirty) draw(); }).observe(cv);
    }
    if ("ResizeObserver" in window) new ResizeObserver(size).observe(cv); else size();
    ink = color("--ps-dot", ink); hot = color("--ps-hot", hot);
    return { setK, setDark };
  })();

  let stage = -1;
  function announce(s) {
    if (s === stage) return;
    stage = s;
    if (liveEl) liveEl.textContent = `글 ${s}편 — 예시로 약 ${fmt(K[s])}명 중 한 명`;
  }
  // 밤 막(--d)이 짙어지는 동안의 글자 대비 — 글자색은 FLIP 에서 한 번만 바뀐다(먹 → 밤 글자 · 중간색으로 흐르지 않는다).
  // 큰 글자(제목 · 숫자)는 d 0.49~0.63 에서 어느 쪽 색이든 3:1 이상이라 FLIP 0.56 이면 그대로 된다.
  // 작은 라벨(4.5:1)은 먹 글자가 d 0.50 까지 · 밤 글자가 0.62 부터라 그 사이에만 라벨 뒤에 같은 쪽 바탕(--pa)을 깐다 —
  // 종이 바탕 a 를 깔면 라벨 뒤 막 농도가 d(1-a), 밤 바탕 b 면 d+(1-d)b. 이것을 LIGHT_MAX 이하 · DARK_MIN 이상으로 맞춘다.
  const FLIP = 0.56, LIGHT_MAX = 0.48, DARK_MIN = 0.65;
  const plate = (d) => (d < FLIP ? (d > LIGHT_MAX ? 1 - LIGHT_MAX / d : 0) : (d < DARK_MIN ? (DARK_MIN - d) / (1 - d) : 0));

  // 카드 i 의 등장 구간: s ∈ [i·GAP, i·GAP + RAMP] — GAP < RAMP 라 앞 카드가 다 나오기 전에 다음이 시작한다. 마지막 카드는 s=6 에서 끝
  const RAMP = 1.8, GAP = (6 - RAMP) / 5;   // 0.84 간격 · 1.8 램프 — 늘 한두 장이 같이 움직인다
  // 카드 등장값(cs · 0~1) → 핀 · 지도 배율 · 숫자 · 점. 고정 장면(narrowScene)과 휴대폰 흐름(narrowFlow)이 같이 쓴다. 반환: 배율 z · 사람 수 k
  function narrowApply(cs, zmax = ZMAX) {
    let u = 0;                               // 나온 카드 수(소수) — 숫자 · 점이 이것을 따른다
    cs.forEach((c, i) => { u += c; setVar(posts[i], "--in", c); });
    pins.forEach((p) => setVar(p.el, "--in", cs[p.i] || 0));
    const z = 1 + (zmax - 1) * smooth(u / 6);   // 글이 쌓일수록 지도가 「나」 쪽으로 다가간다
    if (stageEl) setVar(stageEl, "--z", z);
    const i0 = Math.min(5, Math.floor(u)), f = u - i0;
    const k = Math.exp(Math.log(K[i0]) + (Math.log(K[i0 + 1]) - Math.log(K[i0])) * f);
    countEl.textContent = `약 ${fmt(k)}명`;
    announce(Math.min(6, Math.floor(u + 0.3)));
    if (window.PadoCity3D) window.PadoCity3D.set(cs, u, k);   // 3D 도시 시안(?scene=3d) — 같은 진행도로 그린다
    return { z, k };
  }
  function narrowScene(p, on) {
    if (!narrow) return;
    if (!on && M.mode() === "flow") return;   // 휴대폰 흐름 모드는 narrowFlow 가 그린다
    if (!on) {   // 정지 상태 — 다 켜진 모습
      posts.forEach((el) => setVar(el, "--in", 1));
      pins.forEach((p) => setVar(p.el, "--in", 1));
      if (stageEl) setVar(stageEl, "--z", ZMAX);
      if (night) setVar(night, "--d", 0);
      setVar(narrow, "--pa", 0);
      narrow.classList.remove("is-dark");
      countEl.textContent = `약 ${fmt(K[6])}명`;
      announce(6);
      if (crowd) { crowd.setDark(false); crowd.setK(1, ZMAX); }
      if (window.PadoCity3D) { window.PadoCity3D.setDark(false); window.PadoCity3D.set(posts.map(() => 1), 6, 1); }
      return;
    }
    // 0~6 — 카드는 앞 62% 안에 다 나온다. 뒤 38% 는 「약 1명 · 나」가 다 보이는 채로 멈춘다(읽을 시간 — 14% 였을 땐 다 나오자마자 화면이 올라갔다 · 10/14)
    const s = clamp(p / 0.62) * 6;
    const { z, k } = narrowApply(posts.map((el, i) => smooth((s - i * GAP) / RAMP)));
    const dark = smooth((p - 0.2) / 0.3) * 0.9;    // 글이 절반쯤 쌓인 뒤 어두워진다(0.5 에서 다 어두움)
    if (night) setVar(night, "--d", dark);
    setVar(narrow, "--pa", plate(dark));
    if (spot) setVar(spot, "--s", 1 - smooth((p - 0.25) / 0.4));    // 1 → 0 : 스포트라이트가 「나」로 조여 온다(0.65 에서 끝)
    narrow.classList.toggle("is-dark", dark >= FLIP);
    if (crowd) { crowd.setDark(dark >= FLIP); crowd.setK(k, z); }
    if (window.PadoCity3D) window.PadoCity3D.setDark(dark >= FLIP);
  }

  // ── 연출 B — 네 단계 점등 ───────────────────────────────────────────────
  const steps = M.track($("#steps"));
  const stepEls = $$(".ps-step", steps);
  const path = $(".ps-path", steps);   // --w 를 여기 준다 — 선(i)과 선 끝 점(b)이 같이 따른다
  const vis = $$(".ps-vis-i", steps);
  // 네 단계는 「스크롤로 문을 열고, 전환은 늘 같은 빠르기로」 — 2번(좁혀지기)처럼 스크롤 위치에 그림을 묶으면(스크러빙)
  // 빨리 내릴 때 네 번의 전환이 한꺼번에 몰려 슉 지나간다(10/14 사용자 피드백 두 번). 그래서 스크롤은 「몇 단계까지 왔나(target)」만 정하고,
  // 보이는 단계(shown)는 한 번에 한 단계씩 STEP_MS 간격으로 따라간다. 전환 자체는 CSS 가 같은 시간으로 그린다(@property --a --f --t --w).
  // 단계 i 의 문이 열리는 진행도 — 앞 52% 안에 네 단계가 다 열리고, 뒤 48% 는 네 단계가 다 보이는 채로 멈춘다
  // (한 단계씩 0.52초 늦게 따라와도 장면이 풀리기 전에 다 나온다 · 끝까지 나온 뒤 읽을 시간 — 10/14)
  // 간격 STEP_MS · 두 단계 이상 뒤처지면 STEP_CATCH 로 따라잡는다(빨리 내려도 장면이 풀리기 전에 네 단계가 다 나오게)
  // 다섯 번째 문(0.6) = 「끝」 — 네 단계가 다 나온 뒤 선이 4단계 점에서 오른쪽 끝까지 한 번에 늘어난다(다른 단계와 같은 방식 · 스크롤에 묶지 않는다)
  // 간격 STEP_MS · 두 단계 이상 뒤처지면 STEP_CATCH · 4단계 → 끝은 STEP_END(선만 늘어나 짧게) — 휠 1초 10칸으로 지나가도 풀리기 전에 끝까지
  const STEP_AT = [0, 0.14, 0.3, 0.46, 0.6], STEP_MS = 400, STEP_CATCH = 280, STEP_END = 250;
  let shown = 0, target = 0, stepTimer = 0, stepFirst = true, lastStep = -1e9;
  function applySteps(on) {
    const cur = Math.min(shown, stepEls.length);   // 보이는 단계(「끝」 단계에서도 4단계 그림 그대로)
    stepEls.forEach((el, i) => {
      const v = !on || i < cur ? 1 : 0;
      setVar(el, "--a", v);
      el.classList.toggle("reached", v === 1);
    });
    // 그림판 — 지금 단계 그림만(정지 상태는 네 장 다). 지나간 그림은 왼쪽으로, 아직인 그림은 오른쪽에서 들어온다
    vis.forEach((el, i) => {
      setVar(el, "--f", !on || i === cur - 1 ? 1 : 0);
      setVar(el, "--dir", on && i < cur - 1 ? -1 : 1);
      setVar(el, "--t", !on || i < cur ? 1 : 0);
    });
    // 선 — 보이는 마지막 단계의 점까지. 점 자리는 칸 사이 간격 때문에 i/4 가 아니라 잰 값(dotAt)
    setPath(on);
    steps.dataset.shown = String(shown);
    steps.dataset.target = String(target);
  }
  function stepTick() {
    stepTimer = 0;
    if (shown === target) return;
    shown += shown < target ? 1 : -1;
    lastStep = performance.now();
    applySteps(true);
    if (shown !== target) stepTimer = setTimeout(stepTick, gap());
  }
  const gap = () => (shown === STEP_AT.length - 1 && target > shown ? STEP_END : Math.abs(target - shown) >= 2 ? STEP_CATCH : STEP_MS);
  // 다음 단계는 마지막 전환에서 STEP_MS 가 지난 뒤에 — 관성 보간으로 목표가 프레임마다 하나씩 올라와도 몰려 넘어가지 않게
  function scheduleStep() {
    if (stepTimer || shown === target) return;
    stepTimer = setTimeout(stepTick, Math.max(0, gap() - (performance.now() - lastStep)));
  }
  // 선 — 보이는 마지막 단계의 점까지(점 자리는 칸 사이 간격 때문에 i/4 가 아니라 잰 값 dotAt).
  // 네 단계가 다 보인 뒤 「끝」 단계에서 오른쪽 끝까지 — 끝에 닿은 뒤 멈춤 구간을 지나 장면이 넘어간다(10/14)
  function setPath(on) {
    if (!path) return;
    const n = stepEls.length;
    let v = 1;
    if (on) v = shown <= 1 ? 0 : shown <= n ? dotAt[shown - 1] : 1;   // 「끝」 단계(n + 1) = 오른쪽 끝
    setVar(path, "--w", v);
  }
  function stepsScene(w, on) {
    if (!steps) return;
    if (!on && M.mode() === "flow") { clearTimeout(stepTimer); stepTimer = 0; stepFirst = true; return; }   // 휴대폰은 stepsFlow
    if (!on) { clearTimeout(stepTimer); stepTimer = 0; shown = target = STEP_AT.length; stepFirst = true; applySteps(false); return; }
    let t = 0;
    STEP_AT.forEach((at, i) => { if (w >= at) t = i + 1; });
    if (t === target && !stepFirst) return;
    target = t;
    // 처음 그릴 때(새로고침 · 정지 → 움직임)는 그 자리 모습으로 바로 — 그 뒤로는 한 단계씩
    if (stepFirst) { stepFirst = false; shown = target; applySteps(true); return; }
    steps.dataset.target = String(target);
    scheduleStep();
  }
  // 점 i 의 가로 자리(선 길이 비율) — 크기가 바뀔 때만 잰다(프레임마다 레이아웃을 읽지 않는다)
  let dotAt = [0, 0.25, 0.5, 0.75];
  M.onRefresh(() => {
    const track = path && path.getBoundingClientRect();
    if (!track || !track.width) return;
    dotAt = stepEls.map((el) => { const d = el.querySelector(".dot"); const r = (d || el).getBoundingClientRect(); return clamp((r.left + r.width / 2 - track.left) / track.width); });
  });

  // ── 연출 C — 읽기 진행 막대 · 소개 순서 · 어두운 구간 ─────────────────────
  const bar = $("#psBar");
  const cue = $("#psCue");
  const CUE_GONE = 40;   // 이만큼(px) 내리면 스크롤 신호를 거둔다 — 이미 내릴 줄 안다
  let cueGone = null;
  const secs = $$("[data-ps-section]").map((el) => M.track(el));
  const mapLinks = new Map($$(".ps-map a[data-map]").map((a) => [a.dataset.map, a]));
  // 어두운 정도 — 섹션 위치로 만든 키프레임. 같은 값 두 번 = 멈춤 구간
  const tl = M.createTimeline(() => {
    if (!narrow || !steps) return [];
    const a = M.top(narrow), b = M.release(narrow);
    return [
      { at: a + (b - a) * 0.2, v: { night: 0 } },
      { at: a + (b - a) * 0.5, v: { night: 0.9 } },
      { at: b, v: { night: 0.9 } },
      { at: M.top(steps) - M.view.vh * 0.3, v: { night: 0 } },
    ];
  });
  let darkOn = false, current = null;
  function chromeScene(y, on) {
    if (bar) setVar(bar, "--p", clamp(y / M.view.max));
    if (cue && (y > CUE_GONE) !== cueGone) { cueGone = y > CUE_GONE; cue.classList.toggle("is-gone", cueGone); }
    const night = on ? (tl.sample(y).night || 0) : 0;
    if ((night > 0.5) !== darkOn) { darkOn = night > 0.5; root.classList.toggle("dark-chapter", darkOn); }
    let cur = secs[0];
    for (const s of secs) if (M.top(s) - y <= M.view.vh * 0.1) cur = s;
    secs.forEach((s) => {
      const a = mapLinks.get(s.id);
      if (!a) return;
      const u = a.querySelector("i");
      const span = Math.max(1, on && s.classList.contains("ps-pin") ? M.release(s) - M.top(s) : M.height(s));
      if (u) setVar(u, "--p", clamp((y - M.top(s) + M.view.vh * 0.1) / span));
    });
    if (cur !== current) {
      current = cur;
      mapLinks.forEach((a, id) => { if (id === cur.id) a.setAttribute("aria-current", "step"); else a.removeAttribute("aria-current"); });
    }
  }

  // ── 휴대폰 흐름 모드(html.ps-flow · 폭 767 이하) — 장면을 고정하지 않는다. 지도 · 숫자는 위에 붙어 있고(CSS sticky),
  //    카드가 화면 중간 아래(66%)에서 올라올 때마다 하나씩 나오며 숫자가 줄고 핀이 꽂힌다. 네 단계는 단계마다 화면에 들면 한 번 재생된다.
  //    요소 자리는 크기가 바뀔 때만 잰 값(M.track · M.top)이라 프레임마다 레이아웃을 읽지 않는다
  posts.forEach((el) => M.track(el));
  stepEls.forEach((el) => M.track(el));
  function narrowFlow(y, view) {
    if (!narrow) return;
    if (night) setVar(night, "--d", 0);
    setVar(narrow, "--pa", 0);
    narrow.classList.remove("is-dark");
    // 카드 위쪽이 화면 높이 66% 선을 지나 14% 더 올라오는 동안 나온다 — 장면에 막 들어섰을 땐 첫 카드부터(큰 숫자에서 시작)
    const at = view.vh * 0.66, span = view.vh * 0.14;
    // 휴대폰 지도는 작아서(약 230px) 끝 배율을 조금 낮춘다 — 가장자리 핀 라벨이 잘리지 않게
    const { z, k } = narrowApply(posts.map((el) => smooth((at - (M.top(el) - y)) / span)), 1.45);
    if (crowd) { crowd.setDark(false); crowd.setK(k, z); }
  }
  function stepsFlow(y, view) {
    if (!steps) return;
    stepEls.forEach((el, i) => {
      const seen = M.top(el) - y < view.vh * 0.78;          // 화면 아래 22% 위로 들어오면 한 번 재생(전환은 CSS 시간 · 위로 되돌아가도 다시 접지 않는다)
      if (seen) el.classList.add("seen");
      const on = el.classList.contains("seen") ? 1 : 0;
      setVar(el, "--a", on);
      el.classList.toggle("reached", on === 1);
      const mv = el.querySelector(".ps-vis-m");
      if (mv) setVar(mv, "--t", on);
    });
    if (path) setVar(path, "--w", 1);
  }
  M.addFlowScene(narrowFlow);
  M.addFlowScene(stepsFlow);
  M.addScene(narrowScene, narrow);   // 보간된 진행도(cur)로 그린다
  M.addScene(stepsScene, steps);
  M.addScene(chromeScene);           // 읽기 진행 막대 · 소개 순서는 실제 스크롤 위치 그대로
  M.start();
})();
