"""파도풀 — 재식별 위험 셀프 점검. 대회용 스파이크 (정본은 E 의 W5 분석 웹앱).

    python apps/demo/app.py                 # http://localhost:8000
    SNS_URL=http://localhost:3000           # 우리뜰. 이 주소의 /api/export/<user_ref> 만 본다

계층 경계 (E-system.md §2):
  - DB 없음. 파일 안 씀. 스캔 결과는 프로세스 메모리에만 있다가 사라진다.
  - SNS 의 export 응답만 읽는다. sns.db 를 열지 않는다.
  - 조치는 «권고» 까지. 실행 버튼은 우리뜰(SNS) 쪽 링크다. 여기서 글을 바꾸는 라우트는 없다.
  - 외부 호출은 engine/external.py 한 곳, 기본 꺼짐.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import requests  # noqa: E402
from flask import Flask, abort, jsonify, redirect, render_template, request  # noqa: E402
from markupsafe import Markup  # noqa: E402

from engine import external  # noqa: E402
from engine.pipeline import analyze, compute, evidence_posts  # noqa: E402
from engine.recommend import recommend, stage2_output  # noqa: E402

SNS_URL = os.getenv("SNS_URL", "http://localhost:3000").rstrip("/")
DEMO_PERSONAS = [p for p in os.getenv("DEMO_PERSONAS", "D05,D01,D11,D17,D06").split(",") if p]

app = Flask(__name__)
SESSIONS: dict[str, dict] = {}   # user_ref → {"prev": 결과|None, "cur": 결과}. 메모리뿐이다.

_CSS = {"LOC_ADMIN": "loc", "LOC_FACILITY": "loc", "REL_HOME": "loc", "AGE": "age", "FAM": "fam",
        "SEX": "fam", "INCOME": "inc", "JOB": "inc", "COMMUTE": "com", "REL_WORK": "com"}
_TYPE_KO = {"LOC_ADMIN": "지명", "LOC_FACILITY": "시설·장소", "REL_HOME": "집 근처", "AGE": "나이",
            "FAM": "가족", "SEX": "성별", "INCOME": "소득", "JOB": "직업", "COMMUTE": "이동·통근", "REL_WORK": "직장 근처"}
_ATTR_KO = {"age": "나이", "sex": "성별", "location": "사는 곳", "occupation": "직업", "family": "가족",
            "commute": "통근·이동", "income": "소득"}


def example_accounts() -> list[dict]:
    """연결 화면의 예시 계정 — 합성 코퍼스 인물에서 만든다. SNS DB 는 안 본다."""
    out = []
    for pid in DEMO_PERSONAS:
        f = ROOT / "data" / "corpus" / "v0" / "personas" / f"{pid}.json"
        if not f.exists():
            continue
        p = json.loads(f.read_text(encoding="utf-8"))
        out.append({"user_ref": "u_" + hashlib.sha1(pid.encode()).hexdigest()[:8],
                    "nickname": (p.get("account") or {}).get("nickname") or pid,
                    "alias": p.get("alias", "")})
    return out


def fetch_export(user_ref: str) -> dict | None:
    r = requests.get(f"{SNS_URL}/api/export/{user_ref}", timeout=5)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def run_scan(export: dict) -> dict:
    view = analyze(export)
    base = compute(view)
    rec = recommend(view, base)
    out = stage2_output(view, base, rec)
    return {"view": view, "base": base, "rec": rec, "stage2": out,
            "n_posts": len(export.get("posts") or [])}


# ── 화면용 렌더 보조 ──────────────────────────────────────────────────────
def mark_text(text: str, spans: list[dict], notes: dict) -> Markup:
    """원문에 스팬 형광을 입힌다. subject=other · 제외 스팬은 점선(x)으로 «걸러냈다» 를 보인다."""
    out, pos = [], 0
    for sp in sorted(spans, key=lambda s: s["start"]):
        if sp["start"] < pos:
            continue
        out.append(html.escape(text[pos:sp["start"]]))
        n = notes.get(sp["span_id"], {})
        excluded = sp["subject"] != "self" or n.get("exclude")
        cls = "x" if excluded else _CSS.get(sp["type"], "loc")
        title = f"{_TYPE_KO.get(sp['type'], sp['type'])} · {sp['level']} · {sp['subject']}"
        if n.get("why"):
            title += " — " + n["why"]
        out.append(f'<mark class="{cls}" title="{html.escape(title)}">{html.escape(text[sp["start"]:sp["end"]])}</mark>')
        pos = sp["end"]
    out.append(html.escape(text[pos:]))
    return Markup("".join(out))


def evidence_cards(view: dict) -> list[dict]:
    cards = []
    for p in evidence_posts(view):
        chans = []
        for tid, txt in p["texts"].items():
            sps = [s for s in p["spans"] if s["text_id"] == tid]
            chans.append({"text_id": tid, "html": mark_text(txt, sps, p["notes"]), "n": len(sps)})
        cards.append({"post_id": p["post_id"], "channels": chans, "geo_tag": p["activity_meta"].get("geo_tag"),
                      "dialect": [h.split(":", 1)[1] for h in p["flags"].get("dialect_hits") or []][:6],
                      "n_spans": len([s for s in p["spans"] if s["subject"] == "self" and not p["notes"].get(s["span_id"], {}).get("exclude")])})
    prof = view["profile"]
    if prof["spans"]:
        cards.insert(0, {"post_id": "프로필 소개란", "geo_tag": None, "dialect": [],
                         "channels": [{"text_id": "profile_bio", "html": mark_text(prof["texts"]["profile_bio"], prof["spans"], prof["notes"]), "n": len(prof["spans"])}],
                         "n_spans": len(prof["spans"])})
    return cards


def traps(view: dict) -> list[dict]:
    out = []
    for p in view["posts"]:
        for sp in p["spans"]:
            n = p["notes"].get(sp["span_id"], {})
            if sp["subject"] == "other" or n.get("exclude"):
                line = p["texts"][sp["text_id"]]
                ls = line.rfind("\n", 0, sp["start"]) + 1
                le = line.find("\n", sp["end"])
                out.append({"post_id": p["post_id"], "text": sp["text"], "why": n.get("why", ""),
                            "sentence": line[ls: len(line) if le < 0 else le].strip(),
                            "kind": "타인" if sp["subject"] == "other" else {"past_residence": "과거 거주", "transit": "이동 경로"}.get(n.get("exclude"), "제외")})
    return out


def rewrite_forms(res: dict) -> dict[str, list[dict]]:
    """조치 ③ 카드용 — span_id → 후보 3안. 각 후보에 «우리뜰 수정 화면으로 보낼 본문 전체» 를 붙인다."""
    view = res["view"]
    texts = {p["post_id"]: p["texts"] for p in view["posts"]}
    out: dict[str, list[dict]] = {}
    for r in res["rec"]["rewrites"]:
        full = texts[r["post_id"]][r["_text_id"]]
        new_full = full.replace(r["_sentence"], r["_new_sentence"], 1)
        field = "body" if r["_text_id"] == "body" else ("title" if r["_text_id"] == "title" else "caption" + r["_text_id"].split(":")[1])
        out.setdefault(r["span_id"], []).append({**r, "field": field, "new_full": new_full})
    return out


def cut_steps(prev: dict | None, cur: dict) -> list[dict]:
    if not prev:
        return []
    now = {s["condition"] for s in cur["base"]["steps"]}
    return [s for s in prev["base"]["steps"] if s["condition"] not in now and s["axis"] != "sex"]


# ── 라우트 ────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return render_template("connect.html", accounts=example_accounts(), sns_url=SNS_URL,
                           external_on=external.enabled())


@app.post("/scan")
def scan():
    user_ref = (request.form.get("user_ref") or "").strip()
    if not user_ref:
        return redirect("/")
    try:
        export = fetch_export(user_ref)
    except requests.RequestException as e:
        return render_template("connect.html", accounts=example_accounts(), sns_url=SNS_URL,
                               external_on=external.enabled(),
                               error=f"우리뜰({SNS_URL})에 연결하지 못했습니다 — SNS 가 떠 있나요? ({e.__class__.__name__})"), 502
    if export is None:
        return render_template("connect.html", accounts=example_accounts(), sns_url=SNS_URL,
                               external_on=external.enabled(), error=f"우리뜰에 {user_ref} 계정이 없습니다."), 404
    res = run_scan(export)
    s = SESSIONS.setdefault(user_ref, {"prev": None, "cur": None})
    s["prev"], s["cur"] = s["cur"], res
    return redirect(f"/result/{user_ref}")


@app.get("/result/<user_ref>")
def result(user_ref: str):
    s = SESSIONS.get(user_ref)
    if not s or not s["cur"]:
        return redirect("/")
    res, prev = s["cur"], s["prev"]
    base, rec, st2 = res["base"], res["rec"], res["stage2"]
    leaking = [(_ATTR_KO[a], f["verdict"]) for a, f in st2["findings"].items() if f["verdict"] != "abstain"]
    return render_template(
        "result.html", user_ref=user_ref, nickname=res["view"]["nickname"], n_posts=res["n_posts"],
        base=base, prev=prev["base"] if prev else None, rec=rec, st2=st2, leaking=leaking,
        n_direct=len(res["view"]["direct_identifiers"]), cards=evidence_cards(res["view"]),
        traps=traps(res["view"]), rewrites=rewrite_forms(res), cut=cut_steps(prev, res),
        sns_url=SNS_URL, attr_ko=_ATTR_KO, external_on=external.enabled())


@app.get("/api/result/<user_ref>")
def api_result(user_ref: str):
    """계약 Stage2Output 그대로 — 심사·개발자용."""
    s = SESSIONS.get(user_ref)
    if not s or not s["cur"]:
        abort(404)
    return jsonify(s["cur"]["stage2"])


@app.post("/forget/<user_ref>")
def forget(user_ref: str):
    SESSIONS.pop(user_ref, None)
    return redirect("/")


if __name__ == "__main__":
    app.run(port=int(os.getenv("DEMO_PORT", "8000")), debug=os.getenv("DEMO_DEBUG") == "1")
