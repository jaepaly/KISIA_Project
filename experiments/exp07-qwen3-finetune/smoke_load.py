"""Qwen3-4B 4bit 로드 + LoRA 부착 + 학습 스텝 1회 — VRAM 이 실제로 들어가는지 본다.

python experiments/exp07-qwen3-finetune/smoke_load.py [--seq-len 1024] [--rank 16]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

MODEL_ID = "Qwen/Qwen3-4B"
RESULTS = Path(__file__).parent / "results"


def gb(n: int) -> float:
    return round(n / 1e9, 2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq-len", type=int, default=1024)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--batch", type=int, default=1)
    a = ap.parse_args()

    torch.manual_seed(20260907)
    rec: dict = {"model": MODEL_ID, "seq_len": a.seq_len, "rank": a.rank, "batch": a.batch}

    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        ),
        device_map={"": 0},
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )
    rec["load_sec"] = round(time.time() - t0, 1)
    rec["vram_after_load_gb"] = gb(torch.cuda.memory_allocated())
    print(f"로드 {rec['load_sec']}s · VRAM {rec['vram_after_load_gb']} GB")

    # prepare_model_for_kbit_training 은 임베딩 389M 을 fp32 로 올려 +0.8GB — 8GB 카드에서는 안 쓴다
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model = get_peft_model(
        model,
        LoraConfig(
            r=a.rank,
            lora_alpha=2 * a.rank,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
            lora_dropout=0.05,
            task_type="CAUSAL_LM",
        ),
    )
    trainable, total = model.get_nb_trainable_parameters()
    rec["trainable_params"] = trainable
    rec["trainable_pct"] = round(100 * trainable / total, 3)
    print(f"학습 파라미터 {trainable:,} / {total:,} ({rec['trainable_pct']}%)")

    # from_pretrained 는 eval 모드로 돌려준다 — train() 이 아니면 gradient checkpointing 이 적용되지 않는다
    model.train()
    ids = torch.randint(0, tok.vocab_size, (a.batch, a.seq_len), device="cuda")
    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    out = model(input_ids=ids, labels=ids)
    out.loss.backward()
    torch.cuda.synchronize()
    rec["step_sec"] = round(time.time() - t0, 1)
    rec["vram_peak_step_gb"] = gb(torch.cuda.max_memory_allocated())
    rec["vram_total_gb"] = gb(torch.cuda.get_device_properties(0).total_memory)
    rec["loss"] = round(out.loss.item(), 3)
    print(
        f"fwd+bwd {rec['step_sec']}s · 피크 VRAM {rec['vram_peak_step_gb']} / "
        f"{rec['vram_total_gb']} GB · loss {rec['loss']}"
    )

    out = RESULTS / f"smoke_load_seq{a.seq_len}_r{a.rank}.json"
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    print("→", out)


if __name__ == "__main__":
    main()
