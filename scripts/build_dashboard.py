#!/usr/bin/env python3
"""팀 대시보드 — 사람마다 「지금 뭘 하면 되는지」를 한 장으로.

  python scripts/build_dashboard.py > site/index.html

## 실시간이다. 스냅샷은 폴백일 뿐이다

GitHub Pages 는 정적 파일만 준다. 그런데 «페이지»는 브라우저에서 GitHub
공개 API 를 직접 부를 수 있다. 공개 저장소라 인증이 필요 없다.

  · api.github.com          인증 없이 IP 당 시간당 60회. 한 번 볼 때 2회 쓴다
  · raw.githubusercontent   제한 없음. 체크리스트 문서는 여기서 받는다

그래서 순서가 이렇다.

  ① 페이지가 열리면 «구울 때 박아둔» 데이터로 즉시 그린다 (0ms, 깜빡임 없음)
  ② 곧바로 API 를 불러 실시간으로 다시 그린다 (보통 0.3초)
  ③ API 가 막히면(시간당 60회 초과·오프라인) ① 그대로 두고
     머리말에 «스냅샷» 이라고 밝힌다

⚠️ 스냅샷을 지우면 안 된다. API 가 죽었을 때 빈 화면이 뜨고, 빈 화면은
   «할 일 없음» 으로 읽힌다. 틀린 정보보다 나쁘다.

## 무엇을 모으나

  ① 내 승인을 기다리는 PR    reviewRequests 에 내가 있는 열린 PR
  ② 내가 올렸는데 멈춘 PR     내가 쓴 PR 중 리뷰어가 없는 것
  ③ 문서 체크리스트          «dashboard» 표식이 붙은 - [ ] 항목   ← GitHub 이 못 봄
  ④ 담당 이슈                assignees 에 내가 있는 열린 이슈

③ 표식 — 이렇게 적은 블록만 읽는다

    <!-- dashboard: owner=jhyun114 -->
    - [ ] §1 candidates 를 함께 싣는 것
    - [ ] §4 offset 을 유니코드 코드포인트로

    ⚠️ 표식 없는 - [ ] 는 무시한다. 저장소의 - [ ] 대부분은
       persona-design.md 의 «작성 시 확인» 처럼 매번 다시 쓰는 템플릿이지
       누구의 남은 작업이 아니다. 전부 긁으면 121건이 뜨고 아무도 안 본다.
       owner 는 쉼표로 여럿 적을 수 있다 (owner=jhyun114,jaepaly).

## 목록이 아니라 «다음 한 걸음»을 보여준다

목록만 주면 «그래서 뭘 하라는 건지»를 사람이 다시 계산해야 한다. 맨 위에
지금 할 일 하나를 문장으로 내고, 항목마다 동사를 붙인다. 고르는 규칙은
`next_action()` 주석에 있다.

⚠️ 손으로 채우는 칸을 두지 않는다. 하나라도 수동이면 곧 낡고,
   낡은 대시보드는 없느니만 못하다.

⚠️ 이 페이지는 공개된다(PUBLIC 리포 + Pages). PR·이슈는 어차피 공개라
   문제없지만 개인 정보를 넣지 않는다. 실명 대신 역할 문자와 GitHub 계정만 쓴다.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = "jaepaly/KISIA_Project"

# 역할 문자 ↔ GitHub 계정. 근거는 .mailmap.
# ⚠️ 실명은 넣지 않는다 — 공개 페이지다.
TEAM = [
    ("A", "nuewsun"),
    ("B", "philotti"),
    ("C", "jhyun114"),
    ("D", "jaepaly"),
    ("E", "zihhhhh"),
]

DOCS_ROOT = Path("docs")
MARKER = re.compile(r"<!--\s*dashboard:\s*owner\s*=\s*([^>]+?)\s*-->")
UNCHECKED = re.compile(r"^\s*[-*]\s+\[ \]\s+(.*)$")
CHECKED = re.compile(r"^\s*[-*]\s+\[[xX]\]\s+")


def gh(args: list[str]) -> list[dict]:
    """gh CLI 를 JSON 으로 부른다. 실패하면 빈 목록 — 페이지는 그래도 뜬다."""
    try:
        r = subprocess.run(["gh", *args], capture_output=True,
                           encoding="utf-8", timeout=120)
    except Exception as e:                                    # noqa: BLE001
        print(f"::warning::gh 호출 실패 {args[:2]}: {e}", file=sys.stderr)
        return []
    if r.returncode != 0:
        print(f"::warning::gh {args[:2]} exit={r.returncode} {r.stderr[:200]}",
              file=sys.stderr)
        return []
    try:
        return json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return []


def fetch():
    # ⚠️ --state open 을 빼지 마라. GitHub 은 머지·닫힌 PR 에도 reviewRequests 를
    #    그대로 남긴다 (실측 2026-08-26). 빼면 닫힌 PR 이 «승인 대기» 로 뜬다.
    prs = gh(["pr", "list", "--repo", REPO, "--state", "open", "--limit", "100",
              "--json", "number,title,url,author,reviewRequests,isDraft,"
                        "createdAt,statusCheckRollup,latestReviews"])
    issues = gh(["issue", "list", "--repo", REPO, "--state", "open", "--limit", "100",
                 "--json", "number,title,url,assignees,updatedAt"])
    return prs, issues


def scan_checklists():
    """표식이 붙은 블록의 미완 항목만 거둔다. (항목들, 표식이 있는 파일 목록)"""
    out, files = [], []
    if not DOCS_ROOT.is_dir():
        return out, files
    for path in sorted(DOCS_ROOT.rglob("*.md")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        owners = None
        in_comment = False
        found = False
        for i, line in enumerate(lines, 1):
            # 여러 줄 주석은 통째로 건너뛴다. 표식 옆에 설명을 여러 줄로 붙이는
            # 일이 많은데, 둘째 줄부터는 <!-- 로 시작하지 않아 블록이 끊겼다.
            if in_comment:
                if "-->" in line:
                    in_comment = False
                continue
            if "<!--" in line and "-->" not in line:
                in_comment = True
                m = MARKER.search(line)
                if m:
                    owners = [o.strip() for o in m.group(1).split(",") if o.strip()]
                    found = True
                continue
            m = MARKER.search(line)
            if m:
                owners = [o.strip() for o in m.group(1).split(",") if o.strip()]
                found = True
                continue
            if owners is None:
                continue
            u = UNCHECKED.match(line)
            if u:
                out.append({"owners": owners, "text": u.group(1).strip(),
                            "file": path.as_posix(), "line": i})
                continue
            if CHECKED.match(line):
                continue
            # 한 줄짜리 주석도 안 끊는다.
            if line.lstrip().startswith("<!--"):
                continue
            # 빈 줄도 안 끊는다. 체크박스도 주석도 아닌 «내용» 줄에서 끊는다.
            if line.strip():
                owners = None
        if found:
            files.append(path.as_posix())
    return out, files


def check_kind(pr: dict) -> str:
    """필수 검사는 guard·lint 다. notify 는 디스코드 알림이라 무시한다."""
    roll = pr.get("statusCheckRollup") or []
    req = [c for c in roll if (c.get("name") or "") in ("guard", "lint")]
    if not req:
        return ""
    bad = [c for c in req if (c.get("conclusion") or c.get("status")) != "SUCCESS"]
    if any((c.get("status") or "") in ("IN_PROGRESS", "QUEUED") for c in bad):
        return "run"
    return "fail" if bad else "ok"


def bake(prs, issues, todos, todo_files) -> dict:
    """브라우저가 실시간 데이터를 못 받았을 때 쓸 폴백."""
    return {
        "repo": REPO,
        "built": int(time.time()),
        "team": [[r, lg] for r, lg in TEAM],
        "todoFiles": todo_files,
        "prs": [{
            "n": p["number"], "title": p["title"], "url": p["url"],
            "author": (p.get("author") or {}).get("login", ""),
            # ⚠️ 중복 제거. CODEOWNERS 자동 요청과 --reviewer 명시 요청이 겹치면
            #    같은 사람이 두 번 들어온다 (실측 2026-08-27, #63).
            "reviewers": sorted({r.get("login") for r in (p.get("reviewRequests") or [])
                                 if r.get("login")}),
            # ⚠️ 승인한 사람은 reviewRequests 에 남아 있을 수 있다. 요청이 둘이면
            #    승인이 하나만 소멸시키기 때문이다 (#63 에서 실제로 그랬다).
            #    그래서 «요청받았나» 만 보지 않고 «이미 승인했나» 를 함께 본다.
            "approved": sorted({r.get("author", {}).get("login")
                                for r in (p.get("latestReviews") or [])
                                if r.get("state") == "APPROVED"
                                and r.get("author", {}).get("login")}),
            "draft": bool(p.get("isDraft")),
            "created": p.get("createdAt", ""),
            "check": check_kind(p),
        } for p in prs],
        "issues": [{
            "n": i["number"], "title": i["title"], "url": i["url"],
            "assignees": [a.get("login") for a in (i.get("assignees") or [])
                          if a.get("login")],
            "updated": i.get("updatedAt", ""),
        } for i in issues],
        "todos": todos,
    }


# ── 페이지 ────────────────────────────────────────────────────────────
# 그리는 일은 전부 브라우저가 한다. 파이썬은 폴백 데이터를 박아 넣을 뿐이다.
# 그래야 «구운 화면»과 «실시간 화면»이 갈리지 않는다 — 렌더 코드가 하나다.

CSS = r"""
/* ── 토큰 ─────────────────────────────────────────────────────────
   색은 여기서만 정한다. 어두운 화면은 토큰만 바꾼다 — 규칙은 한 벌이다. */
