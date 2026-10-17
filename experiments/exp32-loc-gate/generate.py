"""exp32 — D1e 글 생성. exp29 generate.py 를 그대로 쓰고 입출력 경로만 이 실험 것으로 바꾼다 (README §2).

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python -u experiments/exp32-loc-gate/generate.py   (GEMINI_API_KEY 는 환경변수)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("gen29", HERE.parent / "exp29-media-place-rule" / "generate.py")
gen29 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen29)
gen29.PLAN = HERE / "data" / "plan.jsonl"
gen29.OUT = HERE / "data" / "posts.jsonl"

if __name__ == "__main__":
    sys.exit(gen29.main())
