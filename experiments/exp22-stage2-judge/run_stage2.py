"""exp22 2단 실행 — 고정한 1단 예측(data/stage1.jsonl)을 받아 한 구성(v1 · v2)으로 30계정을 한 번 돌린다 (README §2).

    PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 PYTHONPATH="src;." python experiments/exp22-stage2-judge/run_stage2.py --config v1
    PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 PYTHONPATH="src;." python experiments/exp22-stage2-judge/run_stage2.py --config v2

구성은 각자의 **전체 구성**이다:
- v1 = 지금 앱 — `infer.build_user_prompt(cap=True)`(상한 24/6 · 스팬 없는 글도 목록에) · `SYSTEM_V1` · 어댑터 exp08 results/adapter
- v2 = 후보 — 같은 가명화 · `select_for_model(16, 4)` · 스팬 없는 글 뺌 · `SYSTEM_V2`(make_sft_v2) · 어댑터 exp08 results/adapter_v2
디코딩은 두 구성 같다 — 앱 Stage2Model 과 같은 greedy · thinking 끔 · `output_budget(입력 스팬 수)`.
출력: results/raw_<config>.jsonl — 계정마다 보낸 입력 · 원시 출력 · 앱 검증 결과(validate_findings) · 시간. 이미 있으면 멈춘다(한 번만).
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
from make_sft_v1 import user_ref  # noqa: E402
from make_sft_v2 import MAX_PER_TYPE, MAX_SPANS, SYSTEM_V2  # noqa: E402

ADAPTERS = {"v1": ROOT / "experiments/exp08-stage2-sft/results/adapter",
            "v2": ROOT / "experiments/exp08-stage2-sft/results/adapter_v2"}
# 어댑터는 커밋하지 않는다 — 다른 작업 폴더에서 돌리면 --adapter 로 보관본을 준다. v1 은 해시로 같은 어댑터인지 확인한다
V1_SHA256 = "1053e7adcc77d1863e0789978b468d29d92930dc9c26a84a0a29e7fbc99a6a4b"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_accounts() -> list[dict]:
    manifest = json.loads((HERE / "data/stage1_manifest.json").read_text(encoding="utf-8"))
    if sha256(HERE / "data/accounts.jsonl") != manifest["accounts_sha256"] or sha256(HERE / "data/stage1.jsonl") != manifest["stage1_sha256"]:
        raise SystemExit("accounts · stage1 해시가 manifest 와 다르다 — 고정한 입력만 쓴다")
    spans = {r["post_id"]: r["spans"] for r in map(json.loads, (HERE / "data/stage1.jsonl").read_text(encoding="utf-8").splitlines()) if r}
    out = []
    for line in (HERE / "data/accounts.jsonl").read_text(encoding="utf-8").splitlines():
        a = json.loads(line)
        posts = [{"post_id": p["post_id"], "texts": {"body": p["texts"]["body"]}, "spans": spans[p["post_id"]]} for p in a["posts"]]
        out.append({"account_id": a["account_id"], "posts": posts})
    return out


def model_input(config: str, uref: str, posts: list[dict]) -> tuple[str, str, list[dict]]:
    """(system, user_prompt, entries) — 앱이 그 구성에서 모델에 보내는 것 그대로"""
    if config == "v1":
        # v1 구성 = 10/12 까지의 앱 (상한 24/6 · 빈 글 포함) — 앱 기본값이 v2 로 바뀌어도 재현되게 명시한다
        entries = [{"post_id": p["post_id"], "spans": infer.pseudonymize_spans(p)} for p in posts]
        entries = infer.select_for_model(entries, max_spans=24, max_per_type=6)
        return infer.SYSTEM_V1, json.dumps({"user_ref": uref, "profile": None, "posts": entries}, ensure_ascii=False), entries
    entries = [{"post_id": p["post_id"], "spans": infer.pseudonymize_spans(p)} for p in posts]
    entries = [e for e in infer.select_for_model(entries, max_spans=MAX_SPANS, max_per_type=MAX_PER_TYPE) if e["spans"]]
    return SYSTEM_V2, json.dumps({"user_ref": uref, "profile": None, "posts": entries}, ensure_ascii=False), entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=("v1", "v2"), required=True)
    ap.add_argument("--adapter", type=Path, help="어댑터 폴더 (기본: exp08 results/adapter · adapter_v2)")
    a = ap.parse_args()
    out = HERE / "results" / f"raw_{a.config}.jsonl"
    if out.exists():
        raise SystemExit(f"{out} 가 이미 있다 — exp22 는 구성마다 한 번만 돌린다 (README §2)")
    adapter = a.adapter or ADAPTERS[a.config]
    if a.config == "v1" and sha256(adapter / "adapter_model.safetensors") != V1_SHA256:
        raise SystemExit(f"v1 어댑터 해시가 다르다: {adapter}")
    model = infer.Stage2Model(adapter)
    torch = model._torch
    accounts = load_accounts()
    out.parent.mkdir(exist_ok=True)
    rows = []
    for acc in accounts:
        system, prompt, entries = model_input(a.config, user_ref(acc["account_id"]), acc["posts"])
        n_spans = sum(len(e["spans"]) for e in entries)
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        chat = model.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        ids = model.tok(chat, return_tensors="pt").to(model.model.device)
        t0 = time.perf_counter()
        with torch.no_grad():
            gen = model.model.generate(**ids, max_new_tokens=infer.output_budget(n_spans), do_sample=False,
                                       temperature=None, top_p=None, top_k=None)
        raw = model.tok.decode(gen[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        sec = round(time.perf_counter() - t0, 1)
        validated = infer.validate_findings(infer.parse_findings(raw), entries)
        rows.append({"account_id": acc["account_id"], "config": a.config, "prompt_tokens": int(ids["input_ids"].shape[1]),
                     "n_spans_in": n_spans, "entries": [{"post_id": e["post_id"], "span_ids": [s["span_id"] for s in e["spans"]]} for e in entries],
                     "raw": raw, "raw_findings": infer.parse_findings(raw), "validated": validated, "seconds": sec,
                     "truncated": not raw.rstrip().endswith("}")})
        print(f"{acc['account_id']} · 입력 {rows[-1]['prompt_tokens']} 토큰 · 스팬 {n_spans} · {sec}s · "
              f"{'검증 통과' if validated else '폴백'}", flush=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8", newline="\n")
    meta = {"config": a.config, "adapter": str(adapter), "adapter_sha256": sha256(adapter / "adapter_model.safetensors"),
            "system_sha256": hashlib.sha256((infer.SYSTEM_V1 if a.config == "v1" else SYSTEM_V2).encode()).hexdigest(),
            "stage1_manifest": json.loads((HERE / "data/stage1_manifest.json").read_text(encoding="utf-8")),
            "measured": time.strftime("%Y-%m-%d %H:%M"), "gpu": torch.cuda.get_device_name(0)}
    (HERE / "results" / f"raw_{a.config}_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
