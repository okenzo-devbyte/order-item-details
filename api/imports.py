from __future__ import annotations

import sqlite3
from pathlib import Path

from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows


def build_snapshot_bytes(xlsx_path: Path):
    """Returns (serialized_sqlite_bytes, ImportReport) for an uploaded workbook."""
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        report = build_database(read_order_rows(xlsx_path), connection)
        return connection.serialize(), report
    finally:
        connection.close()
