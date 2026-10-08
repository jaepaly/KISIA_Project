"""바꿔 쓰기 어댑터 QLoRA SFT — exp08 train.py 를 그대로 가져와 데이터 · 산출 경로만 바꿨다.

    python experiments/exp21-local-rewrite/train.py [--epochs 2] [--max-len 1024]

- 데이터: make_teacher.py --build 가 만든 data/train.jsonl · dev.jsonl (교사 GPT · 인물 단위 분리)
- 2단 어댑터와 같은 베이스(Qwen3-4B NF4) 위에 따로 얹는다 — 실행 때 어댑터만 바꿔 끼운다

- 손실은 assistant 턴에만 (system·user 는 -100)
- max-len 을 넘는 예시는 버린다 (자르면 타깃 JSON 이 깨진다) — 버린 수를 metrics 에 적는다
- 산출: results/rewrite_adapter/ (LoRA 가중치 · 커밋하지 않는다)
- **이어 하기**: 5업데이트마다 results/checkpoint/state.pt 에 학습 가중치 · 옵티마이저 · 스케줄 · 데이터 순서 · 위치 · 난수 상태를
  저장한다. 중간에 끊기면 같은 인자에 --resume 을 붙여 그 지점부터 똑같이 이어 간다 (10/8 · 시스템 RAM 부족으로 45/78 에서 끊긴 뒤) · results/metrics.json (loss 곡선 · dev loss · VRAM · 시간)
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
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--max-len", type=int, default=1024)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--seed", type=int, default=20260908)
    ap.add_argument("--limit", type=int, default=0, help="디버그 — 예시 n개만")
    ap.add_argument("--resume", action="store_true", help="results/checkpoint/state.pt 에서 이어 하기")
    ap.add_argument("--ckpt-every", type=int, default=5)
    ap.add_argument("--stop-at", type=int, default=0, help="시험용 — 이 업데이트에서 체크포인트만 남기고 멈춘다 (이어 하기 확인)")
    ap.add_argument("--out-dir", type=Path, default=None, help="산출 폴더 (기본 results/)")
    ap.add_argument("--data-dir", type=Path, default=None, help="학습 데이터 폴더 (기본 data/)")
    a = ap.parse_args()
    torch.manual_seed(a.seed); random.seed(a.seed)
    global RESULTS
    if a.out_dir:
        RESULTS = a.out_dir
    RESULTS.mkdir(parents=True, exist_ok=True)

    tok = AutoTokenizer.from_pretrained(MODEL_ID, local_files_only=True)
    data_dir = a.data_dir or DATA
    train, tr_drop = load(tok, data_dir / "train.jsonl", a.max_len)
    dev, dv_drop = load(tok, data_dir / "dev.jsonl", a.max_len)
    if a.limit:
        train, dev = train[: a.limit], dev[: max(4, a.limit // 8)]
    print(f"train {len(train)} (버림 {tr_drop}) · dev {len(dev)} (버림 {dv_drop}) · max_len {a.max_len}")

    t0 = time.time()
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID, local_files_only=True,
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
    ckpt = RESULTS / "checkpoint" / "state.pt"
    trainable = [n for n, p in model.named_parameters() if p.requires_grad]
    step = upd = 0
    run_loss = 0.0
    orders: list[list[int]] = []
    elapsed_before = 0.0
    if a.resume:
        st = torch.load(ckpt, map_location="cpu", weights_only=False)
        model.load_state_dict(st["weights"], strict=False)
        opt.load_state_dict(st["opt"]); sched.load_state_dict(st["sched"])
        step, upd, run_loss, orders, metrics = st["step"], st["upd"], st["run_loss"], st["orders"], st["metrics"]
        random.setstate(st["py_rng"]); torch.set_rng_state(st["torch_rng"]); torch.cuda.set_rng_state(st["cuda_rng"])
        elapsed_before = st["elapsed"]
        print(f"이어 하기: upd {upd}/{total_updates} · step {step}")
    else:
        metrics["dev_loss_before"] = eval_loss(model, dev)
        print("dev loss (학습 전)", metrics["dev_loss_before"], flush=True)
        for _ in range(a.epochs):  # 순서를 미리 다 정해 둔다 — 이어 하기 때 같은 순서를 쓰려고
            order = list(range(len(train))); random.shuffle(order); orders.append(order)

    def save_ckpt() -> None:
        named = dict(model.named_parameters())
        state = {"weights": {n: named[n].detach().cpu() for n in trainable}, "opt": opt.state_dict(),
                 "sched": sched.state_dict(), "step": step, "upd": upd, "run_loss": run_loss, "orders": orders,
                 "metrics": metrics, "py_rng": random.getstate(), "torch_rng": torch.get_rng_state(),
                 "cuda_rng": torch.cuda.get_rng_state(), "elapsed": elapsed_before + time.time() - t0}
        ckpt.parent.mkdir(parents=True, exist_ok=True)
        tmp = ckpt.with_suffix(".tmp")
        torch.save(state, tmp)
        tmp.replace(ckpt)  # 저장 도중에 끊겨도 직전 체크포인트는 남는다

    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    done = step  # 이미 지난 예시 수 (이어 하기)
    seen = 0
    for ep in range(a.epochs):
        for i in orders[ep]:
            seen += 1
            if seen <= done:
                continue
            ids, labels = train[i]
            out = model(input_ids=ids[None].cuda(), labels=labels[None].cuda())
            (out.loss / a.grad_accum).backward()
            run_loss += out.loss.item(); step += 1
            if step % a.grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step(); sched.step(); opt.zero_grad(set_to_none=True); upd += 1
                if upd % 5 == 0 or upd == total_updates:
                    avg = round(run_loss / a.grad_accum / 5, 4) if upd % 5 == 0 else round(run_loss / a.grad_accum, 4)
                    sec = round(elapsed_before + time.time() - t0)
                    metrics["loss_curve"].append({"update": upd, "loss": avg, "sec": sec})
                    print(f"  upd {upd}/{total_updates} · loss {avg} · {sec}s · VRAM {gb(torch.cuda.max_memory_allocated())} GB", flush=True)
                    run_loss = 0.0
                if upd % a.ckpt_every == 0:
                    save_ckpt()  # 손실 기록 뒤에 — 이어 할 때 run_loss 가 0 부터 다시 쌓이게
                if a.stop_at and upd == a.stop_at:
                    save_ckpt()
                    print(f"--stop-at {upd} — 멈춤", flush=True)
                    return
    metrics["train_sec"] = round(elapsed_before + time.time() - t0)
    metrics["vram_peak_gb"] = gb(torch.cuda.max_memory_allocated())
    metrics["dev_loss_after"] = eval_loss(model, dev)
    print("dev loss (학습 후)", metrics["dev_loss_after"], "· 피크 VRAM", metrics["vram_peak_gb"], "GB")
    model.save_pretrained(RESULTS / "rewrite_adapter")
    (RESULTS / "train_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print("→", RESULTS / "rewrite_adapter", "·", RESULTS / "train_metrics.json")


if __name__ == "__main__":
    main()
