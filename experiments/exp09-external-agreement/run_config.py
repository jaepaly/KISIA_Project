"""exp09 를 2단 구성별로 다시 — exp22 · exp22b 교체 기준 6번 (회귀 확인).

    PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 PYTHONPATH="src;." \\
        python experiments/exp09-external-agreement/run_config.py --config v1 --adapter <v1 보관본>
    python experiments/exp09-external-agreement/run_config.py --config v2
    python experiments/exp09-external-agreement/score.py --qwen-file qwen_cfg_v1.jsonl --out metrics_cfg_v1.json
    python experiments/exp09-external-agreement/score.py --qwen-file qwen_cfg_v2.jsonl --out metrics_cfg_v2.json

9/28 결과(`data/qwen.jsonl` · `results/metrics.json` — v1 · 전체 입력 · 상한 700)는 **건드리지 않는다**. 입력은 같은
`data/inputs.jsonl`(105명 · 239편 · 가명 스팬)의 posts 를 앱이 그 구성에서 고르는 대로 다시 고른다:
- v1 = 지금 앱 — `select_for_model` 상한 24/6 · 스팬 없는 글도 목록에 · system = inputs 의 학습 프롬프트(SYSTEM_V1)
- v2 = 후보 — 상한 16/4 · 스팬 없는 글 뺌 · system = SYSTEM_V2 (make_sft_v2)
두 구성 모두 고친 출력 상한 `output_budget(entries)` (#346) · greedy · thinking 끔. 외부 LLM 판정(`data/external.jsonl` · 9/28)은 그대로 정답 쪽.
채점은 9/28 과 같은 score.py 경로(원시 출력 파싱 — 앱 검증 없이)라 두 구성이 같은 잣대다.
출력: data/qwen_cfg_<config>.jsonl (이미 있으면 멈춘다 · 한 번만)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "experiments/exp08-stage2-sft")]

from kopl.c4_stage2 import infer  # noqa: E402
from make_sft_v2 import MAX_PER_TYPE, MAX_SPANS, SYSTEM_V2  # noqa: E402

V1_SHA256 = "1053e7adcc77d1863e0789978b468d29d92930dc9c26a84a0a29e7fbc99a6a4b"
ADAPTERS = {"v1": ROOT / "experiments/exp08-stage2-sft/results/adapter",
            "v2": ROOT / "experiments/exp08-stage2-sft/results/adapter_v2"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_input(config: str, row: dict) -> tuple[str, str, list[dict]]:
    user = json.loads(row["user"])
    posts = user["posts"]
    if config == "v1":
        entries = infer.select_for_model(posts, max_spans=24, max_per_type=6)  # 10/12 까지의 앱 (기본값이 v2 로 바뀌어도 재현)
        system = row["system"]
    else:
        entries = [e for e in infer.select_for_model(posts, max_spans=MAX_SPANS, max_per_type=MAX_PER_TYPE) if e["spans"]]
        system = SYSTEM_V2
    return system, json.dumps({**user, "posts": entries}, ensure_ascii=False), entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=("v1", "v2"), required=True)
    ap.add_argument("--adapter", type=Path)
    a = ap.parse_args()
    out = HERE / "data" / f"qwen_cfg_{a.config}.jsonl"
    if out.exists():
        raise SystemExit(f"{out} 가 이미 있다 — 구성마다 한 번만")
    adapter = a.adapter or ADAPTERS[a.config]
    if a.config == "v1" and sha256(adapter / "adapter_model.safetensors") != V1_SHA256:
        raise SystemExit(f"v1 어댑터 해시가 다르다: {adapter}")
    rows = [json.loads(l) for l in (HERE / "data/inputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    model = infer.Stage2Model(adapter)
    torch = model._torch
    recs = []
    for r in rows:
        system, prompt, entries = config_input(a.config, r)
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        chat = model.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        ids = model.tok(chat, return_tensors="pt").to(model.model.device)
        t0 = time.time()
        with torch.no_grad():
            gen = model.model.generate(**ids, max_new_tokens=infer.output_budget(entries), do_sample=False,
                                       temperature=None, top_p=None, top_k=None)
        text = model.tok.decode(gen[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        rec = {"persona_id": r["persona_id"], "model": f"Qwen/Qwen3-4B+{a.config}", "config": a.config,
               "findings": None, "error": None, "sec": round(time.time() - t0, 1), "raw": text,
               "n_spans_in": sum(len(e["spans"]) for e in entries), "truncated": not text.rstrip().endswith("}")}
        try:
            rec["findings"] = json.loads(text[text.index("{"): text.rindex("}") + 1])["findings"]
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        recs.append(rec)
        print(r["persona_id"], "ok" if rec["findings"] else f"FAIL {rec['error']}", rec["sec"], "s", flush=True)
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in recs), encoding="utf-8", newline="\n")
    (HERE / "data" / f"qwen_cfg_{a.config}_meta.json").write_text(json.dumps({
        "config": a.config, "adapter": str(adapter), "adapter_sha256": sha256(adapter / "adapter_model.safetensors"),
        "inputs_sha256": sha256(HERE / "data/inputs.jsonl"), "external_sha256": sha256(HERE / "data/external.jsonl"),
        "measured": time.strftime("%Y-%m-%d %H:%M")}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
