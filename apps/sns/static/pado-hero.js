/* 「파도풀이란?」 첫 화면 들판 (about.html #hero · canvas#psField) — motion-core.js 다음에 읽는다.
   점 하나가 사람 하나, 흐린 낱말이 평범한 글 속 단서다. 마우스(터치)를 따라오는 돋보기 안에서만 낱말이 또렷해지고 점이 진해진다 —
   「글 속 단서는 평소엔 안 보이지만, 찾으려는 사람에게는 보인다」.
   · 돋보기는 포인터를 관성으로 따라온다(지수 감쇠 · motion-core 와 같은 방식). 점 · 낱말은 깊이만큼 반대로 조금 밀린다(시차).
   · 포인터가 없거나(터치 기기 · 처음 연 뒤) 2.5초 넘게 가만있으면 돋보기가 빈자리를 천천히 떠돈다.
   · 글자 영역(제목 · 설명) 위에는 낱말을 두지 않고 점도 흐리게 — 본문 대비를 지킨다.
   · 정지 상태(html.no-motion — 움직임 끄기 · 동작 줄이기 · ?view=static · 낮은/좁은 화면)는 돋보기가 한자리에 멈춘 한 장면만 그린다.
   · 첫 화면이 안 보이거나 탭이 숨으면 그리기를 멈춘다. 외부 요청 없음. */
