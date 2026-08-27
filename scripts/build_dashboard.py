#!/usr/bin/env python3
"""팀 대시보드 — 사람마다 「지금 내 차례인 것」을 한 장으로.

  python scripts/build_dashboard.py > site/index.html

왜 만들었나
    디스코드 알림은 «흐름»이고 PR 은 «상태»다. 흐름으로 상태를 전하면
    쌓일수록 자기 것을 못 찾는다. 실제로 다음이 일어났다.
      · geo-dictionary §8 체크리스트 5건을 담당자가 자기 몫인 줄 몰랐다
      · 고친 커밋을 PR 로 안 열어서 main 에 안 들어간 채로 하루가 갔다

GitHub 이 이미 해주는 것은 안 만든다
    「내 승인이 필요한 PR」은 아래 URL 이 항상 정확하다. 우리 페이지는
    스냅샷이라 저것보다 늘 낡다. 그런데도 만드는 이유는 ③ 때문이다.
      https://github.com/OWNER/REPO/pulls?q=is%3Aopen+is%3Apr+review-requested%3A%40me

무엇을 모으나
    ① 내 승인이 필요한 PR      reviewRequests 에 내가 있는 열린 PR
    ② 내가 작성자인데 멈춘 PR   내가 쓴 PR 중 reviewRequests 가 빈 것
    ③ 문서 체크리스트          «dashboard» 표식이 붙은 - [ ] 항목      ← GitHub 이 못 보는 것
    ④ 담당 이슈                assignees 에 내가 있는 열린 이슈

③ 표식 — 이렇게 적은 블록만 읽는다

    <!-- dashboard: owner=jhyun114 -->
    - [ ] §1 candidates 를 함께 싣는 것
    - [ ] §4 offset 을 유니코드 코드포인트로

    ⚠️ 표식 없는 - [ ] 는 무시한다. 저장소의 - [ ] 대부분은
       persona-design.md 의 «작성 시 확인» 처럼 매번 다시 쓰는 템플릿이지
       누구의 남은 작업이 아니다. 전부 긁으면 121건이 뜨고 아무도 안 본다.
       owner 는 쉼표로 여럿 적을 수 있다 (owner=jhyun114,jaepaly).

⚠️ 손으로 채우는 칸을 두지 않는다. 하나라도 수동이면 곧 낡고,
   낡은 대시보드는 없느니만 못하다 — 사람들이 믿고 안 보게 되기 때문이다.

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
LOGINS = [lg for _, lg in TEAM]
ROLE = {lg: r for r, lg in TEAM}

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
                        "updatedAt,createdAt,statusCheckRollup"])
    issues = gh(["issue", "list", "--repo", REPO, "--state", "open", "--limit", "100",
                 "--json", "number,title,url,author,assignees,updatedAt,createdAt"])
    return prs, issues


def scan_checklists() -> list[dict]:
    """표식이 붙은 블록의 미완 항목만 거둔다."""
    out = []
    if not DOCS_ROOT.is_dir():
        return out
    for path in sorted(DOCS_ROOT.rglob("*.md")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        owners: list[str] | None = None
        in_comment = False
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
                continue
            m = MARKER.search(line)
            if m:
                owners = [o.strip() for o in m.group(1).split(",") if o.strip()]
                continue
            if owners is None:
                continue
            u = UNCHECKED.match(line)
            if u:
                out.append({
                    "owners": owners, "text": u.group(1).strip(),
                    "file": path.as_posix(), "line": i,
                })
                continue
            if CHECKED.match(line):
                continue
            # 한 줄짜리 주석도 안 끊는다.
            if line.lstrip().startswith("<!--"):
                continue
            # 빈 줄도 안 끊는다. 체크박스도 주석도 아닌 «내용» 줄에서 끊는다.
            if line.strip():
                owners = None
    return out


def days_since(iso: str) -> int:
    try:
        t = time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return 0
    return max(0, int((time.time() - time.mktime(t) + time.timezone) // 86400))


def checks_of(pr: dict) -> tuple[str, str]:
    """필수 검사는 guard·lint 다. notify 는 디스코드 알림이라 무시한다."""
    roll = pr.get("statusCheckRollup") or []
    req = [c for c in roll if (c.get("name") or "") in ("guard", "lint")]
    if not req:
        return "none", "검사 없음"
    bad = [c for c in req if (c.get("conclusion") or c.get("status")) != "SUCCESS"]
    if any((c.get("status") or "") in ("IN_PROGRESS", "QUEUED") for c in bad):
        return "run", "검사 진행 중"
    if bad:
        return "fail", "검사 실패"
    return "ok", "검사 통과"


def bucket(prs, issues, todos):
    """사람마다 네 묶음. 아무에게도 안 붙는 것은 '__none__' 으로 모은다."""
    per = {lg: {"review": [], "mine": [], "issues": [], "todos": []} for lg in LOGINS}
    per["__none__"] = {"review": [], "mine": [], "issues": [], "todos": []}

    for pr in prs:
        reqs = [r.get("login") for r in (pr.get("reviewRequests") or []) if r.get("login")]
        author = (pr.get("author") or {}).get("login")
        if reqs:
            for lg in reqs:
                per.setdefault(lg, {"review": [], "mine": [], "issues": [], "todos": []})
                per[lg]["review"].append(pr)
        elif author in per:
            per[author]["mine"].append(pr)
        else:
            per["__none__"]["mine"].append(pr)

    for it in issues:
        asg = [a.get("login") for a in (it.get("assignees") or []) if a.get("login")]
        if not asg:
            per["__none__"]["issues"].append(it)
        for lg in asg:
            per.setdefault(lg, {"review": [], "mine": [], "issues": [], "todos": []})
            per[lg]["issues"].append(it)

    for t in todos:
        for lg in t["owners"]:
            per.setdefault(lg, {"review": [], "mine": [], "issues": [], "todos": []})
            per[lg]["todos"].append(t)

    return per


# ── 렌더 ──────────────────────────────────────────────────────────────
E = html.escape

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")


def md(text: str) -> str:
    """체크리스트 항목의 인라인 마크다운만 살린다.

    ⚠️ 먼저 escape 하고 그 다음에 태그를 넣는다. 순서를 바꾸면 문서에
       <script> 를 적은 사람이 이 페이지에 스크립트를 심을 수 있다.
    """
    out = E(text)
    out = _CODE.sub(r"<code>\g<1></code>", out)
    out = _BOLD.sub(r"<strong>\g<1></strong>", out)
    return out

CSS = """
:root{
  --bg:#fbfbfa; --card:#fff; --ink:#1a1a19; --dim:#6b6b68; --line:#e5e5e2;
  --accent:#7c5cff; --red:#c4342b; --amber:#a86400; --green:#2c7a4b;
  --chip:#f0f0ee;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#16161a; --card:#1e1e23; --ink:#eceef2; --dim:#9a9aa4; --line:#2e2e36;
  --accent:#9d85ff; --red:#ff8a80; --amber:#e3aa4a; --green:#6fcf97; --chip:#26262e;
}}
:root[data-theme="dark"]{
  --bg:#16161a; --card:#1e1e23; --ink:#eceef2; --dim:#9a9aa4; --line:#2e2e36;
  --accent:#9d85ff; --red:#ff8a80; --amber:#e3aa4a; --green:#6fcf97; --chip:#26262e;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic",
       "Apple SD Gothic Neo",sans-serif;}
