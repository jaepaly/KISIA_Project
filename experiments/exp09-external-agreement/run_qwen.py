"""Qwen3-4B + v1 어댑터 — inputs.jsonl 을 인물별로 greedy 생성. exp08 eval.py 와 같은 로딩·디코딩.

    python experiments/exp09-external-agreement/run_qwen.py [--pilot] [--max-new 700]

- 제약 디코딩 없음 — 생성 문자열의 첫 `{` ~ 마지막 `}` 를 파싱. 실패는 invalid 로 남긴다
- 이미 결과가 있는 인물은 건너뛴다
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

HERE = Path(__file__).resolve().parent
ADAPTER = HERE.parents[0] / "exp08-stage2-sft/results/adapter"
MODEL_ID = "Qwen/Qwen3-4B"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--max-new", type=int, default=700)
    a = ap.parse_args()
    data = HERE / "data"
    rows = [json.loads(l) for l in (data / "inputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.pilot:
        keep = set(json.loads((data / "pilot_ids.json").read_text(encoding="utf-8")))
        rows = [r for r in rows if r["persona_id"] in keep]
    out_path = data / ("qwen_pilot.jsonl" if a.pilot else "qwen.jsonl")
    done = set()
    if out_path.exists():
        done = {json.loads(l)["persona_id"] for l in out_path.read_text(encoding="utf-8").splitlines() if l.strip()}
    rows = [r for r in rows if r["persona_id"] not in done]
    if not rows:
        return 0

    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                               bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True),
        device_map={"": 0}, dtype=torch.bfloat16, attn_implementation="sdpa")
    model = PeftModel.from_pretrained(model, ADAPTER)
    model.eval()

    with out_path.open("a", encoding="utf-8") as f:
        for r in rows:
            msgs = [{"role": "system", "content": r["system"]}, {"role": "user", "content": r["user"]}]
            prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
            ids = tok(prompt, return_tensors="pt").to("cuda")
            t0 = time.time()
            with torch.no_grad():
                out = model.generate(**ids, max_new_tokens=a.max_new, do_sample=False,
                                     temperature=None, top_p=None, top_k=None)
            text = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
            rec = {"persona_id": r["persona_id"], "model": f"{MODEL_ID}+v1-adapter", "findings": None,
                   "error": None, "sec": round(time.time() - t0, 1), "raw": text}
            try:
                rec["findings"] = json.loads(text[text.index("{"): text.rindex("}") + 1])["findings"]
            except Exception as e:  # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(r["persona_id"], "ok" if rec["findings"] else f"FAIL {rec['error']}", rec["sec"], "s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
