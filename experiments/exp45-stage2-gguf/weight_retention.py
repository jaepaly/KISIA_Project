"""결과 4 원인 — merge 뒤 재양자화에서 어댑터 몫이 얼마나 남는가 (CPU · 저장소 밖 GGUF 를 읽는다).

    python experiments/exp45-stage2-gguf/weight_retention.py --adapter <v2 어댑터 폴더> --gguf-py <llama.cpp b12090>/gguf-py \
        --merged-bf16 <dq-merge bf16.gguf> --base-bf16 <dqonly bf16.gguf> \
        --merged-Q8_0 <dq-merge Q8_0.gguf> --base-Q8_0 <dqonly Q8_0.gguf> \
        --merged-Q5_K_M <dq-merge Q5_K_M.gguf> --base-Q5_K_M <dqonly Q5_K_M.gguf> --out <요약 JSON>

- Δ = v2 어댑터 B·A·(lora_alpha / r) (fp32). merged = merge_dq.py 로 만든 판(W+Δ 를 양자화) · base = dq_base.py 판(W 만 양자화)
- retained = <X_merged − X_base, Δ> / ‖Δ‖²  — 같은 격자에서 merge 로 더해진 몫이 Δ 방향으로 얼마나 남았나(1 이면 그대로)
- resid_over_D = ‖(X_merged − X_base) − Δ‖ / ‖Δ‖  — 어댑터 몫 대비 잡음 크기
- 표본은 층 9개 × 어텐션 4 투영(q·k·v·o) = 36 텐서. LoRA 분리(베이스 Q8_0 + LoRA f32)는 Δ 를 실행 때 f32 로 더하므로 이 손실이 없다
"""
import argparse
import json
import sys
from pathlib import Path

LAYERS = [0, 4, 9, 13, 18, 22, 27, 31, 35]
PROJ = {"q_proj": "attn_q", "k_proj": "attn_k", "v_proj": "attn_v", "o_proj": "attn_output"}
QUANTS = ("bf16", "Q8_0", "Q5_K_M")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", type=Path, required=True)
    ap.add_argument("--gguf-py", type=Path, required=True, help="llama.cpp b12090 의 gguf-py 폴더")
    for q in QUANTS:
        ap.add_argument(f"--merged-{q}", type=Path, required=True)
        ap.add_argument(f"--base-{q}", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    sys.path.insert(0, str(a.gguf_py))
    import gguf
    import numpy as np
    import torch
    from gguf.quants import dequantize
    from safetensors import safe_open

    cfg = json.loads((a.adapter / "adapter_config.json").read_text(encoding="utf-8"))
    scale = cfg["lora_alpha"] / cfg["r"]
    files = {f"m_{q}": getattr(a, f"merged_{q}") for q in QUANTS} | {f"u_{q}": getattr(a, f"base_{q}") for q in QUANTS}
    gt = {k: {x.name: x for x in gguf.GGUFReader(str(p)).tensors} for k, p in files.items()}
    ad = safe_open(str(a.adapter / "adapter_model.safetensors"), "pt")
    keys = list(ad.keys())
    rows = []
    for L in LAYERS:
        for p, gname in PROJ.items():
            ka = next(k for k in keys if f"layers.{L}.self_attn.{p}.lora_A" in k)
            kb = next(k for k in keys if f"layers.{L}.self_attn.{p}.lora_B" in k)
            D = (ad.get_tensor(kb).float() @ ad.get_tensor(ka).float()) * scale
            T = {}
            for k in files:
                x = gt[k][f"blk.{L}.{gname}.weight"]
                T[k] = torch.from_numpy(np.asarray(dequantize(x.data, x.tensor_type), dtype=np.float32).reshape(D.shape))
            r = {"layer": L, "proj": p, "D_over_W": round(D.norm().item() / T["u_bf16"].norm().item(), 5)}
            for q in QUANTS:
                diff = T["m_" + q] - T["u_" + q]
                r["retained_" + q] = round((diff * D).sum().item() / (D * D).sum().item(), 4)
                r["resid_over_D_" + q] = round((diff - D).norm().item() / D.norm().item(), 4)
            rows.append(r)
            print(json.dumps(r), flush=True)
    mean = {k: round(float(np.mean([r[k] for r in rows])), 4) for k in rows[0] if k not in ("layer", "proj")}
    a.out.write_text(json.dumps({"tensors": len(rows), "lora_scale": scale, "mean": mean, "rows": rows}, indent=1) + "\n",
                     encoding="utf-8")
    print("MEAN", json.dumps(mean))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
