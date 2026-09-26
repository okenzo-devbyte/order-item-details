from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from order_search.search.engine import SearchEngine

from . import crypto

FACET_COLUMNS = {
    "store_code": ("orders", "store_code"),
    "order_type": ("orders", "order_type"),
    "vip_group": ("orders", "vip_group"),
    "dept": ("products", "dept"),
    "class_code": ("products", "class_code"),
    "subclass_code": ("products", "subclass_code"),
}


class SnapshotStore:
    """Owns the decrypted snapshot connection and every read against it.

    The connection is built once, held in memory only, and shared behind a
    single lock. Callers never touch it directly.
    """

    def __init__(self, keyring: dict[str, bytes], key_id: str = "v1") -> None:
        self._keyring = keyring
        self._key_id = key_id
        self._connection: sqlite3.Connection | None = None
        self.lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._connection is not None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("snapshot is not loaded")
        return self._connection

    @staticmethod
    def _build(plaintext: bytes) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.deserialize(plaintext)
        connection.execute(
            "INSERT INTO products_fts(products_fts) VALUES('rebuild')"
        )
        connection.execute("PRAGMA query_only=ON")
        return connection

    def replace_with_bytes(self, plaintext: bytes) -> None:
        fresh = self._build(plaintext)
        with self.lock:
            previous, self._connection = self._connection, fresh
        if previous is not None:
            previous.close()

    def load_file(self, path: str | Path) -> None:
        plaintext = crypto.open_sealed(Path(path).read_bytes(), self._keyring)
        self.replace_with_bytes(plaintext)

    def _engine(self) -> SearchEngine:
        return SearchEngine(self.connection)

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        with self.lock:
            return self._engine().search(query, **kwargs)

    def suggest(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        with self.lock:
            return self._engine().suggest(query, limit=limit)

    def customer_history(self, customer_id: int, filters: Any = None):
        with self.lock:
            return self._engine().customer_history(customer_id, filters)

    def product_customers(self, product_id: int, filters: Any = None):
        with self.lock:
            return self._engine().product_customers(product_id, filters)

    def facets(self) -> dict[str, list]:
        out: dict[str, list] = {}
        with self.lock:
            for name, (table, column) in FACET_COLUMNS.items():
                rows = self.connection.execute(
                    f"SELECT DISTINCT {column} AS v FROM {table}"
                    f" WHERE {column} IS NOT NULL ORDER BY {column}"
                ).fetchall()
                out[name] = [row["v"] for row in rows]
        return out

    def counts(self) -> dict[str, int]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT key, value FROM meta"
            ).fetchall()
        return {row["key"]: int(row["value"]) for row in rows}

    def close(self) -> None:
        with self.lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
