"""exp30 — 학생 분류기: 1단 후보 하나를 문맥과 함께 보고 self · other · unknown · drop 을 고른다 (README §3). GPU 서버에서 돈다.

    export PYTHONIOENCODING=utf-8 PYTHONPATH=src
    python experiments/exp30-review-distill/student.py train --sets pool,aug --out <저장 폴더>
    python experiments/exp30-review-distill/student.py apply --model <저장 폴더> --tag S1 --sets d1c,d4   # results/a0_{set} → results/S1_{set}

입력 = 「[유형] 앞 문장 + 스팬 문장(스팬을 ⟦ ⟧ 로 표시) + 뒤 문장」 · 최대 256토큰.
학습 · 고르기 나눔은 글 단위(seed 20261019 · 10%). 문턱 없이 argmax 로 적용한다(D1c · D4 로 고르지 않는다).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

import common

BASE = "monologg/koelectra-base-v3-discriminator"
SEED = 20261019
MAXLEN = 256
_CUT = re.compile(r"(?<=[.!?…~])\s+|\n+")


def context(body: str, s: dict) -> str:
    """스팬이 든 문장과 앞뒤 한 문장씩."""
    marked = body[:s["start"]] + "⟦" + body[s["start"]:s["end"]] + "⟧" + body[s["end"]:]
    sents = [x for x in _CUT.split(marked) if x.strip()]
    at = next(i for i, x in enumerate(sents) if "⟦" in x)
    return f"[{s['type']}] " + " ".join(sents[max(0, at - 1): at + 2])


def examples(name: str) -> list[tuple[str, str, int]]:
    """[(post_id, 입력, 라벨 번호)] — 교사 판정이 있는 후보만."""
    body = {r["post_id"]: r["body"] for r in common.load(name)}
    a0 = {json.loads(l)["post_id"]: json.loads(l)["spans"] for l in open(common.HERE / "results" / f"a0_{name}.jsonl", encoding="utf-8")}
    out = []
    for line in open(common.HERE / "results" / f"teacher_{name}.jsonl", encoding="utf-8"):
        d = json.loads(line)
        if "post_id" not in d or d["decisions"] is None:
            continue
        for s, lab in zip(a0[d["post_id"]], d["decisions"]):
            out.append((d["post_id"], context(body[d["post_id"]], s), common.LABELS.index(lab)))
    return out


def macro_f1(gold: list[int], pred: list[int]) -> float:
    f1s = []
    for k in range(4):
        tp = sum(g == k and p == k for g, p in zip(gold, pred))
        fp = sum(g != k and p == k for g, p in zip(gold, pred))
        fn = sum(g == k and p != k for g, p in zip(gold, pred))
        f1s.append(2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0)
    return sum(f1s) / 4


def train(a) -> None:
    import numpy as np
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

    torch.manual_seed(SEED)
    rows = [r for name in a.sets.split(",") for r in examples(name)]
    posts = sorted({r[0] for r in rows})
    dev_posts = set(random.Random(SEED).sample(posts, max(1, len(posts) // 10)))
    tr = [r for r in rows if r[0] not in dev_posts]
    dv = [r for r in rows if r[0] in dev_posts]
    print(f"학습 {len(tr)} · 고르기 {len(dv)} · 라벨 분포 {np.bincount([r[2] for r in rows], minlength=4).tolist()}", flush=True)
    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForSequenceClassification.from_pretrained(BASE, num_labels=4).cuda()
    counts = np.bincount([r[2] for r in tr], minlength=4) + 1
    weight = torch.tensor((counts.sum() / (4 * counts)) ** 0.5, dtype=torch.float).cuda()   # 드문 라벨(drop · unknown)에 가중
    loss_fn = torch.nn.CrossEntropyLoss(weight=weight)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-5, weight_decay=0.01)
    bs, epochs = 16, 5
    steps = epochs * ((len(tr) + bs - 1) // bs)
    sched = get_linear_schedule_with_warmup(opt, int(0.1 * steps), steps)

    def batches(data, shuffle):
        idx = list(range(len(data)))
        if shuffle:
            random.Random(SEED + len(data)).shuffle(idx)
        for i in range(0, len(idx), bs):
            b = [data[j] for j in idx[i:i + bs]]
            enc = tok([x[1] for x in b], truncation=True, max_length=MAXLEN, padding=True, return_tensors="pt").to("cuda")
            yield enc, torch.tensor([x[2] for x in b]).cuda()

    best, out = -1.0, Path(a.out)
    for ep in range(epochs):
        model.train()
        for enc, y in batches(tr, True):
            loss = loss_fn(model(**enc).logits, y)
            loss.backward()
            opt.step(); sched.step(); opt.zero_grad()
        model.eval()
        pred, gold = [], []
        with torch.no_grad():
            for enc, y in batches(dv, False):
                pred += model(**enc).logits.argmax(-1).tolist(); gold += y.tolist()
        f1 = macro_f1(gold, pred)
        print(f"epoch {ep + 1} 고르기 macro-F1 {f1:.3f}", flush=True)
        if f1 > best:
            best = f1
            model.save_pretrained(out); tok.save_pretrained(out)
    (out / "train_meta.json").write_text(json.dumps({"base": BASE, "sets": a.sets, "train": len(tr), "dev": len(dv), "best_dev_macro_f1": round(best, 4),
                                                     "prompt_hash": common.PROMPT_HASH}, ensure_ascii=False, indent=1), encoding="utf-8")


def apply(a) -> None:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForSequenceClassification.from_pretrained(a.model).to(a.device).eval()
    for name in a.sets.split(","):
        body = {r["post_id"]: r["body"] for r in common.load(name)}
        with open(common.HERE / "results" / f"{a.tag}_{name}.jsonl", "w", encoding="utf-8", newline="\n") as f:
            for line in open(common.HERE / "results" / f"a0_{name}.jsonl", encoding="utf-8"):
                r = json.loads(line)
                t = time.perf_counter()
                dec = []
                if r["spans"]:
                    enc = tok([context(body[r["post_id"]], s) for s in r["spans"]], truncation=True, max_length=MAXLEN,
                              padding=True, return_tensors="pt").to(a.device)
                    with torch.no_grad():
                        dec = [common.LABELS[i] for i in model(**enc).logits.argmax(-1).tolist()]
                spans = common.apply(r["spans"], dec)
                f.write(json.dumps({"post_id": r["post_id"], "spans": spans, "decisions": dec,
                                    "sec": round(time.perf_counter() - t + r.get("sec", 0), 3)}, ensure_ascii=False) + "\n")
        print(name, "done", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("train"); p1.add_argument("--sets", default="pool,aug"); p1.add_argument("--out", required=True)
    p2 = sub.add_parser("apply"); p2.add_argument("--model", required=True); p2.add_argument("--tag", default="S1")
    p2.add_argument("--sets", default="d1c,d4"); p2.add_argument("--device", default="cuda")
    a = ap.parse_args()
    {"train": train, "apply": apply}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
