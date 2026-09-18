"""adapter 로드 후 dev.jsonl 샘플 3개에 대해 생성·GT 비교."""
from __future__ import annotations
import json, sys, textwrap
from pathlib import Path

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from peft import PeftModel

ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = "Qwen/Qwen3-4B"
ADAPTER = Path(__file__).parent / "results/adapter"
DATA = Path(__file__).parent / "data/dev.jsonl"
N = 10

bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16,
                         bnb_4bit_use_double_quant=True, bnb_4bit_quant_type="nf4")
tok = AutoTokenizer.from_pretrained(MODEL_ID)
base = AutoModelForCausalLM.from_pretrained(MODEL_ID, quantization_config=bnb,
                                            device_map="auto", torch_dtype=torch.bfloat16)
model = PeftModel.from_pretrained(base, ADAPTER)
model.eval()

samples = []
with DATA.open(encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i >= N:
            break
        samples.append(json.loads(line)["messages"])

for idx, msgs in enumerate(samples, 1):
    system = msgs[0]["content"]
    user   = msgs[1]["content"]
    gt     = msgs[2]["content"]

    prompt = tok.apply_chat_template(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        tokenize=False, add_generation_prompt=True, enable_thinking=False,
    )
    inputs = tok(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=1024, do_sample=False,
                             pad_token_id=tok.eos_token_id)
    raw = tok.decode(out[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True).strip()
    # Qwen3 thinking mode: </think> 이후가 실제 답
    if "</think>" in raw:
        gen = raw.split("</think>", 1)[1].strip()
    else:
        gen = raw

    print(f"\n{'='*60}")
    print(f"[샘플 {idx}]")
    print(f"--- GT ---\n{textwrap.shorten(gt, 300)}")
    print(f"--- 생성 ---\n{textwrap.shorten(gen, 300)}")

    # verdict 일치 비교
    try:
        gt_j  = json.loads(gt)
        gen_j = json.loads(gen)
        matches = {k: gt_j["findings"][k]["verdict"] == gen_j["findings"][k]["verdict"]
                   for k in gt_j["findings"]}
        hit = sum(matches.values())
        print(f"verdict 일치: {hit}/7  {matches}")
    except Exception as e:
        print(f"JSON 파싱 실패: {e}")

print("\n완료")