.wrap{max-width:900px;margin:0 auto;padding:28px 18px 64px}
header{margin-bottom:22px}
h1{font-size:21px;margin:0 0 6px;letter-spacing:-.01em}
.sub{color:var(--dim);font-size:13px}
.stale{color:var(--amber);font-weight:600}
nav{display:flex;flex-wrap:wrap;gap:7px;margin:20px 0 24px}
nav button{font:inherit;font-size:14px;cursor:pointer;padding:7px 15px;
  border-radius:999px;border:1px solid var(--line);background:var(--card);
  color:var(--ink);transition:.12s}
nav button:hover{border-color:var(--accent)}
nav button[aria-selected="true"]{background:var(--accent);border-color:var(--accent);
  color:#fff;font-weight:600}
nav button .n{opacity:.65;margin-left:5px;font-variant-numeric:tabular-nums}
section[hidden]{display:none}
h2{font-size:14px;margin:26px 0 10px;color:var(--dim);font-weight:600}
h2:first-of-type{margin-top:0}
ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
li{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:11px 13px}
li.hot{border-left:3px solid var(--red)}
li.warm{border-left:3px solid var(--amber)}
a{color:inherit;text-decoration:none}
a:hover .t{text-decoration:underline}
.num{color:var(--dim);font-variant-numeric:tabular-nums;margin-right:6px}
.t{font-weight:500}
.meta{margin-top:5px;font-size:12.5px;color:var(--dim);
  display:flex;flex-wrap:wrap;gap:5px 10px;align-items:center}
.chip{background:var(--chip);border-radius:5px;padding:1px 7px;font-size:12px}
.ok{color:var(--green)} .fail{color:var(--red)} .warnc{color:var(--amber)}
.empty{color:var(--dim);font-size:13.5px;padding:14px 0}
.todo .t{font-weight:400}
.t code{background:var(--chip);border-radius:4px;padding:1px 5px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}
.t strong{font-weight:650}
.src{font-size:12px;color:var(--dim);font-family:ui-monospace,SFMono-Regular,
  Menlo,Consolas,monospace}
footer{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);
  color:var(--dim);font-size:12.5px}
