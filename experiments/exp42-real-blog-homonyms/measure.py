"""exp42 — 실제 블로그 오탐에서 나온 좁은 규칙 네 가지를 test 밖 골드로 잰다.

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp42-real-blog-homonyms/measure.py \\
        --checkpoint <1단 v2 폴더> [--cache <raw 저장 경로 · 저장소 밖>]

- R1 동형이의어 지명(음성 · 공주 · 예산 · 장수 · 해보면 · 강하면): 지명 문맥이 없으면 규칙 · 모델 LOC_ADMIN 후보에서 뺀다 (rules)
- R2 「N세의 + 다른 사람」: AGE 의 subject 를 other 로 (attributes)
- R3 반사실 가정 「만약 … -었다면」 안의 모델 JOB 후보를 뺀다 (rules)
- R4 셋 이상 나열한 지명: LOC_ADMIN 의 subject 를 unknown 으로 (attributes)

R1 · R3 은 스팬을 바꾸므로 스팬 채점(partial match · 같은 유형 · IoU ≥ 0.5 · 일대일 · 채널별 — label-schema §2)으로,
R2 · R4 는 subject 만 바꾸므로 맞은 스팬(TP)의 subject 일치로 잰다. 끈 규칙은 main 과 같은 동작이다(함수 · 플래그만 바꿔 끼운다).

모델 후보 추론 · 골드 읽기 · 채점은 exp41 measure.py 를 그대로 불러 쓴다 — test 255편은 거기서 읽자마자 빠진다
(splits/test_post_ids.json["post_ids"] · 길이 255 assert). gold/blind/ 는 하위 폴더라 안 잡힌다. 판정셋 exp17b · exp17c 는 보지 않는다.
"""
import argparse
import importlib.util
import json
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from kopl.c1_span import attributes, rules

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("exp41_measure", HERE.parent / "exp41-precision-rules" / "measure.py")
exp41 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(exp41)
assert len(exp41.TEST) == 255

ADOPTED_WORDS = rules._COMMON_WORD_PLACES

# R1 후보 — 사전의 시군구 약칭 256개 · 두 글자 지명 49개를 다 훑어 일반 낱말로도 읽히는 것 + 「동사 + -면」 꼴 면 이름 (README §1).
# 하나씩 켜 test 밖 골드에서 잃는 골드가 0 인 것만 rules._COMMON_WORD_PLACES 에 넣는다
CANDIDATES = {
    "시군구 약칭": "강진 강화 거창 경주 고령 고성 곡성 공주 관악 광명 광산 구리 구미 기장 남동 남해 단원 대구 대덕 대전 동남 동해 "
               "만세 무안 보은 봉화 부산 부여 분당 사상 사천 상당 상록 상주 서북 서원 서해 성산 성주 세종 수성 수영 수원 "
               "수지 신안 양산 양주 여수 여주 연수 영광 영양 영주 예산 오산 완주 용인 원주 유성 음성 이천 인제 장성 장수 "
               "장안 정선 제천 중원 진주 청원 청주 팔달 함양 효행".split(),
    "두 글자 지명": "변동 연동 상동 중동 학동 신동 대동 일동 서구 북구 파동 능동 양동 사동 금동 목동".split(),
    "「동사+면」 면 이름": "강하면 해보면 마리면 부리면 보안면".split(),
}


@contextmanager
def configured(r1, r2, r3, r4, words=None):
    saved = (rules._COMMON_WORD_PLACES, rules.is_model_homonym_place, rules.is_counterfactual,
             attributes._RULE_AGE_OTHER, attributes._RULE_ADMIN_LIST)
    if words is not None:
        rules._COMMON_WORD_PLACES = frozenset(words)
    if not r1:   # main 동작 — 진도 · 달성만 규칙에서 거르고, 모델 후보는 거르지 않는다
        rules._COMMON_WORD_PLACES = frozenset()
        rules.is_model_homonym_place = lambda text, start, end: False
    if not r3:
        rules.is_counterfactual = lambda text, start, end: False
    attributes._RULE_AGE_OTHER = r2
    attributes._RULE_ADMIN_LIST = r4
    try:
        yield
    finally:
        (rules._COMMON_WORD_PLACES, rules.is_model_homonym_place, rules.is_counterfactual,
         attributes._RULE_AGE_OTHER, attributes._RULE_ADMIN_LIST) = saved


