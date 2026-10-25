"""exp41 — 1단 정밀도 규칙 세 개(C1 조각 버림 · C2 「X 안에서」 다듬기 · C3 모델이 안 본 규칙 지명 버림)를 test 밖 골드로 잰다.

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp41-precision-rules/measure.py \\
        --checkpoint <1단 v2 폴더> [--cache <raw 저장 경로 · 저장소 밖>]

1단 v2 를 test 밖 골드 글 전부에 돌려(임계값 0.7 · 앱과 같다) 병합 전 모델 후보와 모델이 본 스팬 전부(겹침 해소 전)를 얻고,
규칙을 끈 병합(= main) · 규칙 하나씩 · 셋 다 켠 병합을 같은 후보로 채점한다.
채점은 partial match — 같은 유형 · IoU ≥ 0.5 · 일대일(IoU 큰 쌍부터) · 채널별 (label-schema §2).

test 255편(splits/test_post_ids.json["post_ids"])은 읽자마자 뺀다 — 추론도 하지 않는다.
골드는 gold/*_spans.jsonl 만(gold/blind/ 는 하위 폴더라 안 잡힌다). 판정셋 exp17b · exp17c 는 여기서 보지 않는다.
"""
import argparse
import glob
import hashlib
import json
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from kopl.c1_span import rules
from kopl.c1_span.bio import span_iou

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORPUS = ROOT / "data/corpus/v0"
TEST = set(json.load(open(CORPUS / "splits/test_post_ids.json", encoding="utf-8"))["post_ids"])
assert len(TEST) == 255
THRESHOLD = 0.7   # 앱 _MIN_SPAN_SCORE 와 같다 — 바꾸지 않는다


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def ctx(text, start, end, n=10):
    return (text[max(0, start - n):start] + "⟦" + text[start:end] + "⟧" + text[end:end + n]).replace("\n", "⏎")


def gold_posts():
    out = {}
    for f in sorted(glob.glob(str(CORPUS / "gold/*_spans.jsonl"))):
        for d in jl(f):
            pid = d.get("post_id")
            if pid and pid not in TEST and "texts" in d:
                out[pid] = d
    assert not set(out) & TEST
    return out


