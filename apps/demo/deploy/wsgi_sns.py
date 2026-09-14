"""waitress 진입점 — Veilo(:3000). `python apps/demo/sns_ext.py` 와 같은 앱을 개발 서버 대신 waitress 로 띄운다."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))            # apps/demo
import sns_ext  # noqa: E402

c = sns_ext.sns.connect()
sns_ext.sns.init(c)
c.close()
application = sns_ext.app