:root{
  --bg:#faf9f7; --card:#fff; --ink:#191917; --dim:#71716c; --faint:#a3a39c;
  --line:#e8e6e1; --line-soft:#f1efeb;
  --accent:#6d4aff; --accent-ink:#5a37e8; --accent-bg:#f4f1ff;
  --red:#c0362c; --red-bg:#fdf1f0; --amber:#9a5b00; --green:#217a4b;
  --chip:#f2f0ec;
  --r:14px; --shadow:0 1px 2px rgba(24,22,18,.05);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#141417; --card:#1c1c21; --ink:#eeeef1; --dim:#9b9ba4; --faint:#6e6e78;
  --line:#2b2b33; --line-soft:#232329;
  --accent:#a78bff; --accent-ink:#c4b2ff; --accent-bg:#221d33;
  --red:#ff8a7e; --red-bg:#2a1c1b; --amber:#e0a54a; --green:#63cd92;
  --chip:#26262e; --shadow:none;
}}
:root[data-theme="dark"]{
  --bg:#141417; --card:#1c1c21; --ink:#eeeef1; --dim:#9b9ba4; --faint:#6e6e78;
  --line:#2b2b33; --line-soft:#232329;
  --accent:#a78bff; --accent-ink:#c4b2ff; --accent-bg:#221d33;
  --red:#ff8a7e; --red-bg:#2a1c1b; --amber:#e0a54a; --green:#63cd92;
  --chip:#26262e; --shadow:none;
}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Pretendard",
       "Malgun Gothic","Apple SD Gothic Neo",sans-serif;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
