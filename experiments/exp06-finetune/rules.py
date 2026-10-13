"""옮겼다 → ``src/kopl/c1_span/rules.py`` (README W9 D 9번 · 동작 그대로).

실험 스크립트 · 테스트의 ``import rules`` 이 계속 돌도록 같은 모듈 객체를 돌려준다 — 복사본이 아니라서
한쪽을 패치하면 다른 쪽에도 보인다. ``src`` 가 PYTHONPATH 에 있어야 한다 (전에도 그랬다).
"""
import sys

from kopl.c1_span import rules as _impl

if __name__ == "__main__":
    raise SystemExit("rules 는 실행 스크립트가 아니다")
else:
    sys.modules[__name__] = _impl
