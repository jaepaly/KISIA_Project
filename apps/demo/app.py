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
from engine.recommend import (_line_of, candidates_for, fit_particle, ladder_candidates,  # noqa: E402
                              leading_particle, recommend, stage2_output)

SNS_URL = os.getenv("SNS_URL", "http://localhost:3000").rstrip("/")
DEMO_PERSONAS = [p for p in os.getenv("DEMO_PERSONAS", "D05,D01,D11,D06").split(",") if p]

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
        out.append(f'<mark class="{cls}" data-span="{html.escape(sp["span_id"])}" title="{html.escape(title)}">'
                   f'{html.escape(text[sp["start"]:sp["end"]])}</mark>')
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
                            "kind": "타인" if sp["subject"] == "other" else {"past_residence": "과거 거주", "transit": "이동 경로", "travel": "여행지"}.get(n.get("exclude"), "제외")})
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


def summary(res: dict) -> dict:
    b = res["base"]
    return {"k": b["k"], "k_level": b["k_level"], "risk": b["risk"], "label": b["label"], "css": b["css"],
            "steps": b["steps"], "n_posts": res["n_posts"]}


def api_payload(res: dict) -> dict:
    """우리뜰(플랫폼)이 자기 화면에 그릴 수 있는 형태. 계약 Stage2Output 은 `stage2` 에 그대로 담는다."""
    view, base, rec, st2 = res["view"], res["base"], res["rec"], res["stage2"]
    cards = [{**c, "channels": [{**ch, "html": str(ch["html"])} for ch in c["channels"]]} for c in evidence_cards(view)]
    rws: dict[str, list] = {}
    for sid, items in rewrite_forms(res).items():
        rws[sid] = [{"suggestion": r["suggestion"], "note": r["_note"], "similarity": r["semantic_similarity"],
                     "sentence": r["_sentence"], "new_sentence": r["_new_sentence"], "field": r["field"],
                     "new_full": r["new_full"], "text_id": r["_text_id"]} for r in items]
    acts = [{"action_type": a["action_type"], "burden": a["burden"], "certainty": a["certainty"],
             "rationale": a["rationale"], "projected_delta": a["projected_delta"], "post_id": a["_post_id"],
             "span_id": a.get("_span_id"), "k": a["_k"], "k_cum": a["_k_cum"]} for a in rec["actions"]]
    return {
        **summary(res), "user_ref": view["user_ref"], "nickname": view["nickname"],
        "findings": {a: {**f, "ko": _ATTR_KO[a]} for a, f in st2["findings"].items()},
        "leaking": [_ATTR_KO[a] for a, f in st2["findings"].items() if f["verdict"] != "abstain"],
        "n_direct": len(view["direct_identifiers"]),
        "traps": traps(view), "evidence": cards, "actions": acts, "rewrites": rws,
        "projected": rec["projected"], "projected_k": rec["projected_k"], "exceptional": rec["exceptional"],
        "provenance": st2["provenance"], "stage2": st2,
    }


@app.post("/api/scan")
def api_scan():
    """플랫폼(우리뜰)이 export 형식 그대로 보내면 진단을 돌려준다. 저장하지 않는다."""
    export = request.get_json(silent=True)
    if not export or "user_ref" not in export or "posts" not in export:
        abort(400)
    return jsonify(api_payload(run_scan(export)))


@app.post("/api/check")
def api_check():
    """에디터 점검 — 작성 완료 후 1회 [MF-015]. {export, draft} → 올리기 전/후 k 와 초안의 새는 문장.

    draft = {title, body, photos:[{caption}], activity_meta:{geo_tag}}. 기존 공개 글과 합쳐 세므로
    「이 글 하나가 후보를 얼마나 좁히나」 가 실제 계산으로 나온다.
    """
    j = request.get_json(silent=True) or {}
    export, draft = j.get("export"), j.get("draft")
    if not export or draft is None:
        abort(400)
    before = run_scan(export)
    d = {"post_id": "draft", "user_ref": export["user_ref"], "title": draft.get("title") or None,
         "body": draft.get("body") or "", "photos": draft.get("photos") or [],
         "activity_meta": {"nickname": export.get("nickname"), "geo_tag": (draft.get("activity_meta") or {}).get("geo_tag"),
                           "post_time": None}}
    after = run_scan({**export, "posts": [*export["posts"], d]})
    dv = [p for p in after["view"]["posts"] if p["post_id"] == "draft"][0]
    chans = [{"text_id": tid, "html": str(mark_text(txt, [s for s in dv["spans"] if s["text_id"] == tid], dv["notes"]))}
             for tid, txt in dv["texts"].items()]
    self_spans = [s for s in dv["spans"] if s["subject"] == "self" and not dv["notes"].get(s["span_id"], {}).get("exclude")]
    contributing = [s for s in after["base"]["steps"] if s.get("src") and s["src"].get("post_id") == "draft"]
    # 초안 스팬마다 — 에디터에서 그 자리를 누르면 바로 고를 수 있게 후보 3안과 «이 표현을 빼면 k» 를 붙인다
    spans_out = []
    ext_used = after["stage2"]["provenance"]["external_llm_used"]
    for s in self_spans:
        text = dv["texts"][s["text_id"]]
        ls, le = _line_of(text, s["start"], s["end"])
        cands, used = candidates_for(text[ls:le], s)
        ext_used = ext_used or used
        k_without = compute(after["view"], exclude_spans=frozenset({s["span_id"]}))["k"]
        # 지우지 말고 넓히기 — 지명은 상위 행정구역, 나이는 10년 단위. 각 단에 실제 k. 그 뒤에 일반 후보(지우기)
        ladder = ladder_candidates(after["view"], "draft", s, dv["notes"].get(s["span_id"], {}))
        merged = [{**c, "kind": "widen"} for c in ladder] + \
                 [{**c, "k": k_without, "kind": "erase"} for c in cands][: (2 if ladder else 3)]
        # 뒤에 조사가 붙어 있으면 치환 범위에 넣고 후보마다 받침에 맞는 조사를 붙여 준다 (「이 나이이 되니」 방지)
        particle = leading_particle(text[s["end"]:])
        spans_out.append({"span_id": s["span_id"], "text": s["text"] + particle, "particle": particle,
                          "type": _TYPE_KO.get(s["type"], s["type"]), "level": s["level"], "text_id": s["text_id"],
                          "start": s["start"], "end": s["end"] + len(particle), "k_without": k_without,
                          "candidates": [{"text": c["text"] + (fit_particle(c["text"], particle) if c["text"] else ""),
                                          "note": c["note"], "k": c["k"], "kind": c["kind"], "bound": c.get("bound"),
                                          "bound_k": c.get("bound_k"),
                                          "bound_fix": ({**c["bound_fix"], "check_url": f"/u/{export['user_ref']}/check"}
                                                        if c.get("bound_fix") else None)}
                                         for c in merged]})
    return jsonify({
        "before": summary(before), "after": summary(after),
        "draft": {"channels": chans, "n_spans": len(self_spans), "spans": spans_out,
                  "dialect": [h.split(":", 1)[1] for h in dv["flags"].get("dialect_hits") or []][:6],
                  "traps": [t for t in traps(after["view"]) if t["post_id"] == "draft"],
                  "geo_tag": d["activity_meta"]["geo_tag"]},
        "contributing": contributing,
        "narrows": after["base"]["k"] < before["base"]["k"] if before["base"]["k"] and after["base"]["k"] else False,
        "provenance": {**after["stage2"]["provenance"], "external_llm_used": ext_used},
    })


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
