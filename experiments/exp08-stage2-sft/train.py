"""2단 판정기 QLoRA SFT — Qwen3-4B NF4 + LoRA r16, RTX 3060 8GB (exp07 상한: seq 1024 · batch 1).

    python experiments/exp08-stage2-sft/train.py [--epochs 1] [--max-len 1024] [--grad-accum 8] [--lr 2e-4]

- 손실은 assistant 턴에만 (system·user 는 -100)
- max-len 을 넘는 예시는 버린다 (자르면 타깃 JSON 이 깨진다) — 버린 수를 metrics 에 적는다
- 산출: results/adapter/ (LoRA 가중치) · results/metrics.json (loss 곡선 · dev loss · VRAM · 시간)
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

MODEL_ID = "Qwen/Qwen3-4B"
HERE = Path(__file__).parent
DATA = HERE / "data"
RESULTS = HERE / "results"


def gb(n: int) -> float:
    return round(n / 1e9, 2)


def encode(tok, messages: list[dict], max_len: int):
    """chat template 로 전체를 만들고, assistant 구간만 라벨로 남긴다."""
    prompt = tok.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    full = tok.apply_chat_template(messages, tokenize=False, enable_thinking=False)
    if not full.startswith(prompt):
        return None
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    f_ids = tok(full, add_special_tokens=False)["input_ids"]
    if len(f_ids) > max_len:
        return None
    labels = [-100] * len(p_ids) + f_ids[len(p_ids):]
    return torch.tensor(f_ids), torch.tensor(labels)


def load(tok, path: Path, max_len: int):
    kept, dropped = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        enc = encode(tok, json.loads(line)["messages"], max_len)
        if enc is None:
            dropped += 1
        else:
            kept.append(enc)
    return kept, dropped


@torch.no_grad()
def eval_loss(model, data) -> float:
    model.eval()
    tot, n = 0.0, 0
    for ids, labels in data:
        out = model(input_ids=ids[None].cuda(), labels=labels[None].cuda())
        tot += out.loss.item(); n += 1
    model.train()
    return round(tot / max(n, 1), 4)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--max-len", type=int, default=1024)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--seed", type=int, default=20260908)
    ap.add_argument("--limit", type=int, default=0, help="디버그 — 예시 n개만")
    a = ap.parse_args()
    torch.manual_seed(a.seed); random.seed(a.seed)
    RESULTS.mkdir(parents=True, exist_ok=True)

    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    train, tr_drop = load(tok, DATA / "train.jsonl", a.max_len)
    dev, dv_drop = load(tok, DATA / "dev.jsonl", a.max_len)
    if a.limit:
        train, dev = train[: a.limit], dev[: max(4, a.limit // 8)]
    print(f"train {len(train)} (버림 {tr_drop}) · dev {len(dev)} (버림 {dv_drop}) · max_len {a.max_len}")

    t0 = time.time()
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                               bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True),
        device_map={"": 0}, dtype=torch.bfloat16, attn_implementation="sdpa",
    )
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05,
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
                                             task_type="CAUSAL_LM"))
    model.train()
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)
    total_updates = math.ceil(len(train) * a.epochs / a.grad_accum)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda u: min(1.0, (u + 1) / max(1, int(0.05 * total_updates))) * 0.5 * (1 + math.cos(math.pi * min(u, total_updates) / total_updates)))
    print(f"로드 {round(time.time()-t0,1)}s · 업데이트 {total_updates}회")

    metrics = {"model": MODEL_ID, "rank": a.rank, "max_len": a.max_len, "grad_accum": a.grad_accum, "lr": a.lr,
               "epochs": a.epochs, "seed": a.seed, "train_n": len(train), "train_dropped": tr_drop,
               "dev_n": len(dev), "dev_dropped": dv_drop, "loss_curve": [], "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    metrics["dev_loss_before"] = eval_loss(model, dev)
    print("dev loss (학습 전)", metrics["dev_loss_before"])

    torch.cuda.reset_peak_memory_stats()
    step = upd = 0
    run_loss = 0.0
    t0 = time.time()
    for ep in range(a.epochs):
        order = list(range(len(train))); random.shuffle(order)
        for i in order:
            ids, labels = train[i]
            out = model(input_ids=ids[None].cuda(), labels=labels[None].cuda())
            (out.loss / a.grad_accum).backward()
            run_loss += out.loss.item(); step += 1
            if step % a.grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step(); sched.step(); opt.zero_grad(set_to_none=True); upd += 1
                if upd % 20 == 0:
                    model.save_pretrained(RESULTS / "adapter")  # 중간 저장 — 스톨·중단 대비
                if upd % 5 == 0 or upd == total_updates:
                    avg = round(run_loss / a.grad_accum / 5, 4) if upd % 5 == 0 else round(run_loss / a.grad_accum, 4)
                    metrics["loss_curve"].append({"update": upd, "loss": avg, "sec": round(time.time() - t0)})
                    print(f"  upd {upd}/{total_updates} · loss {avg} · {round(time.time()-t0)}s · VRAM {gb(torch.cuda.max_memory_allocated())} GB", flush=True)
                    run_loss = 0.0
    metrics["train_sec"] = round(time.time() - t0)
    metrics["vram_peak_gb"] = gb(torch.cuda.max_memory_allocated())
    metrics["dev_loss_after"] = eval_loss(model, dev)
    print("dev loss (학습 후)", metrics["dev_loss_after"], "· 피크 VRAM", metrics["vram_peak_gb"], "GB")
    model.save_pretrained(RESULTS / "adapter")
    (RESULTS / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print("→", RESULTS / "adapter", "·", RESULTS / "metrics.json")


if __name__ == "__main__":
    main()
