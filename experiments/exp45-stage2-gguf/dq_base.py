"""1/2 — 앱(Stage2Model)이 쓰는 베이스 가중치(NF4 double quant 를 bf16 으로 푼 Qwen3-4B)를 HF 폴더로 만든다. 어댑터는 merge 하지 않는다.

    PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 python experiments/exp45-stage2-gguf/dq_base.py --out <빈 폴더 · 약 8GB> [--base Qwen/Qwen3-4B]

GPU(bitsandbytes) 필요. 다음 단계는 build_gguf_lora.cmd — 이 폴더를 convert(bf16) → Q8_0 로 바꾸고, v2 어댑터는
convert_lora_to_gguf.py --outtype f32 로 따로 바꾼다. 앱은 llama-server -m <Q8_0> --lora <LoRA f32> 로 돌린다(infer.Stage2GGUF).

왜 merge 하지 않는가(결과 4): 어댑터 몫 ‖BA·α/r‖ 은 ‖W‖ 의 약 0.8% 라, merge 한 뒤 다시 양자화하면 격자에 깎인다
(Q5_K_M 에서 어댑터 몫 잔존 약 81%). 베이스만 양자화하고 LoRA 를 f32 로 실행 때 더하면 어댑터 몫은 그대로 남는다.
산출물은 저장소에 넣지 않는다(*.safetensors · *.gguf).
"""
import argparse
import glob
import os
import shutil
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")

BASE_FILES = ["config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"]


def base_dir(base: str) -> str:
    """from_pretrained(base, local_files_only=True) 가 읽는 것과 같은 폴더 — 로컬 폴더면 그대로, 허브 이름이면
    지금 HF_HOME · 캐시 설정에서 그 이름의 main 이 가리키는 스냅샷"""
    if os.path.isdir(base):
        return base
    from huggingface_hub import snapshot_download
    return snapshot_download(base, local_files_only=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default="Qwen/Qwen3-4B")
    a = ap.parse_args()
    import torch
    import bitsandbytes as bnb
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    t0 = time.time()
    cpu = AutoModelForCausalLM.from_pretrained(a.base, local_files_only=True, dtype=torch.bfloat16,
                                               low_cpu_mem_usage=True, device_map={"": "cpu"})
    q = AutoModelForCausalLM.from_pretrained(   # Stage2Model 과 같은 양자화 설정
        a.base, local_files_only=True,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                               bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True),
        device_map={"": 0}, dtype=torch.bfloat16, attn_implementation="sdpa")
    cpu_mods = dict(cpu.named_modules())
    n = 0
    with torch.no_grad():
        for name, mod in q.named_modules():
            if isinstance(mod, bnb.nn.Linear4bit):
                w = bnb.functional.dequantize_4bit(mod.weight.data, mod.weight.quant_state).to(torch.bfloat16)
                tgt = cpu_mods[name].weight
                assert tgt.shape == w.shape, (name, tgt.shape, w.shape)
                tgt.copy_(w.cpu())
                n += 1
    print("dequantized linears", n)
    del q
    torch.cuda.empty_cache()
    cpu.save_pretrained(a.out, safe_serialization=True, max_shard_size="2GB")
    # 토크나이저 · 설정은 실제로 올린 베이스(--base)의 파일 그대로 (앱은 chat 템플릿을 쓰지 않는다 — infer.chat_prompt)
    snap = base_dir(a.base)
    print("base files from", snap)
    for f in BASE_FILES:
        src = os.path.join(snap, f)
        if not os.path.isfile(src):
            raise SystemExit(f"베이스에 {f} 가 없다: {snap}")
        shutil.copyfile(src, os.path.join(a.out, f))
    for f in glob.glob(os.path.join(a.out, "chat_template.jinja")):
        os.remove(f)
    print("done", round(time.time() - t0, 1), "s")


if __name__ == "__main__":
    main()
