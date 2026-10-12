"""2단 v2 VRAM 탐침 (W9 D 5번) — exp08 train.py 와 같은 설정(NF4 · LoRA r16 q/k/v/o · grad checkpointing · batch 1)으로
길이별 학습 한 걸음(forward+backward)의 피크 VRAM · 시간. A = 지금 train.py 방식(전 구간 logits) · B = 답변 구간만 logits(`logits_to_keep`).

    PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 python experiments/exp08-stage2-sft/v2_vram.py

입력은 무작위 토큰(메모리는 길이만 따른다) · 답변 900 토큰(실제 계정 답변 최대 873). RTX 3060 8GB · 10/12 결과는 README 「v2 준비」."""
import time

import torch
import torch.nn.functional as F
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, BitsAndBytesConfig

model = AutoModelForCausalLM.from_pretrained(
    "Qwen/Qwen3-4B",
    quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                           bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True),
    device_map={"": 0}, dtype=torch.bfloat16, attn_implementation="sdpa")
model.config.use_cache = False
model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
model.enable_input_require_grads()
model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05,
                                         target_modules=["q_proj", "k_proj", "v_proj", "o_proj"], task_type="CAUSAL_LM"))
model.train()
COMP = 900   # 실제 계정 답변 최대 873 토큰
for L in (1408, 2048, 2560, 2900):
    for mode in ("A", "B"):
        torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
        ids = torch.randint(1000, 100000, (1, L), device="cuda")
        labels = ids.clone(); labels[:, : L - COMP] = -100
        t0 = time.time()
        try:
            if mode == "A":
                loss = model(input_ids=ids, labels=labels).loss
            else:
                logits = model(input_ids=ids, logits_to_keep=COMP + 1).logits   # 끝 COMP+1 위치만
                loss = F.cross_entropy(logits[0, :-1].float(), ids[0, L - COMP:])
            loss.backward()
            torch.cuda.synchronize()
            print(f"L={L} {mode} 피크 {torch.cuda.max_memory_allocated()/1e9:.2f} GB · {time.time()-t0:.1f}s", flush=True)
        except torch.OutOfMemoryError:
            print(f"L={L} {mode} OOM", flush=True)
        model.zero_grad(set_to_none=True)
        del ids, labels