(function () {
  "use strict";
  const cv = document.getElementById("psField");
  const hero = document.getElementById("hero");
  if (!cv || !hero || !cv.getContext) return;
  const ctx = cv.getContext("2d");
  const root = document.documentElement;
  const tryEl = document.getElementById("psTry");

  // 가상 예시 낱말 — 아래 장면(좁혀지기)의 글과 같은 이야기
  const WORDS = ["서른여덟", "버스 기사", "첫차", "구민 수영장", "화요일 저녁", "단풍 공원", "국밥집", "다리 야경",
    "3년 차", "딸기 케이크", "새벽", "집 앞", "회사 앞", "창밖", "산책길", "주문을 외우세요", "우리 동네", "퇴근길"];

  let seed = 11;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const smooth = (t) => { t = Math.min(1, Math.max(0, t)); return t * t * (3 - 2 * t); };

  let w = 0, h = 0, dpr = 1, R = 120;
  let dots = [], words = [], keep = [], home = { x: 0, y: 0 };
  let ink = "#26221F", muted = "#6B625B", accent = "#C2573A", font = "Pretendard, sans-serif";
  // 돋보기: 목표(t) · 현재(l) · 시차 기준(c = 가운데)
  let tx = 0, ty = 0, lx = 0, ly = 0, lastMove = -1e9, pointerIn = false;
  let visible = true, raf = 0, lastT = 0;

  const still = () => root.classList.contains("no-motion");

  function readColors() {
    const cs = getComputedStyle(cv);
    ink = cs.getPropertyValue("--ps-ink").trim() || ink;
    muted = cs.getPropertyValue("--ps-muted").trim() || muted;
    accent = cs.getPropertyValue("--ps-accent").trim() || accent;
    font = cs.getPropertyValue("--ps-sans").trim() || font;
  }

  // 글자 영역 — 캔버스 좌표의 사각형(여유 12px)
  function measureKeep() {
    const c = cv.getBoundingClientRect();
    keep = Array.from(hero.querySelectorAll(".ps-in > *")).map((el) => {
      const r = el.getBoundingClientRect();
      return { x0: r.left - c.left - 12, y0: r.top - c.top - 12, x1: r.right - c.left + 12, y1: r.bottom - c.top + 12 };
    }).filter((r) => r.x1 > 0 && r.y1 > 0 && r.x0 < w && r.y0 < h);
  }
  const inKeep = (x, y) => keep.some((r) => x > r.x0 && x < r.x1 && y > r.y0 && y < r.y1);
  const boxHitsKeep = (b) => keep.some((r) => b.x0 < r.x1 && b.x1 > r.x0 && b.y0 < r.y1 && b.y1 > r.y0);

  function layout() {
    dpr = Math.min(1.5, window.devicePixelRatio || 1);
    w = cv.clientWidth; h = cv.clientHeight;
    if (!w || !h) return;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    readColors();
    measureKeep();
    R = Math.max(70, Math.min(150, Math.min(w, h) * 0.17));
    seed = 11;
    const n = Math.round(Math.min(620, (w * h) / 1500));
    dots = [];
    for (let i = 0; i < n; i++) {
      const x = rnd() * w, y = rnd() * h;
      dots.push({ x, y, z: 0.35 + rnd() * 0.65, k: inKeep(x, y) ? 0.3 : 1 });
    }
    // 낱말 — 격자 칸마다 하나씩(칸 안에서 흔들어) 고르게 — 어디에 돋보기를 대도 한두 개는 걸린다.
    // 글자 영역에 걸리는 칸은 비운다. 낱말은 목록을 차례로 돌려 쓴다(칸 순서를 섞어 같은 낱말이 붙지 않게)
    ctx.font = `600 15px ${font}`;
    words = [];
    const CW = 190, CH = 74;
    const cols = Math.max(1, Math.floor(w / CW)), rows = Math.max(1, Math.floor(h / CH));
    const cells = [];
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) cells.push([c, r]);
    for (let i = cells.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); const tmp = cells[i]; cells[i] = cells[j]; cells[j] = tmp; }
    const cw = w / cols, ch = h / rows;
    let wi = 0;
    for (const [c, r] of cells) {
      const t = WORDS[wi % WORDS.length];
      const tw = ctx.measureText(t).width;
      const x = c * cw + 8 + rnd() * Math.max(1, cw - tw - 16), y = r * ch + 26 + rnd() * Math.max(1, ch - 34);
      const b = { x0: x - 10, y0: y - 22, x1: x + tw + 10, y1: y + 12 };
      if (b.x1 > w || b.y1 > h || boxHitsKeep(b)) continue;
      words.push({ t, x, y, tw, b, z: 0.5 + rnd() * 0.3 });
      wi++;
    }
    // 돋보기 첫자리 — 낱말이 가장 많이 모인 빈자리(없으면 오른쪽 아래)
    home = homeSpot();
    if (!pointerIn) { tx = lx = home.x; ty = ly = home.y; }
    draw(performance.now());
  }
  function homeSpot() {
    let best = { x: w * 0.72, y: h * 0.7 }, bestN = -1;
    for (const a of words) {
      const n = words.filter((b) => Math.hypot(b.x - a.x, b.y - a.y) < R * 0.9).length;
      if (n > bestN) { bestN = n; best = { x: a.x + a.tw / 2, y: a.y - 5 }; }
    }
    // 돋보기가 캔버스 밖으로 잘리지 않게 안쪽으로
    best.x = Math.min(w - R - 8, Math.max(R + 8, best.x));
    best.y = Math.min(h - R - 8, Math.max(R + 8, best.y));
    return best;
  }

  function draw(t) {
    if (!w || !h) return;
    ctx.clearRect(0, 0, w, h);
    // 시차 — 돋보기가 가운데에서 떨어진 만큼 깊이(z)에 비례해 반대로
    const px = (lx - w / 2) / (w / 2), py = (ly - h / 2) / (h / 2);
    const SHIFT = 14;
    const r0 = Math.max(1.5, Math.min(w, h) / 360);
    ctx.fillStyle = muted;
    for (const d of dots) {
      let x = d.x - px * SHIFT * d.z, y = d.y - py * SHIFT * d.z;
      const dx = x - lx, dy = y - ly, dist = Math.hypot(dx, dy);
      let a = 0.22 * d.z * d.k, r = r0 * (0.7 + d.z * 0.5);
      if (dist < R) {
        // 돋보기 — 가운데를 넓혀 보이게(어안): 거리 s → s^0.75
        const s = dist / R, s2 = Math.pow(s, 0.75);
        if (dist > 0.001) { x = lx + (dx / dist) * s2 * R; y = ly + (dy / dist) * s2 * R; }
        a = Math.max(a, (0.75 * (1 - s) + 0.2) * d.k);
        r *= 1.5;
        ctx.fillStyle = ink;
      } else ctx.fillStyle = muted;
      ctx.globalAlpha = a;
      ctx.fillRect(x - r / 2, y - r / 2, r, r);
    }
    // 낱말 — 바깥은 거의 안 보이게, 돋보기 안은 또렷하게 + 밑줄(위험 신호 색)
    ctx.font = `600 15px ${font}`;
    ctx.textBaseline = "alphabetic";
    let found = 0;
    for (const o of words) {
      const x = o.x - px * SHIFT * o.z, y = o.y - py * SHIFT * o.z;
      const dist = Math.hypot(x + o.tw / 2 - lx, y - 5 - ly);
      const v = smooth((R - dist) / (R * 0.45));
      ctx.globalAlpha = 0.07 + 0.88 * v;
      ctx.fillStyle = ink;
      ctx.fillText(o.t, x, y);
      if (v > 0.5) {
        found++;
        ctx.globalAlpha = v;
        ctx.fillStyle = accent;
        ctx.fillRect(x, y + 4, o.tw, 2);
      }
    }
    // 돋보기 테 + 「찾은 단서 n개」
    ctx.globalAlpha = 0.55;
    ctx.strokeStyle = ink; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(lx, ly, R, 0, Math.PI * 2); ctx.stroke();
    ctx.globalAlpha = 0.9;
    ctx.beginPath(); ctx.moveTo(lx + R * 0.707, ly + R * 0.707); ctx.lineTo(lx + R * 0.707 + 22, ly + R * 0.707 + 22); ctx.lineWidth = 2; ctx.stroke();
    // 라벨 — 테 바로 아래 가운데. 캔버스 아래로 넘치면 테 위로
    ctx.font = `600 12px ${font}`;
    ctx.fillStyle = ink;
    ctx.textAlign = "center";
    ctx.fillText(`찾은 단서 ${found}개`, lx, ly + R + 20 > h - 4 ? ly - R - 10 : ly + R + 20);
    ctx.textAlign = "start";
    ctx.globalAlpha = 1;
  }

  // 떠돌기 — 첫자리 둘레를 천천히(리사주 곡선). 글자 영역은 피하지 않는다(낱말이 없어 비칠 것이 없을 뿐)
  function wander(t) {
    return { x: home.x + Math.sin(t * 0.00031) * w * 0.12, y: home.y + Math.sin(t * 0.00047 + 1) * h * 0.1 };
  }

  function frame(t) {
    raf = 0;
    if (!visible || document.hidden || still() || !w || !h) { lastT = 0; return; }
    const dt = lastT && t - lastT < 100 ? (t - lastT) / 1000 : 1 / 60;
    lastT = t;
    if (!pointerIn || t - lastMove > 2500) { const p = wander(t); tx = p.x; ty = p.y; }
    const a = 1 - Math.exp(-dt * 7);
    lx += (tx - lx) * a; ly += (ty - ly) * a;
    draw(t);
    raf = requestAnimationFrame(frame);   // 떠돌기가 있어 늘 움직인다 — 화면 밖 · 탭 숨김 · 정지 상태에서만 멈춘다
  }
  function kick() { if (!raf && visible && w && h && !document.hidden && !still()) raf = requestAnimationFrame(frame); }

  function setStill() {
    const s = still();
    if (tryEl) tryEl.hidden = s;
    if (s) { lx = tx = home.x; ly = ty = home.y; draw(0); } else kick();
  }

  hero.addEventListener("pointermove", (e) => {
    if (still()) return;
    const c = cv.getBoundingClientRect();
    tx = e.clientX - c.left; ty = e.clientY - c.top;
    pointerIn = true; lastMove = performance.now();
    kick();
  }, { passive: true });
  hero.addEventListener("pointerleave", () => { pointerIn = false; });
  document.addEventListener("visibilitychange", kick);
  document.addEventListener("padomotion", () => { requestAnimationFrame(() => { layout(); setStill(); }); });
  if ("IntersectionObserver" in window) {
    // 아래 끝이 화면 위에 딱 닿으면 isIntersecting 은 true · 비율은 0 이다 — 비율로 본다 (Codex 10/14)
    new IntersectionObserver((e) => { visible = e[0].intersectionRatio > 0; kick(); }, { threshold: [0, 0.01] }).observe(hero);
  }
  if ("ResizeObserver" in window) new ResizeObserver(() => { layout(); setStill(); }).observe(cv);
  // 글꼴이 늦게 들어오면 낱말 폭 · 글자 영역이 바뀐다 — 다시 잰다
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { layout(); setStill(); });
  layout(); setStill();
  // 측정용 — 돋보기 현재 · 목표 자리와 그리기 루프가 도는지 (check_motion 이 읽는다)
  window.PadoHero = { probe: () => ({ lx, ly, tx, ty, running: !!raf, words: words.length, dots: dots.length }) };
})();