def candidate_scan(posts, raw):
    """R1 후보를 하나씩만 켜고(다른 R 은 끔) 그 낱말이 든 글만 다시 병합 · 채점한다 — 후보별 줄어든 FP · 잃은 골드."""
    rows = []
    for group, words in CANDIDATES.items():
        for w in words:
            sub = {pid: d for pid, d in posts.items() if any(w in t for t in d["texts"].values())}
            if not sub:
                rows.append({"word": w, "group": group, "posts": 0, "fp_removed": 0, "gold_lost": 0, "gold_direct": 0})
                continue
            before, _, _ = merged_all(sub, raw, (False, False, False, False))
            after, _, _ = merged_all(sub, raw, (True, False, False, False), words=[w])
            sb, tp_b, gb = exp41.score(sub, before)
            sa, _, ga = exp41.score(sub, after)
            d = exp41.diff(sub, before, after, tp_b, gb, ga)
            direct = 0
            with configured(True, False, False, False, words=[w]):
                for pid, dd in sub.items():
                    for s in dd["spans"]:
                        if s["type"] == "LOC_ADMIN" and rules.is_model_homonym_place(
                                dd["texts"][s.get("text_id", "body")], s["start"], s["end"]):
                            direct += 1
            rows.append({"word": w, "group": group, "posts": len(sub), "fp_removed": sb["fp"] - sa["fp"],
                         "removed": len(d["removed"]), "gold_lost": len(d["gold_lost"]), "gold_direct": direct,
                         "removed_ctx": [r["ctx"] for r in d["removed"]][:5]})
    return rows


_DET = None


def merged_all(posts, raw, cfg, words=None):
    global _DET
    det = _DET = _DET or rules.ExplicitRules()
    out, stats, subj = {}, Counter(), {}
    with configured(*cfg, words=words):
        for pid, d in posts.items():
            out[pid], st = rules.merge_with_model(pid, d["texts"], raw[pid]["candidates"], det)
            stats.update(st)
            for s in out[pid]:
                subj[(pid, s["text_id"], s["start"], s["end"], s["type"])] = attributes.resolve(d["texts"], s)["subject"]
    return out, stats, subj


def subject_pairs(posts, merged):
    """TP 짝 — (pid, tid, gold 시작 · 끝 · 유형) → (pred 키, gold subject)."""
    pairs = {}
    for pid, d in posts.items():
        for tid in d["texts"]:
            gs = sorted({(s["start"], s["end"], s["type"], s.get("subject", "self"))
                         for s in d["spans"] if s.get("text_id", "body") == tid})
            g = [x[:3] for x in gs]
            p = [(s["start"], s["end"], s["type"]) for s in merged[pid] if s["text_id"] == tid]
            ug, _ = exp41.match(g, p)
            for i, j in ug.items():
                pairs[(pid, tid) + g[i]] = ((pid, tid) + p[j], gs[i][3])
    return pairs


def subject_score(posts, pairs, subj, base_pairs, base_subj):
    agree = sum(subj[pk] == gsub for pk, gsub in pairs.values())
    lost, fixed, changed = [], [], 0
    for gk, (pk, gsub) in pairs.items():
        if gk not in base_pairs:
            continue
        bpk, _ = base_pairs[gk]
        before, after = base_subj[bpk], subj[pk]
        if before != after:
            changed += 1
            row = {"post_id": gk[0], "type": gk[4], "gold_subject": gsub, "before": before, "after": after,
                   "text": posts[gk[0]]["texts"][gk[1]][gk[2]:gk[3]]}
            if before == gsub:
                lost.append(row)
            elif after == gsub:
                fixed.append(row)
    return {"tp_pairs": len(pairs), "subject_agree": agree, "subject_acc": round(agree / max(1, len(pairs)), 4),
            "tp_subject_changed": changed, "subject_gold_lost": lost, "subject_gold_fixed": fixed}


def self_count(subj, types=("AGE", "LOC_ADMIN", "JOB")):
    c = Counter()
    for k, v in subj.items():
        if k[4] in types and v == "self":
            c[k[4]] += 1
    return dict(c)


def gold_direct(posts):
    """모델 출력과 상관없이 골드 스팬 자체에 규칙을 걸어 본다 — 골드가 이 규칙에 걸리면 그만큼 잃을 수 있다.

    R1 · R3: 골드 스팬이 버림 조건에 맞는 수. R2 · R4: 골드 스팬을 후보로 넣었을 때 subject 가 main 과 달라지는 수(골드 subject 별)."""
    out = {"R1_gold_admin_homonym_dropped": [], "R3_gold_job_counterfactual": [], "R2_R4_subject_changed": []}
    for pid, d in posts.items():
        for s in d["spans"]:
            tid = s.get("text_id", "body")
            text = d["texts"][tid]
            cand = {**s, "text_id": tid}
            if s["type"] == "LOC_ADMIN" and rules.is_model_homonym_place(text, s["start"], s["end"]):
                out["R1_gold_admin_homonym_dropped"].append({"post_id": pid, "text": s["text"]})
            if s["type"] == "JOB" and rules.is_counterfactual(text, s["start"], s["end"]):
                out["R3_gold_job_counterfactual"].append({"post_id": pid, "text": s["text"]})
            with configured(*CONFIGS["main"]):
                before = attributes.resolve(d["texts"], cand)["subject"]
            with configured(*CONFIGS["R1+R2+R3+R4"]):
                after = attributes.resolve(d["texts"], cand)["subject"]
            if before != after:
                out["R2_R4_subject_changed"].append({"post_id": pid, "type": s["type"], "text": s["text"],
                                                     "gold_subject": s.get("subject"), "before": before, "after": after})
    return out


