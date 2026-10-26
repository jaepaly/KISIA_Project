"""exp43 — k 조건을 본인(subject=self) 스팬으로만 만들 때 dev 위험도 · k 가 어떻게 바뀌나.

    export PYTHONIOENCODING=utf-8 PYTHONPATH=src
    # 1) 바꾸기 전 코드(main)에서 사용자별 값을 떠 둔다 — 저장소 밖 경로
    python experiments/exp43-self-only-k/measure.py dump --preds <dev 1단 예측 spans jsonl> --out <before.json>
    # 2) 바꾼 코드에서 같은 명령 → after.json
    # 3) 둘을 견준 요약
    python experiments/exp43-self-only-k/measure.py compare --before <before.json> --after <after.json> \\
        --out experiments/exp43-self-only-k/results/summary.json

계산은 하류 러너(experiments/bench/d_risk_action.py)를 그대로 부른다 — 앱과 같은 조건 함수
(``infer._app_conditions`` = ``k_engine.conditions_from_posts``) · 위치태그(seed_sns 재현 · seed 42) · ``risk_total``.
k 는 같은 조건 목록에 ``estimate_k`` 를 부른다(앱 c23.specificity 와 같다). 2단 모델은 다시 돌리지 않는다 —
위험도 · k 는 1단 스팬만으로 계산되고 2단 출력을 입력으로 쓰지 않는다.

test 255편은 ``d_risk_action.read_preds`` 가 막는다(splits/test_post_ids.json["post_ids"] · 길이 255 assert).
골드는 ``gold/<persona>_spans.jsonl`` 최상위만 읽는다 — gold/blind/ 는 하위 폴더라 안 읽힌다.
dump 결과에는 합성 코퍼스의 조건 값이 들어가므로 저장소에는 compare 요약만 남긴다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "scripts", ROOT / "experiments" / "bench"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import d_risk_action as dra  # noqa: E402

from kopl.c1_span.bio import span_iou  # noqa: E402
from kopl.c2_specificity.k_engine import estimate_k  # noqa: E402


def _conditions(posts, engine, *, geo=True):
    conditions_fn, geo_fn, _ = engine
    out = []
    for p in posts:
        out.extend(conditions_fn(list(p.get("spans") or []), p["post_id"]))
        if geo and p.get("geo_tag"):
            c = geo_fn(p["geo_tag"], p["post_id"])
            if c is not None:
                out.append(c)
    return out


def _sig(c):
    return [c["axis"], c["kind"], c.get("geo_code") or c.get("value"), c["resolution"], c["confidence"],
            sorted(c["source_post_ids"])]


def _view(posts, engine):
    conds = _conditions(posts, engine)
    k = estimate_k(conds)
    return {"risk": round(float(engine[2](conds)), 2), "k": k["k"], "k_level": k["k_level"],
            "conditions": sorted((_sig(c) for c in conds), key=json.dumps)}


def _match(pred, gold):
    """같은 채널 · 같은 유형 · IoU ≥ 0.5 · 일대일 — IoU 큰 쌍부터 (label-schema §2 partial · exp41 match 와 같다).

    (pred, gold|None) 목록을 pred 순서대로 돌려준다. IoU 가 같으면 목록 위치가 아니라 스팬 좌표로 순서를 정한다 —
    예측 · 골드 순서가 바뀌어도 맞은 수가 같다 (Codex 검토 2회).
    """
    key = lambda x: (x["start"], x["end"], x["type"])  # noqa: E731
    cand = sorted(((-span_iou(key(a), key(b)), key(a), key(b), i, j) for i, a in enumerate(pred) for j, b in enumerate(gold)
                   if a["type"] == b["type"] and a.get("text_id") == b.get("text_id")
                   and span_iou(key(a), key(b)) >= 0.5))
    up: dict[int, int] = {}
    used: set[int] = set()
    for *_, i, j in cand:
        if i not in up and j not in used:
            up[i] = j
            used.add(j)
    return [(a, gold[up[i]] if i in up else None) for i, a in enumerate(pred)]


def dump(preds_path: Path, out: Path) -> None:
    preds = dra.read_preds(preds_path)               # test 글이 섞이면 멈춘다
    users = dra.group_by_user(preds)
    geo = dra.seed_geo_tags()
    engine = dra.app_engine()
    rows = []
    commute = Counter()
    self_prec: dict[str, Counter] = defaultdict(Counter)
    for user, pids in users.items():
        posts = [{"post_id": p, "spans": preds[p], "geo_tag": geo.get(p)} for p in pids]
        gold = dra.load_gold(user)
        row = {"user": user, "pred_all": _view(posts, engine)}
        if gold is not None:
            both = [p for p in posts if p["post_id"] in gold]
            gposts = [{**p, "spans": gold[p["post_id"]]} for p in both]
            if gposts:
                row["pred"] = _view(both, engine)
                row["gold"] = _view(gposts, engine)
                for p in both:
                    g = gold[p["post_id"]]
                    for t in {x["type"] for x in p["spans"]}:   # 유형별 본인 스팬 정밀도 — 통근을 다른 유형과 견줄 기준
                        mine = [x for x in p["spans"] if x["type"] == t and x.get("subject") == "self"]
                        for _, hit in _match(mine, [x for x in g if x["type"] == t]):
                            self_prec[t]["n"] += 1
                            self_prec[t]["match_gold"] += hit is not None
                    pc = [s for s in p["spans"] if s["type"] == "COMMUTE" and s.get("subject") != "other"]
                    for s, m in _match(pc, [x for x in g if x["type"] == "COMMUTE"]):
                        key = s.get("subject")
                        commute[f"pred_{key}"] += 1
                        commute[f"pred_{key}_match_gold"] += m is not None
                        commute[f"pred_{key}_match_gold_self"] += m is not None and m.get("subject") == "self"
                    rw = any(s["type"] == "REL_WORK" and s.get("subject") != "other" for s in p["spans"])
                    if rw:
                        commute["pred_rel_work_posts"] += 1
                        commute["pred_rel_work_posts_gold_rel_work"] += any(
                            x["type"] == "REL_WORK" and x.get("subject") != "other" for x in g)
                        commute["pred_rel_work_posts_gold_rel_work_self"] += any(
                            x["type"] == "REL_WORK" and x.get("subject") == "self" for x in g)
                    commute["gold_commute_self"] += sum(x["type"] == "COMMUTE" and x.get("subject") == "self" for x in g)
                    commute["gold_commute_unknown"] += sum(x["type"] == "COMMUTE" and x.get("subject") == "unknown" for x in g)
        rows.append(row)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"meta": {"preds": str(preds_path), "preds_sha256": dra._sha256(preds_path),
                                        "git_commit": dra._git_commit(), "n_users": len(rows),
                                        "n_posts": sum(len(v) for v in users.values())},
                               "commute": dict(commute),
                               "self_precision_by_type": {t: {**c, "precision": round(c["match_gold"] / c["n"], 3)}
                                                          for t, c in sorted(self_prec.items())},
                               "users": rows}, ensure_ascii=False, indent=1),
                   encoding="utf-8", newline="\n")


def _axis_counts(rows, key):
    c = Counter()
    for r in rows:
        if key in r:
            for s in r[key]["conditions"]:
                c[s[0]] += 1
    return dict(sorted(c.items()))


def _levels(rows, key):
    return dict(sorted(Counter(r[key]["k_level"] for r in rows if key in r).items()))


def _users(d: dict) -> dict[str, dict]:
    names = [r["user"] for r in d["users"]]
    assert len(names) == len(set(names)), "dump 에 같은 사용자가 두 번 있다"
    return {r["user"]: r for r in d["users"]}


def compare(before: Path, after: Path, out: Path) -> dict:
    b, a = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (before, after))
    assert b["meta"]["preds_sha256"] == a["meta"]["preds_sha256"], "두 dump 의 입력이 다르다"
    bu, au = _users(b), _users(a)
    assert bu.keys() == au.keys()
    res = {"meta": {"preds_sha256": a["meta"]["preds_sha256"], "n_users": len(au), "n_posts": a["meta"]["n_posts"],
                    "before_commit": b["meta"]["git_commit"], "after_commit": a["meta"]["git_commit"]}}
    for side, d in (("before", bu), ("after", au)):
        rows = [r for r in d.values() if "gold" in r]
        res[side] = {
            "risk_vs_gold": dra._compare([r["pred"]["risk"] for r in rows], [r["gold"]["risk"] for r in rows]),
            "k_level_pred": _levels(d.values(), "pred_all"),
            "k_level_gold": _levels(rows, "gold"),
            "conditions_by_axis_pred": _axis_counts(d.values(), "pred_all"),
            "conditions_by_axis_gold": _axis_counts(rows, "gold"),
            "k_level_agree_pred_vs_gold": round(sum(r["pred"]["k_level"] == r["gold"]["k_level"] for r in rows)
                                                / len(rows), 4),
        }
    changed = {side: sorted(u for u in au if bu[u][key]["conditions"] != au[u][key]["conditions"])
               for side, key in (("pred", "pred_all"), ("gold", "gold")) if all(key in bu[u] for u in bu)}
    changed["gold"] = sorted(u for u in au if "gold" in au[u] and bu[u]["gold"]["conditions"] != au[u]["gold"]["conditions"])
    res["changed_users"] = {
        "pred_conditions": len(changed["pred"]),
        "gold_conditions": len(changed["gold"]),
        "pred_k_level": sum(bu[u]["pred_all"]["k_level"] != au[u]["pred_all"]["k_level"] for u in au),
        "pred_k_value": sum(bu[u]["pred_all"]["k"] != au[u]["pred_all"]["k"] for u in au),
        "pred_risk": sum(bu[u]["pred_all"]["risk"] != au[u]["pred_all"]["risk"] for u in au),
        "gold_risk": sum(bu[u]["gold"]["risk"] != au[u]["gold"]["risk"] for u in au if "gold" in au[u]),
        "gold_k_level": sum(bu[u]["gold"]["k_level"] != au[u]["gold"]["k_level"] for u in au if "gold" in au[u]),
        "pred_k_level_transitions": dict(Counter(f"{bu[u]['pred_all']['k_level']}->{au[u]['pred_all']['k_level']}"
                                                 for u in au if bu[u]["pred_all"]["k_level"] != au[u]["pred_all"]["k_level"])),
    }
    c = a["commute"]
    gold_rows = [r for r in au.values() if "gold" in r]
    with_commute = [r for r in gold_rows if any(x[0] == "commute" for x in r["pred"]["conditions"])]
    res["commute_check"] = {
        **c,
        "pred_self_precision": round(c["pred_self_match_gold"] / c["pred_self"], 3),
        "pred_unknown_precision": round(c["pred_unknown_match_gold"] / c["pred_unknown"], 3) if c["pred_unknown"] else None,
        "rel_work_condition_precision": round(c["pred_rel_work_posts_gold_rel_work_self"] / c["pred_rel_work_posts"], 3),
        "users_with_pred_commute_condition": len(with_commute),
        "of_which_gold_has_commute_condition": sum(any(x[0] == "commute" for x in r["gold"]["conditions"])
                                                   for r in with_commute),
        "users_with_gold": len(gold_rows),
        "self_precision_by_type": a["self_precision_by_type"],
        "note": "정밀도 = 같은 글 · 같은 채널 골드 같은 유형(IoU ≥ 0.5 · 1:1)과 맞은 비율. 골드는 반복 언급을 다 라벨하지 않아 "
                "모든 유형이 낮게 나온다 — 유형끼리 견주는 용도",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return res


AXES7 = ("age", "sex", "location", "occupation", "family", "commute", "income")


def _stage2_rows(path: Path) -> dict[str, dict[str, bool]]:
    """stage2_preds.jsonl → {persona: {축: 기권인가}}. 사람이 겹치거나 축이 빠지면 멈춘다."""
    out: dict[str, dict[str, bool]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        u = row["persona_id"]
        assert u not in out, f"{path}: {u} 가 두 번 나온다"
        assert set(row["findings"]) >= set(AXES7), f"{path}: {u} 의 속성이 빠졌다"
        out[u] = {ax: row["findings"][ax]["verdict"] == "abstain" for ax in AXES7}
    return out


def consistency(dumps: dict[str, Path], stage2: dict[str, Path], out: Path) -> dict:
    """2단 판정(속성별 기권 여부) ↔ k 조건(그 축 조건이 있나)이 사용자 · 축마다 어긋나는 칸.

    2단은 다시 돌리지 않고 하류 러너가 저장한 stage2_preds.jsonl(모델 · 규칙)을 읽는다. 위치태그 조건은 2단 입력에도
    들어가므로(geo_tag) 위치 축도 같이 센다. 모델과 규칙의 기권 여부는 (사용자, 축) 칸끼리 직접 견준다.
    """
    s2 = {name: _stage2_rows(path) for name, path in stage2.items()}
    names = sorted(s2)
    for name in names[1:]:
        assert s2[name].keys() == s2[names[0]].keys(), "2단 결과의 사람 목록이 다르다"
    res: dict = {"stage2_abstain_cells_differ": {
        f"{a}_vs_{b}": sorted(f"{u}.{ax}" for u in s2[a] for ax in AXES7 if s2[a][u][ax] != s2[b][u][ax])
        for i, a in enumerate(names) for b in names[i + 1:]}}
    for dname, dpath in dumps.items():
        users = _users(json.loads(Path(dpath).read_text(encoding="utf-8")))
        for sname in names:
            assert s2[sname].keys() == users.keys(), f"{sname}: 2단과 dump 의 사람 목록이 다르다"
            cnt: Counter = Counter()
            cells: dict[str, list[str]] = defaultdict(list)
            for u, verdicts in sorted(s2[sname].items()):
                have = {c[0] for c in users[u]["pred_all"]["conditions"]}
                for ax in AXES7:
                    cnt["cells"] += 1
                    if verdicts[ax] and ax in have:
                        cells["abstain_but_k_condition"].append(f"{u}.{ax}")
                    elif not verdicts[ax] and ax not in have:
                        cells["judged_but_no_k_condition"].append(f"{u}.{ax}")
            for kind, lst in cells.items():
                cnt[kind] = len(lst)
                for c in lst:
                    cnt[f"{kind}.{c.split('.')[1]}"] += 1
            res[f"{dname}|stage2_{sname}"] = {**dict(sorted(cnt.items())), "cells": dict(cells)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--preds", required=True, type=Path)
    d.add_argument("--out", required=True, type=Path)
    c = sub.add_parser("compare")
    c.add_argument("--before", required=True, type=Path)
    c.add_argument("--after", required=True, type=Path)
    c.add_argument("--out", required=True, type=Path)
    s = sub.add_parser("consistency")
    s.add_argument("--before", required=True, type=Path)
    s.add_argument("--after", required=True, type=Path)
    s.add_argument("--stage2-model", required=True, type=Path, help="하류 러너 downstream/stage2/stage2_preds.jsonl")
    s.add_argument("--stage2-rules", required=True, type=Path, help="하류 러너 downstream_rules/stage2/stage2_preds.jsonl")
    s.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    if a.cmd == "dump":
        dump(a.preds, a.out)
    elif a.cmd == "consistency":
        r = consistency({"before": a.before, "after": a.after},
                        {"model": a.stage2_model, "rules": a.stage2_rules}, a.out)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(compare(a.before, a.after, a.out), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
