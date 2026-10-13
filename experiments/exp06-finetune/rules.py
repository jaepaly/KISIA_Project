"""옮겼다 → ``src/kopl/c1_span/rules.py`` (README W9 D 9번 · 동작 그대로).

실험 스크립트 · 테스트의 ``import rules`` 이 계속 돌도록 같은 모듈 객체를 돌려준다 — 복사본이 아니라서
한쪽을 패치하면 다른 쪽에도 보인다. ``src`` 는 PYTHONPATH 에 없어도 여기서 찾는다.
"""
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"  # kopl 을 PYTHONPATH 없이도 찾게 (D 9번 전엔 src 가 필요 없었다)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from kopl.c1_span import rules as _impl

if __name__ != "__main__":  # 직접 실행하면 전처럼 아무것도 하지 않고 끝난다
    sys.modules[__name__] = _impl