CONFIGS = {"main": (False, False, False, False), "R1": (True, False, False, False), "R2": (False, True, False, False),
           "R3": (False, False, True, False), "R4": (False, False, False, True),
           "R1+R2+R3": (True, True, True, False), "R1+R2+R3+R4": (True, True, True, True)}
CONFIGS["ALL"] = CONFIGS["R1+R2+R3+R4"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--cache", help="raw 후보 jsonl (저장소 밖 · exp41 형식 · 있으면 다시 추론하지 않는다)")
    a = ap.parse_args()
    posts = exp41.gold_posts()
    raw, fp = exp41.infer_raw(a.checkpoint, posts, a.cache)
    base, _, base_subj = merged_all(posts, raw, CONFIGS["main"])
    _, tp_base, gold_base = exp41.score(posts, base)
    base_pairs = subject_pairs(posts, base)
    summary = {"checkpoint": a.checkpoint, "threshold": exp41.THRESHOLD, "fingerprint": fp, "posts": len(posts),
               "gold_spans": sum(len(d["spans"]) for d in posts.values()),
               "model_candidates": sum(len(r["candidates"]) for r in raw.values()), "configs": {}}
    changes = {}
    for name, cfg in CONFIGS.items():
        merged, stats, subj = merged_all(posts, raw, cfg)
        sc, _, gold_hit = exp41.score(posts, merged)
        d = exp41.diff(posts, base, merged, tp_base, gold_base, gold_hit)
        pairs = subject_pairs(posts, merged)
        ss = subject_score(posts, pairs, subj, base_pairs, base_subj)
        subj_changed_pred = []
        for k, v in subj.items():
            if k in base_subj and base_subj[k] != v:
                subj_changed_pred.append({"post_id": k[0], "type": k[4], "before": base_subj[k], "after": v,
                                          "ctx": exp41.ctx(posts[k[0]]["texts"][k[1]], k[2], k[3])})
        summary["configs"][name] = {
            **{k: v for k, v in sc.items() if k != "by_type"},
            "removed_or_changed": len(d["removed"]), "removed_was_tp": sum(r["was_tp"] for r in d["removed"]),
            "gold_lost": len(d["gold_lost"]), "gold_gained": len(d["gold_gained"]),
            "subject_acc": ss["subject_acc"], "subject_agree": ss["subject_agree"], "tp_pairs": ss["tp_pairs"],
            "pred_subject_changed": len(subj_changed_pred),
            "subject_gold_lost": len(ss["subject_gold_lost"]), "subject_gold_fixed": len(ss["subject_gold_fixed"]),
            "self_preds": self_count(subj),
            "merge_stats": {k: v for k, v in stats.items() if k.startswith("model_homonym") or k.startswith("model_counter")},
        }
        if name != "main":
            changes[name] = {**d, "subject_changed": subj_changed_pred,
                             "subject_gold_lost": ss["subject_gold_lost"], "subject_gold_fixed": ss["subject_gold_fixed"]}
    scan = candidate_scan(posts, raw)
    adopted = sorted(r["word"] for r in scan if r["gold_lost"] == 0 and r["gold_direct"] == 0)
    summary["r1_candidates"] = {"adopted_rule": "test 밖 골드에서 잃은 골드 0 · 골드 LOC_ADMIN 스팬에 직접 걸어도 0",
                                "adopted": adopted, "in_code": sorted(ADOPTED_WORDS),
                                "rows": [{k: v for k, v in r.items() if k != "removed_ctx"} for r in scan]}
    changes["r1_candidates"] = scan
    for r in scan:
        print(f"  {r['group']:10s} {r['word']:4s} 글 {r['posts']:4d} FP- {r['fp_removed']:3d} 잃은 {r['gold_lost']} 직접 {r['gold_direct']}")
    print("채택 가능:", " ".join(adopted))
    print("코드에 든 것:", " ".join(sorted(ADOPTED_WORDS)))
    gd = gold_direct(posts)
    summary["gold_direct"] = {k: len(v) for k, v in gd.items()}
    changes["gold_direct"] = gd
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results/dev_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (HERE / "results/dev_changes.json").write_text(json.dumps(changes, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for name, c in summary["configs"].items():
        print(f"{name:12s} tp {c['tp']} fp {c['fp']} fn {c['fn']} F1 {c['f1']} | 바뀐 {c['removed_or_changed']} "
              f"(TP {c['removed_was_tp']}) 잃은 골드 {c['gold_lost']} 새 골드 {c['gold_gained']} | subject "
              f"{c['subject_acc']} 바뀐 예측 {c['pred_subject_changed']} 잃은 {c['subject_gold_lost']} 고친 {c['subject_gold_fixed']}")
    print("골드 스팬에 직접 건 결과:", summary["gold_direct"])


if __name__ == "__main__":
    main()
