"""1/3 — 앱이 실제로 계산하는 가중치(NF4 dequant + v2 LoRA)를 bf16 HF 폴더로 만든다. GPU(bitsandbytes) 필요.

    PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 python experiments/exp45-stage2-gguf/merge_dq.py \\
        --adapter <v2 어댑터 폴더 (c045d353…)> --out <빈 폴더 · 약 8GB>

원본 bf16 베이스에 바로 merge 한 판은 정확도가 떨어져 기각했다(README) — QLoRA 학습 때 어댑터가 본 베이스는
NF4(double quant)를 bf16 으로 푼 값이라, 그 값에 merge 해야 앱(Stage2Model)과 같은 함수가 된다.
다음 단계는 build_gguf.cmd (llama.cpp b12090 convert → Q5_K_M). 산출물은 저장소에 넣지 않는다(*.safetensors · *.gguf).
"""
import argparse
import glob
import hashlib
import os
import shutil
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")

V2_ADAPTER_PREFIX = "c045d353"   # models/registry.md 2단 v2 어댑터


def base_dir(base: str) -> str:
    """from_pretrained(base, local_files_only=True) 가 읽는 것과 같은 폴더 — 로컬 폴더면 그대로, 허브 이름이면
    지금 HF_HOME · 캐시 설정에서 그 이름의 main 이 가리키는 스냅샷 (snapshot_download 도 같은 규칙으로 찾는다)"""
    if os.path.isdir(base):
        return base
    from huggingface_hub import snapshot_download
    return snapshot_download(base, local_files_only=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default="Qwen/Qwen3-4B")
    a = ap.parse_args()
    import torch
    import bitsandbytes as bnb
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    with open(os.path.join(a.adapter, "adapter_model.safetensors"), "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest().startswith(V2_ADAPTER_PREFIX), "v2 어댑터가 아니다"
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
    m = PeftModel.from_pretrained(cpu, a.adapter).merge_and_unload()
    m.save_pretrained(a.out, safe_serialization=True, max_shard_size="2GB")
    # 토크나이저 · 설정은 실제로 올린 베이스(--base)의 파일 그대로 (chat 템플릿은 GGUF 메타데이터로 들어가지만 앱은 쓰지 않는다 —
    # infer.chat_prompt). 예전에는 기본 캐시의 첫 스냅샷을 찾아 복사해, --base 가 다른 폴더 · 리비전이면 어긋날 수 있었다 (Codex P2)
    snap = base_dir(a.base)
    print("base files from", snap)
    for f in ["config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"]:
        src = os.path.join(snap, f)
        if not os.path.isfile(src):
            raise SystemExit(f"베이스에 {f} 가 없다: {snap}")
        shutil.copyfile(src, os.path.join(a.out, f))
    for f in glob.glob(os.path.join(a.out, "chat_template.jinja")):
        os.remove(f)
    print("done", round(time.time() - t0, 1), "s")


if __name__ == "__main__":
    main()
