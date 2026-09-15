"""로컬 대시보드 — gh CLI로 현황을 뽑아 브라우저로 연다.

사전 조건:
  1. gh CLI 설치  (winget install GitHub.cli  /  brew install gh)
  2. gh auth login  (최초 1회)
  3. 저장소 루트에서 실행:  python scripts/open_dashboard.py

⚠️ 저장소가 비공개라 브라우저에서 GitHub API 실시간 갱신은 안 된다.
   대신 gh CLI 로 뽑은 스냅샷이 열린다 — 정보는 동일하다.
"""
import pathlib
import subprocess
import sys
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "index.html"


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)

    print("대시보드 생성 중...", flush=True)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_dashboard.py")],
        capture_output=True,
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        sys.stderr.buffer.write(result.stderr)
        print("오류: build_dashboard.py 실패. gh auth login 완료 여부 확인.", file=sys.stderr)
        sys.exit(1)

    OUT.write_bytes(result.stdout)
    size = OUT.stat().st_size
    print(f"생성 완료 ({size:,} bytes) -> {OUT}")
    webbrowser.open(OUT.as_uri())


if __name__ == "__main__":
    main()
