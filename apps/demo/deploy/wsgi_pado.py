"""waitress 진입점 — 파도풀 API(:8000)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))            # apps/demo
import app as pado  # noqa: E402

application = pado.app
