/* 「파도풀이란?」 02 좁혀지기 — 3D 도시 (기본 · ?scene=flat 이면 예전 평면 지도).
   평면 지도(.ps-mapbg) · 점 캔버스(#psCrowd) · DOM 핀(.ps-pins) · 스포트라이트 대신, 같은 무대(.ps-stage)에 캔버스 하나로 가상 동네를 위에서 내려다본다.
   평면 지도는 지우지 않고 대체 화면으로 둔다 — 스크립트가 안 돌거나 캔버스를 못 쓰면 html.ps-3d 가 안 붙어 평면 지도가 그대로 보인다.
   외부 라이브러리 없음 — 원근 투영 · 상자 건물 · 먼 것부터 그리기(painter) 만 직접 한다. 따로 도는 루프 없이 pado-scene.js 가 진행도를 줄 때만 그린다.
   글이 쌓일수록(u 0 → 6) 카메라가 높고 넓은 시점에서 「나」의 집 쪽으로 내려가며 천천히 돈다 · 그 글이 가리키는 곳에 핀이 선다 ·
   조건에 맞는 사람(거리의 점)이 「나」에서 먼 것부터 꺼진다. 지도 · 사람 · 숫자는 모두 가상 예시다. */
(function () {
  "use strict";
  if (new URLSearchParams(location.search).get("scene") === "flat") return;
  const root = document.documentElement;
  const stage = document.querySelector("#narrow .ps-stage");
  if (!stage) return;
  const cv = document.createElement("canvas");
  const ctx = cv.getContext && cv.getContext("2d");
  if (!ctx) return;   // 캔버스를 못 쓰면 평면 지도 그대로
  cv.className = "ps-city";
  cv.setAttribute("aria-hidden", "true");
  stage.appendChild(cv);
  root.classList.add("ps-3d");

  // ── 세계 — 지도 좌표(0~100, about.html 의 평면 지도와 같은 자리) → 세계 x · z (−1~1). y 는 위 ──
  const W = (p) => (p - 50) / 50;
  let seed = 11;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);

  const RIVER = [[-8, 78], [8, 73], [20, 72], [32, 78], [42, 80], [54, 77], [66, 72], [80, 66], [96, 64], [108, 64]].map(([x, y]) => [W(x), W(y)]);
  const ROADS = [
    [[-5, 40], [20, 42], [40, 39], [60, 36], [80, 37], [105, 40]],
    [[45, -5], [47, 20], [44, 45], [41, 62], [44, 85], [47, 105]],
    [[-5, 6], [42, 52]],
  ].map((l) => l.map(([x, y]) => [W(x), W(y)]));
  const BRIDGE = [[W(59.5), W(63)], [W(63), W(83)]];
  const PARK = [[13, 13], [34, 11], [37, 29], [17, 33]].map(([x, y]) => [W(x), W(y)]);
  // 핀 — about.html 의 .ps-pinm 과 같은 자리 · 같은 카드 번호
  const PINS = [[0, 28, 25, "공원"], [2, 74, 30, "차고지"], [3, 29, 54, "수영장"], [4, 65, 44, "국밥집"], [5, 61, 73, "다리"]]
    .map(([i, x, y, name]) => ({ i, x: W(x), z: W(y), name }));

  function segDist(px, pz, a, b) {
    const dx = b[0] - a[0], dz = b[1] - a[1];
    const t = Math.max(0, Math.min(1, ((px - a[0]) * dx + (pz - a[1]) * dz) / (dx * dx + dz * dz || 1)));
    return Math.hypot(px - a[0] - t * dx, pz - a[1] - t * dz);
  }
  const lineDist = (px, pz, l) => { let d = 9; for (let i = 1; i < l.length; i++) d = Math.min(d, segDist(px, pz, l[i - 1], l[i])); return d; };
  function inPoly(px, pz, poly) {
    let c = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, zi] = poly[i], [xj, zj] = poly[j];
      if ((zi > pz) !== (zj > pz) && px < ((xj - xi) * (pz - zi)) / (zj - zi) + xi) c = !c;
    }
    return c;
  }
  const open = (x, z, pad) => lineDist(x, z, RIVER) > 0.11 + pad && ROADS.every((l) => lineDist(x, z, l) > 0.035 + pad) && !inPoly(x, z, PARK);

  // 건물 — 격자 칸마다 상자 하나(강 · 큰길 · 공원은 비운다). 가운데 「나」의 집은 따로
  const CELL = 0.1;
  const blds = [];
  for (let gx = -1; gx < 1 - 1e-6; gx += CELL) {
    for (let gz = -1; gz < 1 - 1e-6; gz += CELL) {
      const cx = gx + CELL / 2, cz = gz + CELL / 2;
      if (Math.hypot(cx, cz) < 0.1) continue;   // 「나」의 집 둘레는 마당으로 비운다
      if (!open(cx, cz, 0.02)) continue;
      const s = CELL * (0.55 + rnd() * 0.2);
      const far = Math.hypot(cx, cz);
      const h = 0.02 + Math.pow(rnd(), 2.4) * (0.03 + 0.17 * Math.min(1, far / 0.8));   // 낮은 집이 대부분 · 「나」 둘레는 낮고 바깥에 가끔 높은 건물 — 끝 장면에서 집이 안 가려지게
      blds.push({ x0: cx - s / 2, x1: cx + s / 2, z0: cz - s / 2, z1: cz + s / 2, h });
    }
  }
  const ME = { x0: -0.035, x1: 0.035, z0: -0.035, z1: 0.035, h: 0.07, me: true };
  blds.push(ME);

  // 사람 — 길 위 점. 꺼지는 순서 = 「나」에서 먼 점부터(거리 + 흔들림) · 0번이 「나」
  const small = !matchMedia("(min-width:768px)").matches;
  const N = small ? 700 : 1500;
  const ppl = [];
  while (ppl.length < N - 1) {
    const x = rnd() * 2 - 1, z = rnd() * 2 - 1;
    if (Math.hypot(x, z) < 0.06) continue;
    if (lineDist(x, z, RIVER) < 0.09) continue;
    ppl.push({ x, z, key: Math.hypot(x, z) + rnd() * 0.35 });
  }
  ppl.sort((a, b) => a.key - b.key);
  const LOGMAX = Math.log(5000000);

  // ── 상태 · 색 ──
  let w = 0, h = 0, dpr = 1, visible = true, dirty = false;
  let U = 0, K = 5000000, CS = [0, 0, 0, 0, 0, 0], dark = false;
  const stats = { n: 0, out: [] };   // 검사용(probe) — 그린 횟수 · 무대 밖으로 잘린 이름표
  // 카메라는 진행도(U)를 바로 쓰지 않고 따로 천천히 따라간다(camU) — 휠 한 칸마다 카메라가 크게 움직였다 서는 「뚝뚝」을 없앤다.
  // motion-core 보간(K 9 · 약 0.35초에 수렴)은 평면 지도엔 충분하지만, 3D 는 한 칸에 시점이 크게 바뀌어 섰다 가는 게 보인다
  let camU = 0, camLast = 0, camRaf = 0;
  const CAM_K = 2.6;   // 시간 상수 약 0.38초 — 칸 사이 간격(0.1~0.2초)보다 길어 칸들이 한 번의 미끄러짐으로 이어진다
  const css = (n, fb) => getComputedStyle(stage).getPropertyValue(n).trim() || fb;
  let C = {};
  function palette() {
    const ink = css("--ps-ink", "#26221F"), accent = css("--ps-accent", "#C2573A");
    C = dark
      ? { top: "#4A4440", side1: "#37322F", side2: "#2D2927", line: "rgba(247,242,234,.16)", ground: "rgba(247,242,234,.05)",
          road: "rgba(247,242,234,.16)", river: "rgba(120,150,170,.18)", park: "rgba(247,242,234,.06)", dot: "rgba(247,242,234,.85)",
          hot: accent, label: "#F7F2EA", labelBg: "#2C2826", labelLine: "rgba(247,242,234,.25)" }
      : { top: "#FBF8F3", side1: "#E6DDD0", side2: "#D8CCBC", line: "rgba(38,34,31,.22)", ground: "rgba(38,34,31,.025)",
          road: "rgba(38,34,31,.16)", river: "rgba(70,110,140,.14)", park: "rgba(38,34,31,.05)", dot: css("--ps-muted", "#6B625B"),
          hot: accent, label: ink, labelBg: css("--ps-paper", "#F7F2EA"), labelLine: "rgba(38,34,31,.18)" };
  }

  // ── 카메라 ── u 0: 높고 넓게 · 6: 「나」의 집 가까이 비스듬히. yaw 는 천천히 돈다
  const sm = (t) => { t = Math.max(0, Math.min(1, t)); return t * t * (3 - 2 * t); };
  let cam = null;
  function camera() {
    const t = sm(camU / 6);
    const yaw = -0.55 + t * 0.75;
    const pitch = 1.12 - t * 0.3;              // 약 64° → 47°
    const dist = 3.3 - t * 1.5;
    const ty = 0.02 * t;
    const cx = dist * Math.cos(pitch) * Math.sin(yaw), cy = dist * Math.sin(pitch) + ty, cz = dist * Math.cos(pitch) * Math.cos(yaw);
    let fx = -cx, fy = ty - cy, fz = -cz;
    const fl = Math.hypot(fx, fy, fz); fx /= fl; fy /= fl; fz /= fl;
    let rx = -fz, rz = fx;                      // f × 위(0,1,0)
    const rl = Math.hypot(rx, rz); rx /= rl; rz /= rl;
    const ux = -rz * fy, uy = rz * fx - rx * fz, uz = rx * fy;   // r × f
    const F = (Math.min(w, h) / 2) / Math.tan((40 * Math.PI) / 360);
    cam = { cx, cy, cz, fx, fy, fz, rx, rz, ux, uy, uz, F };
  }
  // 세계 → 화면. 반환 [x, y, 깊이] · 카메라 뒤면 null
  function P(x, y, z) {
    const dx = x - cam.cx, dy = y - cam.cy, dz = z - cam.cz;
    const d = dx * cam.fx + dy * cam.fy + dz * cam.fz;
    if (d < 0.05) return null;
    const sx = dx * cam.rx + dz * cam.rz, sy = dx * cam.ux + dy * cam.uy + dz * cam.uz;
    return [w / 2 + (sx / d) * cam.F, h * 0.54 - (sy / d) * cam.F, d];
  }

  function poly(pts, fill, stroke) {
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
    ctx.closePath();
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.strokeStyle = stroke; ctx.stroke(); }
  }
  function groundLine(l, width, color) {
    ctx.beginPath();
    let started = false;
    for (const [x, z] of l) {
      const p = P(x, 0, z);
      if (!p) continue;
      started ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
      started = true;
    }
    const mid = P(0, 0, 0);
    ctx.lineWidth = Math.max(1, (width * cam.F) / (mid ? mid[2] : 2));
    ctx.strokeStyle = color; ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.stroke();
  }

  function drawBuilding(b) {
    const { x0, x1, z0, z1 } = b, y = b.h;
    const top = [P(x0, y, z0), P(x1, y, z0), P(x1, y, z1), P(x0, y, z1)];
    if (top.some((p) => !p)) return;
    const hot = b.me;
    const sides = [
      { n: [0, -1], q: [[x0, z0], [x1, z0]] }, { n: [1, 0], q: [[x1, z0], [x1, z1]] },
      { n: [0, 1], q: [[x1, z1], [x0, z1]] }, { n: [-1, 0], q: [[x0, z1], [x0, z0]] },
    ];
    const mx = (x0 + x1) / 2, mz = (z0 + z1) / 2;
    ctx.lineWidth = 1;
    for (const s of sides) {
      const ex = mx + s.n[0] * (x1 - x0) / 2, ez = mz + s.n[1] * (z1 - z0) / 2;
      if ((cam.cx - ex) * s.n[0] + (cam.cz - ez) * s.n[1] <= 0) continue;   // 등 돌린 면
      const [a, c] = s.q;
      const q = [P(a[0], 0, a[1]), P(c[0], 0, c[1]), P(c[0], y, c[1]), P(a[0], y, a[1])];
      if (q.some((p) => !p)) continue;
      const lit = s.n[0] !== 0 ? C.side1 : C.side2;
      poly(q, hot ? (s.n[0] !== 0 ? "#B44D33" : "#9C4029") : lit, hot ? null : C.line);
    }
    poly(top, hot ? C.hot : C.top, hot ? null : C.line);
  }

  function draw() {
    if (!visible) { dirty = true; return; }
    dirty = false;
    if (!w || !h) return;
    stats.n++; stats.out = [];
    camera();
    ctx.clearRect(0, 0, w, h);

    // 바닥 — 동네 판 · 공원 · 강 · 큰길 · 다리
    const g = [P(-1.05, 0, -1.05), P(1.05, 0, -1.05), P(1.05, 0, 1.05), P(-1.05, 0, 1.05)];
    if (g.every(Boolean)) poly(g, C.ground, C.labelLine);
    const pk = PARK.map(([x, z]) => P(x, 0, z));
    if (pk.every(Boolean)) poly(pk, C.park, null);
    groundLine(RIVER, 0.13, C.river);
    ROADS.forEach((l) => groundLine(l, 0.022, C.road));
    groundLine(BRIDGE, 0.016, C.line);

    // 「나」 둘레 고리
    ctx.beginPath();
    for (let i = 0; i <= 48; i++) {
      const a = (i / 48) * Math.PI * 2, p = P(Math.cos(a) * 0.12, 0.001, Math.sin(a) * 0.12);
      if (!p) continue;
      i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
    }
    ctx.strokeStyle = C.hot; ctx.lineWidth = 1.5; ctx.globalAlpha = 0.25 + 0.6 * sm(U / 6); ctx.stroke(); ctx.globalAlpha = 1;

    // 사람 · 건물을 먼 것부터 — 점은 건물 뒤로 가려진다
    const nf = Math.max(1, Math.pow(N, Math.log(Math.max(1, K)) / LOGMAX));
    const band = Math.max(2, nf * 0.3);
    const items = [];
    for (let i = 0; i < ppl.length; i++) {
      const a = 0.08 + 0.8 * sm((nf - (i + 1)) / band + 0.5);
      if (a < 0.085) continue;
      const p = P(ppl[i].x, 0.004, ppl[i].z);
      if (!p || p[0] < -4 || p[1] < -4 || p[0] > w + 4 || p[1] > h + 4) continue;
      items.push({ d: p[2], dot: p, a });
    }
    for (const b of blds) {
      const c = P((b.x0 + b.x1) / 2, b.h / 2, (b.z0 + b.z1) / 2);
      if (c) items.push({ d: c[2] + 0.02, b });
    }
    items.sort((p, q) => q.d - p.d);
    for (const it of items) {
      if (it.b) { ctx.globalAlpha = 1; drawBuilding(it.b); continue; }
      const r = Math.max(1.3, (0.011 * cam.F) / it.dot[2]);
      ctx.globalAlpha = it.a; ctx.fillStyle = C.dot;
      ctx.fillRect(it.dot[0] - r / 2, it.dot[1] - r, r, r * 1.6);
    }
    ctx.globalAlpha = 1;

    // 핀 — 그 글이 나오면 땅에서 솟는다. 막대 + 동그라미 + 이름표(항상 맨 위)
    const fs = Math.round(Math.max(10, Math.min(13, w / 46)));
    ctx.font = `700 ${fs}px ${css("--ps-sans", "sans-serif")}`;
    ctx.textBaseline = "middle";
    for (const pin of PINS) {
      const v = sm(CS[pin.i] || 0);
      if (v <= 0.01) continue;
      const H = 0.26 * v;
      const a = P(pin.x, 0, pin.z), b = P(pin.x, H, pin.z);
      if (!a || !b) continue;
      ctx.globalAlpha = v;
      ctx.strokeStyle = C.hot; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      ctx.fillStyle = C.hot;
      ctx.beginPath(); ctx.ellipse(a[0], a[1], 5, 2.2, 0, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.arc(b[0], b[1], 4, 0, Math.PI * 2); ctx.fill();
      const tw = ctx.measureText(pin.name).width + 14, th = fs + 8;
      let lx = b[0] + 7, ly = b[1] - th / 2;
      if (lx + tw > w - 4) lx = b[0] - 7 - tw;
      if (v > 0.9 && (lx < 0 || ly < 0 || lx + tw > w || ly + th > h)) stats.out.push(pin.name);
      ctx.fillStyle = C.labelBg; ctx.strokeStyle = C.labelLine; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.roundRect ? ctx.roundRect(lx, ly, tw, th, th / 2) : ctx.rect(lx, ly, tw, th); ctx.fill(); ctx.stroke();
      ctx.fillStyle = C.label; ctx.fillText(pin.name, lx + 7, b[1] + 0.5);
    }
    // 「나」 빛기둥 — 글이 쌓일수록 진해진다(마지막엔 이 집 하나만 남는다)
    const bb = P(0, ME.h, 0), bt = P(0, ME.h + 0.5, 0);
    if (bb && bt) {
      const gr = ctx.createLinearGradient(bb[0], bb[1], bt[0], bt[1]);
      gr.addColorStop(0, C.hot); gr.addColorStop(1, "rgba(194,87,58,0)");
      ctx.globalAlpha = 0.15 + 0.55 * sm((U - 2) / 4);
      ctx.strokeStyle = gr; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(bb[0], bb[1]); ctx.lineTo(bt[0], bt[1]); ctx.stroke();
      ctx.globalAlpha = 1;
    }
    // 「나」 표시
    const me = P(0, ME.h + 0.06, 0);
    if (me) {
      ctx.globalAlpha = 1;
      const tw = ctx.measureText("나").width + 14, th = fs + 8;
      ctx.fillStyle = C.hot;
      ctx.beginPath(); ctx.roundRect ? ctx.roundRect(me[0] - tw / 2, me[1] - th, tw, th, th / 2) : ctx.rect(me[0] - tw / 2, me[1] - th, tw, th); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.fillText("나", me[0], me[1] - th / 2 + 0.5); ctx.textAlign = "start";
    }
    ctx.globalAlpha = 1;
  }

  function size() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    w = cv.clientWidth; h = cv.clientHeight;
    cv.width = Math.max(1, Math.round(w * dpr)); cv.height = Math.max(1, Math.round(h * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }
  if ("IntersectionObserver" in window) new IntersectionObserver((e) => { visible = e[0].isIntersecting; if (visible && dirty) draw(); }).observe(cv);
  palette();
  if ("ResizeObserver" in window) new ResizeObserver(size).observe(cv); else size();

  function glide(t) {
    const dt = camLast ? Math.min(0.1, (t - camLast) / 1000) : 1 / 60;
    camLast = t;
    camU += (U - camU) * (1 - Math.exp(-dt * CAM_K));
    if (Math.abs(U - camU) < 0.001) camU = U;
    draw();
    camRaf = camU === U ? 0 : requestAnimationFrame(glide);
  }

  // pado-scene.js 가 부른다 — cs: 카드별 등장값(0~1) · u: 나온 카드 수(소수) · k: 조건에 맞는 사람 수(가상 예시)
  let last = "";
  window.PadoCity3D = {
    set(cs, u, k) {
      const key = cs.map((c) => c.toFixed(3)).join() + "|" + u.toFixed(3) + "|" + Math.round(k);
      if (key === last) return;
      last = key; CS = cs; U = u; K = k;
      if (root.classList.contains("no-motion") || !camLast && !camRaf && camU === 0 && u > 5.9) camU = u;   // 정지 · 처음부터 끝 모습이면 바로
      draw();
      if (!camRaf && Math.abs(U - camU) > 0.001) { camLast = 0; camRaf = requestAnimationFrame(glide); }
    },
    setDark(v) { if (v === dark) return; dark = v; palette(); draw(); },
    probe() { return { U: +U.toFixed(3), camU: +camU.toFixed(3), pins: PINS.map((p) => +(CS[p.i] || 0).toFixed(2)), out: stats.out.slice(), draws: stats.n, w, h, dark }; },
  };
})();
