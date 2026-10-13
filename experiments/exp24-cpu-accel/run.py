"""exp24 — 1단 CPU 가속(동적 int8) 예측 · 지연을 앱 탐지 경로 그대로 잰다 (README §4).

    # 예측 (dev 골드 2,512편 + exp17 80편) — 구성마다 한 번
    PYTHONIOENCODING=utf-8 python experiments/exp24-cpu-accel/run.py preds --checkpoint <v2 폴더> --mode fp32 --threads 4
    PYTHONIOENCODING=utf-8 python experiments/exp24-cpu-accel/run.py preds --checkpoint <v2 폴더> --mode int8 --threads 4
    # 지연 (지연 20편) — 구성 × 스레드마다
    PYTHONIOENCODING=utf-8 python experiments/exp24-cpu-accel/run.py latency --checkpoint <v2 폴더> --mode int8 --threads 2
    # 채점 (README §5)
    PYTHONIOENCODING=utf-8 python experiments/exp24-cpu-accel/score.py

test(`splits/test_post_ids.json`) · exp17b · exp17c 는 읽지 않는다.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT / "src", ROOT / "experiments" / "exp06-finetune", ROOT / "apps" / "analyzer" / "engines"):
    sys.path.insert(0, str(p))

RESULTS = HERE / "results"
EXP17 = ROOT / "experiments" / "exp17-planted-eval" / "data" / "posts.jsonl"


def test_post_ids() -> set[str]:
    """test 255편. 파일은 메타 dict 이고 목록은 ``post_ids`` 다 — dict 를 그대로 set 으로 만들면 키 6개만 남는다."""
    ids = set(json.loads((ROOT / "data/corpus/v0/splits/test_post_ids.json").read_text(encoding="utf-8"))["post_ids"])
    if len(ids) != 255:
        raise ValueError(f"test 글 수가 255 가 아니다: {len(ids)}")
    return ids


def dev_gold_posts() -> dict[str, dict]:
    """코퍼스 v0 골드 중 test 가 아닌 글 → {post_id: {texts, spans}}."""
    test = test_post_ids()
    posts = {}
    for f in sorted(glob.glob(str(ROOT / "data/corpus/v0/gold/*_spans.jsonl"))):
        for line in open(f, encoding="utf-8"):
            row = json.loads(line)
            if "post_id" in row and row["post_id"] not in test:
                posts[row["post_id"]] = row
    return posts


def to_record(post_id: str, texts: dict[str, str]) -> dict:
    """채널 사전 → 앱 탐지 입력 (real.detect_spans 가 만드는 모양)."""
    record = {"post_id": post_id}
    for key in ("title", "body"):
        if texts.get(key):
            record[key] = texts[key]
    caps = sorted((int(k.split(":")[1]), v) for k, v in texts.items() if k.startswith("photo_caption:"))
    if caps:
        if [i for i, _ in caps] != list(range(len(caps))):
            raise ValueError(f"캡션 번호가 0부터 이어지지 않는다: {post_id}")
        record["photo_captions"] = [v for _, v in caps]
    return record


def load_detector(checkpoint: Path, mode: str, threads: int):
    import torch
    import infer

    torch.set_num_threads(threads)
    det = infer.SpanDetector(checkpoint, device="cpu", min_span_score=0.7)
    if mode == "int8":
        det.model = torch.quantization.quantize_dynamic(det.model, {torch.nn.Linear}, dtype=torch.qint8)
    elif mode != "fp32":
        raise ValueError(mode)
    return det


def app_detect(det, record: dict) -> dict:
    """앱과 같은 길 — c1_rules.detect(모델 + 명시 규칙 병합) + 규칙 level·subject 판정."""
    import c1_rules
    from kopl.c1_span.attributes import resolve

    if not c1_rules._ENABLED:
        raise RuntimeError("C1_RULES 가 꺼져 있다 — 앱 기본(켬)으로 잰다")
    return c1_rules.detect(det, record, resolve)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def meta(a, det) -> dict:
    import torch

    return {"mode": a.mode, "threads": a.threads, "torch": torch.__version__, "cpu": platform.processor(),
            "machine": platform.node(), "model_sha256": sha256(Path(a.checkpoint) / "model.safetensors"),
            "model_version": det.version, "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def cmd_preds(a) -> None:
    det = load_detector(Path(a.checkpoint), a.mode, a.threads)
    RESULTS.mkdir(exist_ok=True)
    jobs = [("dev", {pid: row["texts"] for pid, row in dev_gold_posts().items()}),
            ("exp17", {json.loads(l)["post_id"]: json.loads(l)["texts"] for l in open(EXP17, encoding="utf-8")})]
    for name, posts in jobs:
        out = RESULTS / f"preds_{name}_{a.mode}.jsonl"
        t0 = time.perf_counter()
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            for i, (pid, texts) in enumerate(posts.items(), 1):
                res = app_detect(det, to_record(pid, texts))
                spans = [{k: s[k] for k in ("text_id", "start", "end", "type", "text", "level", "subject")}
                         for s in res["spans"]]
                f.write(json.dumps({"post_id": pid, "spans": spans}, ensure_ascii=False) + "\n")
                if i % 500 == 0:
                    print(f"{name} {i}/{len(posts)} {time.perf_counter() - t0:.0f}s", flush=True)
        print(f"saved {out} ({len(posts)}편 · {time.perf_counter() - t0:.0f}s)", flush=True)
    (RESULTS / f"preds_{a.mode}_meta.json").write_text(json.dumps(meta(a, det), ensure_ascii=False, indent=2) + "\n",
                                                      encoding="utf-8")


def cmd_latency(a) -> None:
    import measure_cpu_latency as m

    det = load_detector(Path(a.checkpoint), a.mode, a.threads)
    sample = m.select_length_spaced({pid: {"post_id": pid, **to_record(pid, row["texts"])}
                                     for pid, row in dev_gold_posts().items()}, 20)
    rows = []
    for post in sample:
        record = {k: v for k, v in post.items()}
        for label, fn in (("app", lambda r: app_detect(det, r)), ("model", lambda r: det.detect(r))):
            for _ in range(3):
                fn(record)
            times = []
            for _ in range(10):
                t = time.perf_counter()
                fn(record)
                times.append((time.perf_counter() - t) * 1000)
            rows.append({"post_id": post["post_id"], "path": label, "chars": m.post_length(post),
                         "median_ms": statistics.median(times), "times_ms": times})
    out = {"meta": meta(a, det), "rows": rows}
    for label in ("app", "model"):
        med = [r["median_ms"] for r in rows if r["path"] == label]
        out[label] = {"median_of_medians_ms": statistics.median(med), "p95_ms": m.nearest_rank(med, 0.95),
                      "max_ms": max(med), "under_300": sum(x < 300 for x in med)}
        print(a.mode, a.threads, label, {k: round(v, 1) for k, v in out[label].items()}, flush=True)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"latency_{a.mode}_t{a.threads}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                                                                encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["preds", "latency"])
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--mode", choices=["fp32", "int8"], required=True)
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    (cmd_preds if a.what == "preds" else cmd_latency)(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