.wrap{max-width:760px;margin:0 auto;padding:22px 20px 72px}
a{color:inherit;text-decoration:none}

/* ── 머리말 ───────────────────────────────────────────────────── */
h1{font-size:19px;line-height:1.3;margin:0 0 7px;letter-spacing:-.015em;
  font-weight:700}
.sub{color:var(--dim);font-size:12.5px;display:flex;flex-wrap:wrap;
  gap:6px 9px;align-items:center}
.sub .who-team{color:var(--faint)}
.dot{width:6px;height:6px;border-radius:50%;background:var(--green);
  display:inline-block;margin-right:6px;vertical-align:1px;
  box-shadow:0 0 0 3px color-mix(in srgb,var(--green) 18%,transparent)}
.dot.snap{background:var(--amber);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--amber) 18%,transparent)}
button.rf{font:inherit;font-size:12px;cursor:pointer;border:1px solid var(--line);
  background:var(--card);color:var(--dim);border-radius:7px;
  padding:4px 10px;min-height:28px;transition:.12s}
button.rf:hover{border-color:var(--accent);color:var(--accent-ink)}

/* 팀 전체 한 줄 */
.strip{margin:-16px 0 26px;font-size:12px;color:var(--faint);
  display:flex;flex-wrap:wrap;gap:2px 13px;padding:0 2px}
.strip b{color:var(--dim);font-weight:650;font-variant-numeric:tabular-nums}

/* ── 나 — 탭 바를 없앴다. 남의 건수가 나란히 있으면 그게 점수판이다. ── */
.who-line{display:flex;align-items:center;gap:9px;margin:16px 0 20px;
  padding:9px 13px;background:var(--card);border:1px solid var(--line);
  border-radius:11px;box-shadow:var(--shadow)}
