"""exp40 — 「N일차 · N주차 · N년차 · N회차」의 「차」를 COMMUTE 에서 버리는 규칙(#385 3-1)이 무엇을 버리나.

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp40-ordinal-cha/measure.py saved
    PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp40-ordinal-cha/measure.py run --checkpoint <1단 v2 폴더>

saved — ① test 밖 골드에서 규칙에 걸리는 골드 스팬 ② 저장소에 저장된 1단 예측에서 버려지는 스팬
run   — ③ 1단 v2 를 test 밖 코퍼스 글 전부에 다시 돌려 병합 전 모델 후보에서 버려지는 스팬

test 255편(splits/test_post_ids.json["post_ids"])은 읽자마자 뺀다 — 예측도 하지 않고 본문도 열지 않는다.
골드는 exp39(#384)와 같이 gold/*_spans.jsonl 만 본다(gold/blind/ 는 보지 않는다).
판정 · 채점용 셋(exp17b · exp17c · exp17d)은 보지 않는다.
"""
import argparse
import glob
import json
import re
from pathlib import Path

from kopl.c1_span.rules import is_ordinal_cha

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP = ROOT / "experiments"
CORPUS = ROOT / "data/corpus/v0"
TEST = set(json.load(open(CORPUS / "splits/test_post_ids.json", encoding="utf-8"))["post_ids"])
assert len(TEST) == 255
HELD_OUT = {"exp17b-heldout-eval", "exp17c-final-eval", "exp17d-job-eval"}
# 1단 출력(모델 + 규칙 병합 · 리뷰 전)만 — A_ · S1 · T3 · AX · B_ · r1 은 2단 리뷰 · 증류 출력이라 뺀다
SAVED = (["exp24-cpu-accel/results/preds_dev_fp32.jsonl", "exp24-cpu-accel/results/preds_exp17_fp32.jsonl",
          "exp27-adversarial/results/preds.jsonl"]
         + sorted(str(Path(p).relative_to(EXP)).replace("\\", "/") for p in glob.glob(str(EXP / "*/results/a0_*.jsonl")))
         + ["exp39-commute-frag-shape/data/heldout/a0_h39.jsonl"])
ORDINAL_TEXT = re.compile(r"[0-9][일주회년]차")   # 골드 본문에 이 꼴이 몇 번 나오나(참고)


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def ctx(text, start, end, n=10):
    return (text[max(0, start - n):start] + "⟦" + text[start:end] + "⟧" + text[end:end + n]).replace("\n", "⏎")


def iou(a, b):
    return max(0, min(a["end"], b["end"]) - max(a["start"], b["start"])) / (max(a["end"], b["end"]) - min(a["start"], b["start"]))


def gold_by_post():
    out = {}
    for f in sorted(glob.glob(str(CORPUS / "gold/*_spans.jsonl"))):
        for d in jl(f):
            pid = d.get("post_id")
            if pid and pid not in TEST and "texts" in d:
                out[pid] = d.get("spans", [])
    return out


def gold_match(gold, pid, tid, span):
    """버린 스팬이 골드와 맞았나(같은 유형 · IoU ≥ 0.5 = 채점 기준) — 맞았다면 정탐을 잃는 것"""
    return any(g.get("text_id", "body") == tid and g["type"] == "COMMUTE" and iou(g, span) >= 0.5
               for g in gold.get(pid, []))


def corpus_posts():
    out = {}
    for f in sorted(glob.glob(str(CORPUS / "posts/*.jsonl"))):
        for r in jl(f):
            pid = r.get("post_id")
            if pid and pid not in TEST:
                out[pid] = r
    return out


def body_index():
    """post_id → 글 texts 후보들. 코퍼스(test 제외) + 실험 합성 글(판정셋 제외)."""
    idx = {pid: [r["texts"]] for pid, r in corpus_posts().items()}
    for f in glob.glob(str(EXP / "*/data/*posts*.jsonl")):
        if Path(f).parts[-3] in HELD_OUT:
            continue
        for r in jl(f):
            pid = r.get("post_id")
            if pid and pid not in TEST and "texts" in r:
                idx.setdefault(pid, []).append(r["texts"])
    return idx


