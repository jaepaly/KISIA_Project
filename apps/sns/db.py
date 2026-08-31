"""SQLite 연결 하나만 담당한다. 스키마는 schema.sql 이 정본이다."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parents[1] / "data" / "interim" / "sns.db"


def db_path() -> Path:
    return Path(os.getenv("SNS_DB_PATH", DEFAULT_DB))


def connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p)
    c.row_factory = sqlite3.Row          # dict 처럼 쓸 수 있게
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init(conn: sqlite3.Connection) -> None:
    """schema.sql 을 그대로 실행한다. CREATE TABLE IF NOT EXISTS 라 여러 번 돌려도 된다."""
    conn.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    conn.commit()