.who-line .me{display:inline-flex;align-items:center;gap:6px;flex:1;min-width:0}
.who-line .role{font-weight:750;font-size:15px;color:var(--ink)}
.who-line .who{color:var(--faint);font-size:12.5px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.who-line .rf{flex:0 0 auto}

/* 처음 왔을 때 고르는 화면 */
.pick .picks{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.pick .picks button{flex:1 1 auto;min-width:104px;min-height:52px;
  display:inline-flex;align-items:center;justify-content:center;gap:7px;
  font:inherit;cursor:pointer;border-radius:11px;
  border:1px solid var(--line);background:var(--bg);color:var(--ink);
  transition:.14s}
.pick .picks button:hover{border-color:var(--accent);background:var(--accent-bg)}
.pick .picks .role{font-weight:750;font-size:16px}
.pick .picks .who{color:var(--faint);font-size:12.5px}
.pick .why b{color:var(--ink);font-weight:650}

/* ── 지금 할 일 ───────────────────────────────────────────────── */
.now{background:var(--accent-bg);border:1px solid var(--accent);
  border-color:color-mix(in srgb,var(--accent) 32%,transparent);
  border-radius:var(--r);padding:16px 17px 17px;margin-bottom:28px}
.now .lab{font-size:11px;font-weight:750;letter-spacing:.08em;
  color:var(--accent-ink);margin-bottom:7px;text-transform:uppercase}
.now .act{font-size:17.5px;font-weight:700;line-height:1.4;
  letter-spacing:-.012em;margin-bottom:6px}
.now .ttl{font-size:13.5px;color:var(--ink);opacity:.72;margin-bottom:5px;
  line-height:1.5}
.now .why{font-size:12.5px;color:var(--dim);line-height:1.55}
.now a.go{display:inline-flex;align-items:center;min-height:40px;
  margin-top:13px;font-size:13.5px;font-weight:650;
  color:#fff;background:var(--accent);border-radius:9px;padding:0 16px}
.now a.go:hover{filter:brightness(1.08)}
.now.calm{background:var(--card);border-color:var(--line);box-shadow:var(--shadow)}
.now.calm .lab{color:var(--green)}
.now.calm .act{font-weight:600;font-size:16px}

/* ── 묶음 ─────────────────────────────────────────────────────── */
h2{font-size:12.5px;margin:26px 0 9px;color:var(--dim);font-weight:650;
  letter-spacing:.005em;display:flex;align-items:center;gap:7px}
h2 .c{font-variant-numeric:tabular-nums;font-size:11.5px;font-weight:650;
  min-width:18px;height:18px;line-height:18px;text-align:center;
  border-radius:999px;background:var(--chip);color:var(--dim)}
h2::after{content:"";flex:1;height:1px;background:var(--line-soft)}

ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:7px}
li{background:var(--card);border:1px solid var(--line);border-radius:12px;
  box-shadow:var(--shadow);transition:.12s}
li:hover{border-color:var(--accent);
  border-color:color-mix(in srgb,var(--accent) 45%,var(--line))}
li>a{display:block;padding:12px 14px 4px}         /* 카드 전체가 눌린다 */
li .meta{padding:0 14px 11px}
li.hot{border-left:3px solid var(--red)}
li.warm{border-left:3px solid var(--amber)}
li.good{border-left:3px solid var(--green)}

.num{color:var(--faint);font-variant-numeric:tabular-nums;margin-right:7px;
  font-size:13.5px;font-weight:600}
.t{font-weight:500;line-height:1.5}
li>a:hover .t{text-decoration:underline;text-underline-offset:2px}
.do{display:block;margin-top:7px;font-size:12.5px;font-weight:650;
  color:var(--accent-ink)}
.meta{margin-top:7px;font-size:12px;color:var(--dim);
  display:flex;flex-wrap:wrap;gap:4px 9px;align-items:center}
.chip{background:var(--chip);border-radius:6px;padding:2px 8px;font-size:11.5px;
  font-weight:500}
.ok{color:var(--green);font-weight:600} .fail{color:var(--red);font-weight:600}
.warnc{color:var(--amber);font-weight:600}
.empty{color:var(--faint);font-size:13px;padding:2px 0 4px}
.todo .t{font-weight:450}
.t code{background:var(--chip);border-radius:5px;padding:1px 5px;font-size:12.5px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.t strong{font-weight:700}
.src{font-size:11.5px;color:var(--faint);font-family:ui-monospace,SFMono-Regular,
  Menlo,Consolas,monospace;word-break:break-all}

footer{margin-top:46px;padding-top:18px;border-top:1px solid var(--line);
  color:var(--faint);font-size:12px;line-height:1.65}
footer a{text-decoration:underline;text-underline-offset:2px}
footer p{margin:7px 0}
footer code{background:var(--chip);border-radius:4px;padding:1px 4px;font-size:11px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}

/* ── 모바일 ───────────────────────────────────────────────────── */
@media(max-width:600px){
  .wrap{padding:18px 15px 56px}
  .pick .picks button{min-width:0;flex:1 1 28%}
  h1{font-size:17.5px}
  .now{padding:15px 15px 16px}
  .now .act{font-size:16.5px}
  li>a{padding:11px 13px 4px}
  li .meta{padding:0 13px 11px}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = r"""
const R = DATA.repo;
const ROLE = {}; DATA.team.forEach(([r,l]) => ROLE[l] = r);
const CHECK = {}; DATA.prs.forEach(p => { if (p.check) CHECK[p.n] = p.check; });
// 구울 때 박아둔 승인자. 실시간 API(pulls)는 리뷰를 안 주므로 이걸 쓴다.
const APPROVED = {}; DATA.prs.forEach(p => { APPROVED[p.n] = p.approved || []; });
const didApprove = (n, l) => (APPROVED[n] || []).includes(l);
let live = false;

const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

// ⚠️ escape 를 먼저 하고 태그를 넣는다. 순서를 바꾸면 문서에 <script> 를
//    적은 사람이 이 페이지에 스크립트를 심을 수 있다.
const md = s => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>")
                      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

const days = iso => {
  const t = Date.parse(iso);
  return t ? Math.max(0, Math.floor((Date.now() - t) / 86400000)) : 0;
};

/* ── 사람별로 나눈다 ─────────────────────────────────────────────── */
function split(login) {
  // 내가 올린 PR 을 셋으로 쪼갠다. «내 차례»인 것과 «남을 기다리는 것»은 다르다.
  //   broken  검사가 깨졌다     → 내가 고쳐야 한다
  //   ready   승인을 받았다     → 머지만 하면 끝난다
  //   mine    아무도 안 보고 있다 → 리뷰어를 지정해야 한다
  //   waiting 리뷰어가 보는 중   → 내가 할 일은 없다. 상황만 알면 된다
  //
  // ⚠️ ready 와 mine 을 가르는 것이 approved 다. 리뷰가 끝나면 GitHub 이
  //    요청 목록을 비우기 때문에, 그것만 보면 «아직 아무도 안 봤다» 와
  //    «다 보고 끝났다» 가 똑같이 빈 배열로 온다 (실측 #55).
  const b = { review: [], broken: [], ready: [], mine: [], waiting: [],
              todos: [], issues: [] };
  DATA.prs.forEach(p => {
    // 이미 승인했으면 내 차례가 아니다. reviewers 에 남아 있어도 뺀다.
    if (p.reviewers.includes(login) && !didApprove(p.n, login)) { b.review.push(p); return; }
    if (didApprove(p.n, login)) return;   // 승인한 PR 은 다른 묶음에도 안 넣는다
    if (p.author !== login) return;
    if (CHECK[p.n] === "fail") b.broken.push(p);
    else if ((p.approved || []).length) b.ready.push(p);
    else if (!p.reviewers.length) b.mine.push(p);
    else b.waiting.push(p);
  });
  DATA.issues.forEach(i => { if (i.assignees.includes(login)) b.issues.push(i); });
  DATA.todos.forEach(t => { if (t.owners.includes(login)) b.todos.push(t); });
  b.review.sort((x, y) => Date.parse(x.created) - Date.parse(y.created));
  b.waiting.sort((x, y) => Date.parse(x.created) - Date.parse(y.created));
  return b;
}
// ⚠️ waiting 은 안 센다. 내 차례가 아닌데 숫자에 넣으면 «할 일 5건»으로 읽힌다.
const count = b => b.review.length + b.broken.length + b.ready.length
                 + b.mine.length + b.todos.length + b.issues.length;

/* ── 지금 할 일 하나 ──────────────────────────────────────────────
   고르는 순서. 위에 있을수록 «남을 막고 있는 것»이다.
     ① 내 승인을 기다리는 PR — 가장 오래 기다린 것부터
     ② 내가 올렸는데 리뷰어가 없는 PR — 아무도 안 보고 있다
     ③ 문서 체크리스트
     ④ 담당 이슈
   ①이 여럿이면 «가장 오래 기다린 것»을 낸다. 검사가 실패한 PR 은
   승인해도 못 머지하므로 «작성자에게 알려주세요»로 문구가 바뀐다.        */
function nextAction(b, login) {
  if (b.review.length) {
    const p = b.review[0];
    const d = days(p.created);
    const bad = CHECK[p.n] === "fail";
    const others = p.reviewers.filter(x => x !== login).length;
    let why = d >= 1 ? `${d}일째 기다리고 있습니다` : "오늘 올라왔습니다";
    if (others) why += ` · 다른 ${others}명도 같이 요청받았습니다`;
    if (bad) why += " · ⚠️ 검사가 실패해서 승인해도 머지가 안 됩니다";
    return {
      act: bad ? `#${p.n} 은 검사부터 고쳐야 합니다`
               : `#${p.n} 을 승인해 주세요`,
      sub: esc(p.title), why, url: p.url,
      go: bad ? "무엇이 실패했는지 보기" : "열어서 승인하기",
      hot: true
    };
  }
  if (b.broken.length) {
    const p = b.broken[0];
    return {
      act: `#${p.n} 의 검사가 실패했습니다`, sub: esc(p.title),
      why: "고치기 전에는 승인을 받아도 머지가 안 됩니다",
      url: p.url + "/checks", go: "무엇이 실패했는지 보기", hot: true
    };
  }
  if (b.ready.length) {
    const p = b.ready[0];
    const who = (p.approved || []).map(l => `${ROLE[l] || ""} @${l}`.trim()).join(" · ");
    return {
      act: `#${p.n} 을 머지하시면 됩니다`, sub: esc(p.title),
      why: `${esc(who)} 승인 완료 · 검사 통과 — 남은 건 머지뿐입니다`,
      url: p.url, go: "열어서 머지하기", hot: false
    };
  }
  if (b.mine.length) {
    const p = b.mine[0];
    return {
      act: `#${p.n} 에 리뷰어를 지정해 주세요`, sub: esc(p.title),
      why: "리뷰어가 없으면 아무도 이 PR 을 보지 않습니다",
      url: p.url, go: "열어서 리뷰어 지정", hot: true
    };
  }
  if (b.todos.length) {
    const t = b.todos[0];
    return {
      act: `문서에서 확인할 것이 ${b.todos.length}건 있습니다`,
      sub: md(t.text),
      why: `${esc(t.file)}:${t.line} — 확인하면 - [x] 로 바꿔 주세요`,
      url: `https://github.com/${R}/blob/main/${t.file}#L${t.line}`,
      go: "문서에서 보기", hot: false
    };
  }
  if (b.issues.length) {
    const i = b.issues[0];
    return {
      act: `맡고 계신 이슈가 ${b.issues.length}건 있습니다`,
      sub: esc(i.title), why: `#${i.n} · ${days(i.updated)}일 전 갱신`,
      url: i.url, go: "이슈 열기", hot: false
    };
  }
  if (b.waiting.length) {
    const w = b.waiting.map(p => p.reviewers).flat();
    const who = [...new Set(w)].map(l => `${ROLE[l] || ""} @${l}`.trim()).join(" · ");
    return {
      act: "지금 당신 차례인 것은 없습니다", sub: "",
      why: `올리신 PR ${b.waiting.length}건이 ${esc(who)} 을(를) 기다리는 중입니다.`,
      url: "", go: "", hot: false, calm: true
    };
  }
  return {
    act: "지금 당신 차례인 것은 없습니다", sub: "",
    why: "남이 당신을 기다리고 있는 것도 없습니다.",
    url: "", go: "", hot: false, calm: true
  };
}

/* ── 항목 ─────────────────────────────────────────────────────────── */
function prLi(p, opts) {
  const d = days(p.created), k = CHECK[p.n];
  const bits = [];
  if (k === "ok")   bits.push('<span class="ok">검사 통과</span>');
  if (k === "fail") bits.push('<span class="fail">검사 실패</span>');
  if (k === "run")  bits.push('<span class="warnc">검사 중</span>');
  if (d >= 1) bits.push(`<span class="chip">${d}일째</span>`);
  if (p.draft) bits.push('<span class="chip">Draft</span>');
  // ⚠️ 이름을 언제 보이느냐가 갈린다.
  //    names — «내가» 리뷰를 요청한 내 PR. 누구한테 물어야 하는지가 필요하고,
  //            GitHub PR 페이지에 이미 크게 떠 있다
  //    count — 내가 리뷰어인 PR 의 «공동» 리뷰어. 나한테 필요한 건
  //            «혼자가 아니다» 뿐이다. 이름을 띄우면 남의 밀린 목록이 된다
  if (opts.who === "names" && p.reviewers.length) {
    bits.push("기다리는 사람: " +
      esc(p.reviewers.map(l => `${ROLE[l] || ""} @${l}`.trim()).join(" · ")));
  } else if (opts.who === "approved" && (p.approved || []).length) {
    bits.push('<span class="ok">' +
      esc(p.approved.map(l => `${ROLE[l] || ""} @${l}`.trim()).join(" · ")) + " 승인</span>");
  } else if (opts.who === "count") {
    const n = p.reviewers.filter(l => l !== ME && !didApprove(p.n, l)).length;
    if (n) bits.push(`<span class="chip">나 말고 ${n}명도 요청받음</span>`);
  }
  const doing = k === "fail" && opts.verb === "승인해 주세요"
    ? "검사가 실패했습니다 — 작성자에게 알려주세요" : opts.verb;
  const doHtml = doing ? `<span class="do">${esc(doing)} →</span>` : "";
  return `<li class="${opts.hot && d >= 1 ? "hot" : ""}">
    <a href="${esc(p.url)}" target="_blank" rel="noopener">
      <span class="num">#${p.n}</span><span class="t">${esc(p.title)}</span>
      ${doHtml}</a>
    <div class="meta">${bits.join("")}</div></li>`;
}
const issueLi = i => `<li><a href="${esc(i.url)}" target="_blank" rel="noopener">
    <span class="num">#${i.n}</span><span class="t">${esc(i.title)}</span></a>
  <div class="meta"><span class="chip">${days(i.updated)}일 전 갱신</span></div></li>`;
const todoLi = t => `<li class="todo warm">
    <a href="https://github.com/${R}/blob/main/${esc(t.file)}#L${t.line}"
       target="_blank" rel="noopener"><span class="t">${md(t.text)}</span>
      <span class="do">확인하고 - [x] 로 바꾸기 →</span></a>
    <div class="meta"><span class="src">${esc(t.file)}:${t.line}</span></div></li>`;

const block = (title, items, fn, empty) => !items.length
  ? `<h2>${esc(title)}</h2><div class="empty">${esc(empty)}</div>`
  : `<h2>${esc(title)} <span class="c">${items.length}</span></h2>
     <ul>${items.map(fn).join("")}</ul>`;

/* ── 그린다 ───────────────────────────────────────────────────────── */
function render(login) {
  const b = split(login), a = nextAction(b, login);
  const now = `<div class="now ${a.calm ? "calm" : ""}">
      <div class="lab">${a.calm ? "확인 완료" : "지금 할 일"}</div>
      <div class="act">${a.act}</div>
      ${a.sub ? `<div class="why" style="margin-bottom:4px">${a.sub}</div>` : ""}
      <div class="why">${a.why}</div>
      ${a.url ? `<a class="go" href="${esc(a.url)}" target="_blank"
                    rel="noopener">${esc(a.go)} →</a>` : ""}
    </div>`;
  // 팀 전체 한 줄. «내 차례» 는 안 넣는다 — 탭 배지가 이미 같은 숫자를 보여준다.
  const oldest = DATA.prs.filter(p => p.reviewers.length)
    .map(p => days(p.created)).sort((x, y) => y - x)[0] || 0;
  const strip = `<div class="strip">
      <span>열린 PR <b>${DATA.prs.length}</b></span>
      <span>승인 대기 <b>${DATA.prs.filter(p => p.reviewers.length).length}</b></span>
      <span>가장 오래 기다린 것 <b>${oldest}</b>일</span></div>`;

  document.getElementById("main").innerHTML = now + strip
    + block("🔴 내 승인을 기다리는 PR", b.review,
            p => prLi(p, { verb: "승인해 주세요", hot: true, who: "count" }),
            "없습니다.")
    + block("🔴 내가 올렸는데 검사가 실패한 PR", b.broken,
            p => prLi(p, { verb: "검사를 고쳐 주세요", hot: true }), "없습니다.")
    + block("🟢 승인받았습니다 — 머지만 하면 끝", b.ready,
            p => prLi(p, { verb: "머지하세요", hot: false, who: "approved" }), "없습니다.")
    + block("🟡 내가 올렸는데 아무도 안 보고 있는 PR", b.mine,
            p => prLi(p, { verb: "리뷰어를 지정하세요", hot: false }),
            "없습니다.")
    + block("⏳ 내가 올렸고 남을 기다리는 중", b.waiting,
            p => prLi(p, { verb: "", hot: false, who: "names" }),
            "없습니다.")
    + block("📋 문서에서 확인할 것", b.todos, todoLi, "없습니다.")
    + block("📌 맡고 있는 이슈", b.issues, issueLi, "없습니다.");
}

/* ── 실시간 ───────────────────────────────────────────────────────
   공개 저장소라 인증이 필요 없다. api.github.com 은 IP 당 시간당 60회이고
   한 번 볼 때 2회 쓴다. 체크리스트 문서는 raw 라 제한이 없다.
   실패하면 구울 때 박아둔 데이터를 그대로 둔다 — 빈 화면보다 낫다.       */
const TODO_RE = /^\s*[-*]\s+\[ \]\s+(.*)$/;
const MARK_RE = /<!--\s*dashboard:\s*owner\s*=\s*([^>]+?)\s*-->/;

function parseTodos(text, file) {
  const out = [], lines = text.split("\n");
  let owners = null, inC = false;
  lines.forEach((line, idx) => {
    if (inC) { if (line.includes("-->")) inC = false; return; }
    if (line.includes("<!--") && !line.includes("-->")) {
      inC = true;
      const m = MARK_RE.exec(line);
      if (m) owners = m[1].split(",").map(s => s.trim()).filter(Boolean);
      return;
    }
    const m = MARK_RE.exec(line);
    if (m) { owners = m[1].split(",").map(s => s.trim()).filter(Boolean); return; }
    if (!owners) return;
    const u = TODO_RE.exec(line);
    if (u) { out.push({ owners, text: u[1].trim(), file, line: idx + 1 }); return; }
    if (/^\s*[-*]\s+\[[xX]\]\s+/.test(line)) return;
    if (line.trim().startsWith("<!--")) return;
    if (line.trim()) owners = null;
  });
  return out;
}

let LAST = 0;
async function refresh() {
  const badge = document.getElementById("fresh");
  badge.textContent = "불러오는 중…";
  try {
    const j = u => fetch(u, { headers: { Accept: "application/vnd.github+json" } })
      .then(r => r.ok ? r.json() : Promise.reject(r.status));
    const [pulls, items] = await Promise.all([
      j(`https://api.github.com/repos/${R}/pulls?state=open&per_page=100`),
      j(`https://api.github.com/repos/${R}/issues?state=open&per_page=100`),
    ]);
    DATA.prs = pulls.map(p => ({
      n: p.number, title: p.title, url: p.html_url,
      author: (p.user || {}).login || "",
      reviewers: (p.requested_reviewers || []).map(r => r.login),
      draft: !!p.draft, created: p.created_at,
      check: CHECK[p.number] || "",
      approved: APPROVED[p.number] || [],
    }));
    DATA.issues = items.filter(i => !i.pull_request).map(i => ({
      n: i.number, title: i.title, url: i.html_url,
      assignees: (i.assignees || []).map(a => a.login), updated: i.updated_at,
    }));
    const texts = await Promise.all((DATA.todoFiles || []).map(f =>
      fetch(`https://raw.githubusercontent.com/${R}/main/${f}`)
        .then(r => r.ok ? r.text() : "").then(t => [t, f]).catch(() => ["", f])));
    const fresh = [];
    texts.forEach(([t, f]) => { if (t) fresh.push(...parseTodos(t, f)); });
    if (fresh.length || !DATA.todos.length) DATA.todos = fresh;
    live = true;
    const hh = String(new Date().getHours()).padStart(2, "0");
    const mm = String(new Date().getMinutes()).padStart(2, "0");
    badge.innerHTML = `<span class="dot"></span>실시간 · ${hh}:${mm} 기준`;
  } catch (e) {
    live = false;
    badge.innerHTML = `<span class="dot snap"></span>스냅샷 · ${BUILT_LABEL} 기준`
      + (e === 403 ? " (요청 한도 초과 — 잠시 뒤 새로고침)" : "");
  }
  LAST = Date.now();
  if (ME) render(ME);
}

/* ── 나는 누구인가 ────────────────────────────────────────────────
   ⚠️ 이건 «보안»이 아니다. 저장소가 공개라 API 를 직접 부르면 누구든 같은
      정보를 얻는다. 여기서 하는 일은 «열자마자 남의 밀린 목록이 눈에 들어오는
      것»을 없애는 것이다. 접근 비용과 기본 노출은 다른 문제이고,
      팀 분위기를 흔드는 쪽은 후자다.

   그래서 잠금장치를 흉내내지 않는다. 비밀번호도 로그인도 없다 —
   있으면 «보호되고 있다»는 착각만 생긴다. 바닥글에 공개 데이터라고 밝힌다. */
const KEY = "kopl-dash-me";
let ME = "";
const known = l => DATA.team.some(([, lg]) => lg === l);

function setMe(l, remember) {
  ME = l;
  if (remember) { try { localStorage.setItem(KEY, l); } catch (e) {} }
  if (location.hash.slice(1) !== l) history.replaceState(null, "", "#" + l);
  draw();
}

function forget() {
  try { localStorage.removeItem(KEY); } catch (e) {}
  ME = "";
  history.replaceState(null, "", location.pathname);
  draw();
}

/* 처음 왔을 때. 여기에 건수를 띄우지 않는다 — 고르는 화면에 숫자가 나란히
   있으면 그게 곧 점수판이다. */
function picker() {
  document.getElementById("who").innerHTML = "";
  document.getElementById("main").innerHTML = `
    <div class="now calm pick">
      <div class="lab">시작하기</div>
      <div class="act">누구신가요?</div>
      <div class="why">고르시면 이 브라우저가 기억합니다.
        다음부터는 열자마자 본인 화면이 나옵니다.</div>
      <div class="picks">${DATA.team.map(([r, lg]) =>
        `<button type="button" data-me="${lg}">
           <span class="role">${r}</span><span class="who">@${lg}</span>
         </button>`).join("")}</div>
      <div class="why" style="margin-top:12px">
        ⚠️ 이건 잠금장치가 아닙니다. 저장소가 공개라 마음먹으면 누구나 같은
        정보를 GitHub 에서 볼 수 있습니다. 다만 <b>이 화면에서는 본인 것만</b>
        보이게 해서, 서로의 밀린 목록이 눈에 띄지 않게 했습니다.</div>
    </div>`;
  document.querySelectorAll("[data-me]").forEach(b =>
    b.onclick = () => setMe(b.dataset.me, true));
}

function draw() {
  if (!ME) { picker(); return; }
  const role = (DATA.team.find(([, lg]) => lg === ME) || ["", ME])[0];
  document.getElementById("who").innerHTML =
    `<span class="me"><span class="role">${esc(role)}</span>
       <span class="who">@${esc(ME)}</span></span>
     <button type="button" class="rf" id="notme">내가 아님</button>`;
  document.getElementById("notme").onclick = forget;
  render(ME);
}

document.getElementById("rf").onclick = () => refresh();

const hash = location.hash.slice(1);
if (known(hash)) ME = hash;
else { try { const v = localStorage.getItem(KEY); if (known(v)) ME = v; } catch (e) {} }
draw();
if (ME) refresh();
// 탭을 다시 보면 그때 갱신한다. 타이머로 계속 두드리면 시간당 한도를 태운다.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && ME && Date.now() - LAST > 60000) refresh();
});
"""

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>파도풀 — 지금 내 차례</title>
<style>__CSS__</style></head><body><div class="wrap">
<header>
  <h1>지금 내 차례인 것</h1>
  <div class="sub">
    <span class="who-team">KISIA 3팀 파도풀</span>
    <span id="fresh"><span class="dot snap"></span>스냅샷 · __STAMP__ 기준</span>
    <button class="rf" id="rf" type="button">새로고침</button>
  </div>
</header>
<div id="who" class="who-line"></div>
<main id="main"></main>
<noscript><p>이 페이지는 자바스크립트로 그립니다. 켜고 다시 열어 주세요.
  아니면 <a href="https://github.com/__REPO__/pulls">GitHub 에서 직접</a>
  보시면 됩니다.</p></noscript>
<footer>
  <p><strong>이 페이지는 GitHub 을 실시간으로 읽습니다.</strong> 열 때마다
     공개 API 를 부릅니다. 요청 한도(시간당 60회)에 걸리면 마지막으로 구운
     스냅샷을 보여주고 머리말에 그렇다고 적습니다.</p>
  <p><strong>📋 문서에서 확인할 것</strong>은 문서에
     <code>&lt;!-- dashboard: owner=계정 --&gt;</code> 표식을 단 블록만 읽습니다.
     표식 없는 <code>- [ ]</code> 는 「작성 시 확인」 같은 템플릿이라 무시합니다.</p>
  <p><strong>본인 것만 보입니다.</strong> 처음에 고른 사람이 이 브라우저에
     기억되고, 그 사람 화면만 그립니다. 서로의 밀린 목록이 나란히 뜨지 않게
     한 것입니다.<br>
     ⚠️ <strong>다만 잠금장치는 아닙니다.</strong> 저장소가 공개라 마음먹으면
     누구나 같은 정보를 GitHub 에서 볼 수 있습니다. 가려진 척하지 않겠습니다 —
     이 화면이 하는 일은 «열자마자 눈에 들어오는 것»을 줄이는 데까지입니다.</p>
  <p>손으로 채우는 칸은 하나도 없습니다. 내용이 틀렸으면 저장소가 틀린 것입니다 —
     <a href="https://github.com/__REPO__/blob/main/scripts/build_dashboard.py"
        target="_blank" rel="noopener">만드는 코드</a></p>
</footer>
</div>
<script>
const DATA = __DATA__;
const BUILT_LABEL = "__STAMP__";
__JS__
</script>
</body></html>
"""


def main() -> int:
    prs, issues = fetch()
    todos, todo_files = scan_checklists()
    data = bake(prs, issues, todos, todo_files)

    now = time.gmtime(data["built"] + 9 * 3600)   # KST = UTC+9. TZ DB 에 의존하지 않는다
    stamp = time.strftime("%m월 %d일 %H:%M", now)

    doc = (PAGE
           .replace("__CSS__", CSS)
           .replace("__JS__", JS)
           .replace("__DATA__", json.dumps(data, ensure_ascii=False))
           .replace("__STAMP__", stamp)
           .replace("__REPO__", REPO))

    sys.stdout.reconfigure(encoding="utf-8")
    print(doc)
    print("PR %d · 이슈 %d · 체크리스트 %d · 표식 문서 %d"
          % (len(prs), len(issues), len(todos), len(todo_files)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