def gold_check():
    gold_spans = commute = ordinal_dropped = 0
    dropped, cha_any, text_hits, text_hits_covered = [], [], 0, []
    for f in sorted(glob.glob(str(CORPUS / "gold/*_spans.jsonl"))):   # blind/ 는 하위 폴더라 안 잡힌다
        for d in jl(f):
            pid = d.get("post_id")
            if not pid or pid in TEST or "texts" not in d:
                continue
            for s in d.get("spans", []):
                gold_spans += 1
                text = d["texts"].get(s.get("text_id", "body"), "")
                if s["type"] == "COMMUTE":
                    commute += 1
                    if is_ordinal_cha(text, s["start"], s["end"]):
                        ordinal_dropped += 1
                        dropped.append({"post_id": pid, "ctx": ctx(text, s["start"], s["end"])})
                if s["text"] == "차":
                    cha_any.append({"post_id": pid, "type": s["type"], "ordinal": is_ordinal_cha(text, s["start"], s["end"]),
                                    "ctx": ctx(text, s["start"], s["end"])})
            for tid, text in d["texts"].items():
                for m in ORDINAL_TEXT.finditer(text):
                    text_hits += 1
                    c = m.end() - 1   # 「차」 자리
                    for s in d.get("spans", []):
                        if s.get("text_id", "body") == tid and s["start"] <= c < s["end"]:
                            text_hits_covered.append({"post_id": pid, "type": s["type"], "text": s["text"],
                                                      "ctx": ctx(text, m.start(), m.end())})
    return {"gold_spans": gold_spans, "gold_commute": commute, "gold_commute_dropped": ordinal_dropped,
            "dropped": dropped, "gold_spans_text_cha": cha_any,
            "ordinal_pattern_in_gold_texts": text_hits, "ordinal_pattern_covered_by_gold_span": text_hits_covered}


def saved_preds():
    idx = body_index()
    gold = gold_by_post()
    rows, per_file = [], {}
    for rel in SAVED:
        path = EXP / rel
        if not path.exists():
            continue
        n_commute = n_drop = 0
        for d in jl(path):
            pid = d.get("post_id")
            if not pid or pid in TEST:
                continue
            for s in d.get("spans", []):
                if s.get("type") != "COMMUTE":
                    continue
                n_commute += 1
                if s.get("text") != "차":
                    continue
                tid = s.get("text_id", "body")
                texts = next((t for t in idx.get(pid, []) if t.get(tid, "")[s["start"]:s["end"]] == "차"), None)
                if texts is None:
                    rows.append({"file": rel, "post_id": pid, "text_id": tid, "dropped": None, "ctx": "(본문 없음)"})
                    continue
                hit = is_ordinal_cha(texts[tid], s["start"], s["end"])
                n_drop += hit
                rows.append({"file": rel, "post_id": pid, "text_id": tid, "dropped": hit,
                             "in_gold_set": pid in gold, "gold_match": gold_match(gold, pid, tid, s),
                             "ctx": ctx(texts[tid], s["start"], s["end"])})
        per_file[rel] = {"commute": n_commute, "dropped": n_drop}
    return {"files": per_file, "commute_cha_spans": rows}


def run(checkpoint):
    from kopl.c1_span.infer import SpanDetector
    det = SpanDetector(checkpoint)
    posts = corpus_posts()
    gold = gold_by_post()
    n_commute, cha, dropped = 0, [], []
    for pid, r in posts.items():
        raw = det.predict_raw(r)
        for c in raw["candidates"]:
            if c["type"] != "COMMUTE":
                continue
            n_commute += 1
            if c["text"] == "차":
                row = {"post_id": pid, "text_id": c["text_id"], "ctx": ctx(raw["texts"][c["text_id"]], c["start"], c["end"]),
                       "dropped": is_ordinal_cha(raw["texts"][c["text_id"]], c["start"], c["end"]),
                       "in_gold_set": pid in gold, "gold_match": gold_match(gold, pid, c["text_id"], c)}
                cha.append(row)
                if row["dropped"]:
                    dropped.append(row)
    return {"checkpoint": str(checkpoint), "posts": len(posts), "model_commute_candidates": n_commute,
            "model_commute_cha": len(cha), "dropped": len(dropped),
            "dropped_gold_match": sum(r["gold_match"] for r in dropped), "commute_cha_rows": cha}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["saved", "run"])
    ap.add_argument("--checkpoint")
    a = ap.parse_args()
    (HERE / "results").mkdir(exist_ok=True)
    if a.mode == "saved":
        out = {"gold": gold_check(), "saved_preds": saved_preds()}
        name = "saved.json"
    else:
        out = run(a.checkpoint)
        name = "corpus_run.json"
    (HERE / "results" / name).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