footer a{text-decoration:underline}
footer p{margin:6px 0}
@media(max-width:520px){.wrap{padding:20px 13px 48px}h1{font-size:19px}}
"""

JS = """
const tabs=[...document.querySelectorAll('nav button')];
function show(id){
  tabs.forEach(b=>b.setAttribute('aria-selected',String(b.dataset.tab===id)));
  document.querySelectorAll('section[data-panel]')
    .forEach(s=>s.hidden = s.dataset.panel!==id);
  try{localStorage.setItem('kopl-dash-tab',id)}catch(e){}
  if(location.hash.slice(1)!==id) history.replaceState(null,'','#'+id);
}
tabs.forEach(b=>b.onclick=()=>show(b.dataset.tab));
let start=location.hash.slice(1);
if(!start){try{start=localStorage.getItem('kopl-dash-tab')||''}catch(e){}}
show(tabs.some(b=>b.dataset.tab===start)?start:tabs[0].dataset.tab);
"""


def pr_li(pr, hot):
    kind, label = checks_of(pr)
    cls = {"ok": "ok", "fail": "fail", "run": "warnc", "none": ""}[kind]
    d = days_since(pr.get("createdAt") or pr.get("updatedAt") or "")
    reqs = [r.get("login") for r in (pr.get("reviewRequests") or []) if r.get("login")]
    bits = ['<span class="%s">%s</span>' % (cls, E(label))]
    if d >= 1:
        bits.append('<span class="chip">%d일째</span>' % d)
    if pr.get("isDraft"):
        bits.append('<span class="chip">Draft</span>')
    if reqs:
        who = " · ".join(("%s @%s" % (ROLE.get(l, ""), l)).strip() for l in reqs)
        bits.append("기다리는 사람: " + E(who))
    return ('<li class="%s"><a href="%s" target="_blank" rel="noopener">'
            '<span class="num">#%d</span><span class="t">%s</span></a>'
            '<div class="meta">%s</div></li>'
            % ("hot" if hot and d >= 1 else "", E(pr["url"]), pr["number"],
               E(pr["title"]), "".join(bits)))


def issue_li(it):
    d = days_since(it.get("updatedAt") or "")
    return ('<li><a href="%s" target="_blank" rel="noopener">'
            '<span class="num">#%d</span><span class="t">%s</span></a>'
            '<div class="meta"><span class="chip">%d일 전 갱신</span></div></li>'
            % (E(it["url"]), it["number"], E(it["title"]), d))


def todo_li(t):
    url = "https://github.com/%s/blob/main/%s#L%d" % (REPO, t["file"], t["line"])
    return ('<li class="todo warm"><a href="%s" target="_blank" rel="noopener">'
            '<span class="t">%s</span></a>'
            '<div class="meta"><span class="src">%s:%d</span></div></li>'
            % (E(url), md(t["text"]), E(t["file"]), t["line"]))


def block(title, items, render, empty):
    if items:
        body = "".join(render(x) for x in items)
    else:
        body = ('<li style="border:none;background:none;padding:0">'
                '<div class="empty">%s</div></li>' % E(empty))
    return "<h2>%s</h2><ul>%s</ul>" % (E(title), body)


def panel(pid, data, is_person):
    parts = []
    if is_person:
        parts.append(block("🔴 내 승인을 기다리는 PR", data["review"],
                           lambda p: pr_li(p, True), "없습니다."))
        parts.append(block("🟡 내가 올렸고 리뷰어가 없는 PR", data["mine"],
                           lambda p: pr_li(p, False),
                           "없습니다. (리뷰 요청을 걸어야 남이 봅니다)"))
        parts.append(block("📋 문서 체크리스트", data["todos"], todo_li,
                           "표식이 붙은 미완 항목이 없습니다."))
        parts.append(block("📌 담당 이슈", data["issues"], issue_li, "없습니다."))
    else:
        parts.append(block("리뷰어가 지정되지 않은 PR", data["mine"],
                           lambda p: pr_li(p, False), "없습니다."))
        parts.append(block("담당자가 없는 이슈", data["issues"], issue_li, "없습니다."))
    return '<section data-panel="%s" hidden>%s</section>' % (pid, "".join(parts))


PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>파도풀 — 지금 내 차례</title>
<style>%(css)s</style></head><body><div class="wrap">
<header>
  <h1>지금 내 차례인 것</h1>
  <div class="sub">KISIA 3팀 파도풀 · %(stamp)s 기준<span class="stale" id="stale"></span></div>
</header>
<nav role="tablist">%(nav)s</nav>
%(panels)s
<footer>
  <p><strong>이 페이지는 스냅샷입니다.</strong> 30분마다, 그리고 PR·이슈가 바뀔 때마다
     다시 만들어집니다. 지금 이 순간을 확실히 보려면
     <a href="https://github.com/%(repo)s/pulls?q=is%%3Aopen+is%%3Apr+review-requested%%3A%%40me"
        target="_blank" rel="noopener">GitHub 에서 직접</a> 보세요 — 그쪽이 항상 정확합니다.</p>
  <p><strong>📋 문서 체크리스트</strong>는 문서에
     <code>&lt;!-- dashboard: owner=계정 --&gt;</code> 표식을 단 블록만 읽습니다.
     표식 없는 <code>- [ ]</code> 는 「작성 시 확인」 같은 템플릿이라 무시합니다.</p>
  <p>손으로 채우는 칸은 하나도 없습니다. 내용이 틀렸으면 저장소가 틀린 것입니다 —
     <a href="https://github.com/%(repo)s/blob/main/scripts/build_dashboard.py"
        target="_blank" rel="noopener">만드는 코드</a></p>
</footer>
</div>
<script>
const BUILT=%(built)d;
%(js)s
(function(){
  const h=(Date.now()/1000-BUILT)/3600;
  if(h>2) document.getElementById('stale').textContent =
    ' — ⚠️ ' + Math.floor(h) + '시간 전 정보입니다';
})();
</script>
</body></html>
"""


