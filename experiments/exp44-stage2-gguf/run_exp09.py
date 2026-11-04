"""exp09 2단 v2 구성(105명 · 239편)을 GGUF 엔진(Stage2GGUF)으로 다시 — NF4 저장 결과와 비교용.

    PYTHONIOENCODING=utf-8 PYTHONPATH="src;." STAGE2_GGUF=<stage2v2-dq-Q5_K_M.gguf> LLAMA_SERVER=<llama-server.exe> \\
        python experiments/exp44-stage2-gguf/run_exp09.py [--out <파일>]

입력 · 상한 · 출력 상한은 exp09 run_config.py --config v2 와 한 줄도 다르지 않다(config_input 을 그대로 부른다).
생성만 Stage2GGUF.generate(앱 경로와 같은 함수)로 바꾼다. 출력 형식도 run_config 와 같다 → exp09 score.py 로 채점된다.
기본 출력: experiments/exp09-external-agreement/data/qwen_cfg_v2_gguf.jsonl (data/*.jsonl 은 커밋하지 않는다) · 이미 있으면 멈춘다
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP09 = ROOT / "experiments/exp09-external-agreement"
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(EXP09), str(ROOT / "experiments/exp08-stage2-sft")]

from kopl.c4_stage2 import infer  # noqa: E402
from run_config import config_input, sha256  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=EXP09 / "data/qwen_cfg_v2_gguf.jsonl")
    a = ap.parse_args()
    if a.out.exists():
        raise SystemExit(f"{a.out} 가 이미 있다 — 한 번만")
    rows = [json.loads(l) for l in (EXP09 / "data/inputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    t_load = time.time()
    model = infer.Stage2GGUF()            # STAGE2_GGUF · LLAMA_SERVER · 해시 확인 · 127.0.0.1
    load_s = round(time.time() - t_load, 1)
    recs = []
    try:
        for r in rows:
            system, prompt, entries = config_input("v2", r)
            assert system == infer.SYSTEM_V2
            t0 = time.time()
            text = model.generate(prompt, max_new_tokens=infer.output_budget(entries))
            rec = {"persona_id": r["persona_id"], "model": f"{infer.MODEL_VERSION_GGUF}", "config": "v2",
                   "findings": None, "error": None, "sec": round(time.time() - t0, 1), "raw": text,
                   "n_spans_in": sum(len(e["spans"]) for e in entries), "truncated": not text.rstrip().endswith("}")}
            try:
                rec["findings"] = json.loads(text[text.index("{"): text.rindex("}") + 1])["findings"]
            except Exception as e:  # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            # 앱이 실제로 쓰는 값 — validate_findings(None 이면 앱은 규칙으로 폴백)
            rec["app_valid"] = infer.validate_findings(infer.parse_findings(text), entries) is not None
            recs.append(rec)
            print(r["persona_id"], "ok" if rec["findings"] else f"FAIL {rec['error']}", rec["sec"], "s", flush=True)
    finally:
        model.close()
    a.out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in recs), encoding="utf-8", newline="\n")
    gguf = Path(__import__("os").environ["STAGE2_GGUF"])
    (HERE / "results/run_exp09_meta.json").write_text(json.dumps({
        "engine": infer.MODEL_VERSION_GGUF, "gguf_sha256": infer.GGUF_SHA256, "gguf_name": gguf.name,
        "inputs_sha256": sha256(EXP09 / "data/inputs.jsonl"), "external_sha256": sha256(EXP09 / "data/external.jsonl"),
        "out_sha256": sha256(a.out), "server_load_s": load_s, "measured": time.strftime("%Y-%m-%d %H:%M")},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
