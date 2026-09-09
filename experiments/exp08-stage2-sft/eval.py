"""학습된 어댑터를 dev 예시에 돌려 판정·근거·함정 배제를 잰다.

    python experiments/exp08-stage2-sft/eval.py [--n 30] [--max-new 600]

- verdict 정확도(7속성 × 예시) · evidence span_id 집합 F1 · 함정 배제율
- 함정 = 입력에 있지만 타깃 evidence 에 없는 subject:self 스팬 (통로= 표시는 입력에 없다 — 모델이 시제·장소 성격으로 걸러야 한다)
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

MODEL_ID = "Qwen/Qwen3-4B"
HERE = Path(__file__).parent
ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--max-new", type=int, default=700)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rows = [json.loads(l) for l in (HERE / "data" / "dev.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rng = random.Random(a.seed)
    # 함정이 있는 예시를 우선 뽑는다: 입력 self 스팬 중 타깃 evidence 에 없는 것
    def trap_ids(r):
        inp = json.loads(r["messages"][1]["content"]); tgt = json.loads(r["messages"][2]["content"])
        used = {e["span_id"] for f in tgt["findings"].values() for e in f["evidence"]}
        spans = [s for p in inp["posts"] for s in p["spans"]] + ((inp.get("profile") or {}).get("spans") or [])
        return {s["span_id"] for s in spans if s["subject"] == "self" and s["span_id"] not in used}
    with_trap = [r for r in rows if trap_ids(r)]
    others = [r for r in rows if not trap_ids(r)]
    rng.shuffle(with_trap); rng.shuffle(others)
    sample = (with_trap + others)[: a.n]
    print(f"dev {len(rows)} · 함정 있는 예시 {len(with_trap)} · 평가 {len(sample)}")

    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                               bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True),
        device_map={"": 0}, dtype=torch.bfloat16, attn_implementation="sdpa")
    model = PeftModel.from_pretrained(model, HERE / "results" / "adapter")
    model.eval()

    stats = {"n": 0, "json_ok": 0, "verdict_hit": 0, "verdict_total": 0, "ev_tp": 0, "ev_fp": 0, "ev_fn": 0,
             "trap_total": 0, "trap_leaked": 0, "sec": 0.0, "per_attr": {k: [0, 0] for k in ATTRS}}
    fails = []
    for r in sample:
        msgs = r["messages"][:-1]
        prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        ids = tok(prompt, return_tensors="pt").to("cuda")
        t0 = time.time()
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=a.max_new, do_sample=False, temperature=None, top_p=None, top_k=None)
        text = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        stats["sec"] += time.time() - t0
        stats["n"] += 1
        tgt = json.loads(r["messages"][2]["content"])["findings"]
        traps = trap_ids(r)
        try:
            pred = json.loads(text[text.index("{"): text.rindex("}") + 1])["findings"]
            stats["json_ok"] += 1
        except Exception:
            fails.append(text[:200]); stats["verdict_total"] += 7; stats["ev_fn"] += sum(len(f["evidence"]) for f in tgt.values())
            stats["trap_total"] += len(traps)
            continue
        for k in ATTRS:
            stats["verdict_total"] += 1; stats["per_attr"][k][1] += 1
            if pred.get(k, {}).get("verdict") == tgt[k]["verdict"]:
                stats["verdict_hit"] += 1; stats["per_attr"][k][0] += 1
        p_ev = {e.get("span_id") for f in pred.values() if isinstance(f, dict) for e in f.get("evidence", []) if isinstance(e, dict)}
        t_ev = {e["span_id"] for f in tgt.values() for e in f["evidence"]}
        stats["ev_tp"] += len(p_ev & t_ev); stats["ev_fp"] += len(p_ev - t_ev); stats["ev_fn"] += len(t_ev - p_ev)
        stats["trap_total"] += len(traps); stats["trap_leaked"] += len(traps & p_ev)
        print(f"  verdict {sum(pred.get(k,{}).get('verdict')==tgt[k]['verdict'] for k in ATTRS)}/7 · ev +{len(p_ev&t_ev)} -{len(p_ev-t_ev)} miss{len(t_ev-p_ev)} · trap {len(traps&p_ev)}/{len(traps)} · {round(time.time()-t0,1)}s", flush=True)

    P = stats["ev_tp"] / max(1, stats["ev_tp"] + stats["ev_fp"]); R = stats["ev_tp"] / max(1, stats["ev_tp"] + stats["ev_fn"])
    res = {"n": stats["n"], "json_ok": stats["json_ok"], "verdict_acc": round(stats["verdict_hit"] / max(1, stats["verdict_total"]), 4),
           "per_attr_acc": {k: round(v[0] / max(1, v[1]), 3) for k, v in stats["per_attr"].items()},
           "evidence_P": round(P, 4), "evidence_R": round(R, 4), "evidence_F1": round(2 * P * R / max(1e-9, P + R), 4),
           "trap_total": stats["trap_total"], "trap_leaked": stats["trap_leaked"],
           "trap_exclusion": round(1 - stats["trap_leaked"] / max(1, stats["trap_total"]), 4),
           "sec_per_example": round(stats["sec"] / max(1, stats["n"]), 1), "json_fail_samples": fails[:3],
           "measured_at": time.strftime("%Y-%m-%d"), "adapter": "results/adapter (epoch 1, seq 1408, r16)"}
    (HERE / "results" / "eval_dev.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