def main():
    prs, issues = fetch()
    todos = scan_checklists()
    per = bucket(prs, issues, todos)

    now = time.gmtime(time.time() + 9 * 3600)      # KST = UTC+9. TZ DB 에 의존하지 않는다
    stamp = time.strftime("%m월 %d일 %H:%M", now)

    navs, panels = [], []
    for role, lg in TEAM:
        d = per[lg]
        n = len(d["review"]) + len(d["mine"]) + len(d["todos"]) + len(d["issues"])
        navs.append('<button data-tab="%s" role="tab" aria-selected="false">'
                    '%s · @%s<span class="n">%d</span></button>' % (lg, role, lg, n))
        panels.append(panel(lg, d, True))

    nd = per["__none__"]
    n0 = len(nd["mine"]) + len(nd["issues"])
    navs.append('<button data-tab="__none__" role="tab" aria-selected="false">'
                '담당 없음<span class="n">%d</span></button>' % n0)
    panels.append(panel("__none__", nd, False))

    doc = PAGE % {
        "css": CSS, "js": JS, "stamp": stamp, "repo": REPO,
        "nav": "".join(navs), "panels": "".join(panels),
        "built": int(time.time()),
    }
    sys.stdout.reconfigure(encoding="utf-8")
    print(doc)
    print("PR %d · 이슈 %d · 체크리스트 %d" % (len(prs), len(issues), len(todos)),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