def fingerprint(checkpoint, posts):
    """캐시가 어떤 추론인지 — 체크포인트(경로 · 폴더 안 파일 전부의 SHA-256: 가중치 · config · 토크나이저) · 임계값 · 입력 글(post_id + texts) 해시 · raw 형식."""
    ck = Path(checkpoint).resolve()
    weights = {}
    for w in sorted(x for x in ck.iterdir() if x.is_file()):
        h = hashlib.sha256()
        with open(w, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        weights[w.name] = h.hexdigest()
    inputs = hashlib.sha256(json.dumps([[pid, posts[pid]["texts"]] for pid in sorted(posts)],
                                       ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {"checkpoint": str(ck), "files_sha256": weights, "threshold": THRESHOLD, "inputs_sha256": inputs,
            "raw_format": "candidates+model_seen_spans(pre-overlap)"}


def infer_raw(checkpoint, posts, cache):
    """post_id → predict_raw 결과(candidates · model_seen_spans). cache 가 있으면 이어 쓴다.

    캐시 첫 줄에 fingerprint 를 적고, 다시 쓸 때 다르면(체크포인트 · 임계값 · 입력 · 형식) 멈춘다 — Codex 검토."""
    fp = fingerprint(checkpoint, posts)
    raw = {}
    if cache and Path(cache).exists():
        rows = jl(cache)
        if not rows or rows[0].get("fingerprint") != fp:
            raise SystemExit(f"캐시 {cache} 의 fingerprint 가 이번 실행과 다르다 — 다른 경로를 주거나 지우고 다시 돌린다")
        raw = {d["post_id"]: d for d in rows[1:]}
    todo = [pid for pid in posts if pid not in raw]
    if todo:
        from kopl.c1_span.infer import SpanDetector
        det = SpanDetector(checkpoint, min_span_score=THRESHOLD)
        new_file = bool(cache) and not Path(cache).exists()
        f = open(cache, "a", encoding="utf-8") if cache else None
        if new_file:
            f.write(json.dumps({"fingerprint": fp}, ensure_ascii=False) + "\n")
        for n, pid in enumerate(todo, 1):
            r = det.predict_raw({"post_id": pid, "texts": posts[pid]["texts"]})
            raw[pid] = {"post_id": pid, "candidates": r["candidates"], "model_seen_spans": r["model_seen_spans"]}
            if f:
                f.write(json.dumps(raw[pid], ensure_ascii=False) + "\n")
            if n % 200 == 0:
                print(n, len(todo), flush=True)
                if f:
                    f.flush()
        if f:
            f.close()
    return raw, fp


@contextmanager
def configured(c1, c2, c3):
    """규칙을 끄고 켠다 — 끈 것은 main 과 같은 동작이다(규칙 함수만 바꿔 끼운다)."""
    saved = rules.is_fragment_span, rules.trim_admin_inside
    if not c1:
        rules.is_fragment_span = lambda text: False
    if not c2:
        rules.trim_admin_inside = lambda text: None
    try:
        yield c3
    finally:
        rules.is_fragment_span, rules.trim_admin_inside = saved


def match(g, p):
    cand = sorted(((span_iou(a, b), i, j) for i, a in enumerate(g) for j, b in enumerate(p)
                   if a[2] == b[2] and span_iou(a, b) >= 0.5), reverse=True)
    ug, up = {}, {}
    for _, i, j in cand:
        if i not in ug and j not in up:
            ug[i] = j
            up[j] = i
    return ug, up


def merged_all(posts, raw, c1, c2, c3):
    det = rules.ExplicitRules()
    out, stats = {}, Counter()
    with configured(c1, c2, c3):
        for pid, d in posts.items():
            r = raw[pid]
            out[pid], st = rules.merge_with_model(pid, d["texts"], r["candidates"], det,
                                                  r["model_seen_spans"] if c3 else None)
            stats.update(st)
    return out, stats


def score(posts, merged):
    tot, by_type = Counter(), {}
    tp_keys, gold_hit = set(), set()
    for pid, d in posts.items():
        for tid in d["texts"]:
            g = sorted({(s["start"], s["end"], s["type"]) for s in d["spans"] if s.get("text_id", "body") == tid})
            p = [(s["start"], s["end"], s["type"]) for s in merged[pid] if s["text_id"] == tid]
            ug, up = match(g, p)
            tot["tp"] += len(ug)
            tot["fp"] += len(p) - len(up)
            tot["fn"] += len(g) - len(ug)
            for i, a in enumerate(g):
                by_type.setdefault(a[2], Counter())["tp" if i in ug else "fn"] += 1
                if i in ug:
                    gold_hit.add((pid, tid) + a)
            for j, b in enumerate(p):
                if j in up:
                    tp_keys.add((pid, tid) + b)
                else:
                    by_type.setdefault(b[2], Counter())["fp"] += 1
    P = tot["tp"] / max(1, tot["tp"] + tot["fp"])
    R = tot["tp"] / max(1, tot["tp"] + tot["fn"])
    F = 2 * P * R / (P + R) if P + R else 0.0
    return ({**tot, "precision": round(P, 4), "recall": round(R, 4), "f1": round(F, 4),
             "by_type": {k: dict(v) for k, v in sorted(by_type.items())}}, tp_keys, gold_hit)


def diff(posts, before, after, tp_before, gold_before, gold_after):
    """규칙 전후로 바뀐 스팬 전부 — 사라진 것 · 새로 생긴 것 · 잃은 골드 · 새로 맞은 골드."""
    removed, added = [], []
    for pid, d in posts.items():
        kb = {(s["text_id"], s["start"], s["end"], s["type"]): s for s in before[pid]}
        ka = {(s["text_id"], s["start"], s["end"], s["type"]): s for s in after[pid]}
        for k in sorted(set(kb) - set(ka)):
            removed.append({"post_id": pid, "text_id": k[0], "type": k[3], "text": kb[k]["text"],
                            "source": "model" if "score" in kb[k] else "rule",
                            "was_tp": (pid,) + k in tp_before, "ctx": ctx(d["texts"][k[0]], k[1], k[2])})
        for k in sorted(set(ka) - set(kb)):
            added.append({"post_id": pid, "text_id": k[0], "type": k[3], "text": ka[k]["text"],
                          "ctx": ctx(d["texts"][k[0]], k[1], k[2])})

    def rows(keys):
        return [{"post_id": k[0], "text_id": k[1], "type": k[4], "text": posts[k[0]]["texts"][k[1]][k[2]:k[3]]}
                for k in sorted(keys)]
    return {"removed": removed, "added": added, "gold_lost": rows(gold_before - gold_after),
            "gold_gained": rows(gold_after - gold_before)}


CONFIGS = {"main": (False, False, False), "C1": (True, False, False), "C2": (False, True, False),
           "C3": (False, False, True), "C1+C2": (True, True, False), "C1+C2+C3": (True, True, True)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--cache", help="raw 후보 jsonl (저장소 밖 · 있으면 다시 추론하지 않는다)")
    a = ap.parse_args()
    posts = gold_posts()
    raw, fp = infer_raw(a.checkpoint, posts, a.cache)
    base, _ = merged_all(posts, raw, *CONFIGS["main"])
    base_score, tp_base, gold_base = score(posts, base)
    summary = {"checkpoint": a.checkpoint, "threshold": THRESHOLD, "fingerprint": fp, "posts": len(posts),
               "gold_spans": sum(len(d["spans"]) for d in posts.values()),
               "model_candidates": sum(len(r["candidates"]) for r in raw.values()),
               "model_seen_spans": sum(len(r["model_seen_spans"]) for r in raw.values()),
               "configs": {}}
    changes = {}
    for name, cfg in CONFIGS.items():
        merged, stats = merged_all(posts, raw, *cfg)
        sc, _, gold_hit = score(posts, merged)
        d = diff(posts, base, merged, tp_base, gold_base, gold_hit)
        summary["configs"][name] = {**sc, "removed_or_changed": len(d["removed"]),
                                    "removed_was_tp": sum(r["was_tp"] for r in d["removed"]),
                                    "gold_lost": len(d["gold_lost"]), "gold_gained": len(d["gold_gained"]),
                                    "merge_stats": {k: v for k, v in stats.items() if k.startswith(("model_", "rule_"))}}
        if name != "main":
            changes[name] = d
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results/dev_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (HERE / "results/dev_changes.json").write_text(json.dumps(changes["C1+C2+C3"], ensure_ascii=False, indent=1) + "\n",
                                                  encoding="utf-8")
    for name, c in summary["configs"].items():
        print(f"{name:9s} tp {c['tp']} fp {c['fp']} fn {c['fn']} P {c['precision']} R {c['recall']} F1 {c['f1']} "
              f"| 바뀐 {c['removed_or_changed']} (TP {c['removed_was_tp']}) 잃은 골드 {c['gold_lost']} 새 골드 {c['gold_gained']}")


if __name__ == "__main__":
    main()
