from __future__ import annotations

import sqlite3

from .schema_path import SCHEMA_PATH


def apply_schema(connection: sqlite3.Connection) -> None:
    """Drops and recreates every table. Callers pass an autocommit connection
    (isolation_level=None)."""
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
