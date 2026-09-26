from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

SCHEMA_PATH = Path(__file__).with_name("db_schema.sql")


class AppDB:
    """The writable database: users, refresh tokens, versions, audit log."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(
            path, isolation_level=None, check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.lock = threading.Lock()

    def run(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self.lock:
            cursor = self.conn.execute(sql, tuple(params))
            return cursor.lastrowid

    def query_one(self, sql: str, params: Iterable[Any] = ()):
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchone()

    def query_all(self, sql: str, params: Iterable[Any] = ()):
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def close(self) -> None:
        with self.lock:
            self.conn.close()
