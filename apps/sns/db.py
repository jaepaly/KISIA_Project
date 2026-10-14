"""SQLite 연결 하나만 담당한다. 스키마는 schema.sql 이 정본이다."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parents[1] / "data" / "interim" / "sns.db"


def db_path() -> Path:
    return Path(os.getenv("SNS_DB_PATH", DEFAULT_DB))


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = path or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p)
    c.row_factory = sqlite3.Row          # dict 처럼 쓸 수 있게
    c.execute("PRAGMA foreign_keys = ON")
    # 방문자 표 맞추기는 파일마다 이 프로세스에서 한 번만 — 요청마다 DDL 을 다시 돌리지 않는다 (A7).
    # 새 세션 사본은 만들 때 표를 넣으므로(app._session_db_path) 지웠다 다시 만든 사본도 표가 있다
    key = str(Path(p).resolve())
    if key not in _ensured:
        ensure_visitor_tables(c)
        if len(_ensured) > 20_000:   # 세션 사본 경로가 계속 쌓이지 않게 — 비우면 다음에 한 번씩 다시 확인할 뿐이다
            _ensured.clear()
        _ensured.add(key)
    return c


def init(conn: sqlite3.Connection) -> None:
    """schema.sql 을 그대로 실행한다. CREATE TABLE IF NOT EXISTS 라 여러 번 돌려도 된다."""
    conn.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    conn.commit()



# schema.sql 끝의 방문자용 표(me · action_log). 시드 사본이나 이 표가 생기기 전에 만든 세션 사본도
# 열 때 맞물리게 — 전부 IF NOT EXISTS 라 이미 있으면 아무 일도 하지 않는다. 정본은 schema.sql 의 표시 줄 아래다
_VISITOR_MARK = "-- ── 방문자 체험용"
_visitor_ddl: str | None = None
_ensured: set[str] = set()


def ensure_visitor_tables(conn: sqlite3.Connection) -> None:
    global _visitor_ddl
    if _visitor_ddl is None:
        text = (HERE / "schema.sql").read_text(encoding="utf-8")
        _visitor_ddl = text[text.index(_VISITOR_MARK):]
    conn.executescript(_visitor_ddl)
    # 표는 있는데 나중에 생긴 칸이 없는 옛 세션 사본 — 칸만 더한다
    cols = {r[1] for r in conn.execute("PRAGMA table_info(action_log)")}
    if "group_id" not in cols:
        conn.execute("ALTER TABLE action_log ADD COLUMN group_id INTEGER")
        conn.commit()
