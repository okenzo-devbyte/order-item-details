from __future__ import annotations

import sqlite3

from .schema_path import SCHEMA_PATH


def apply_schema(connection: sqlite3.Connection) -> None:
    """Drops and recreates the seven snapshot tables (plus FTS shadows).

    Destructive by design: every call wipes rows in products, customers,
    orders, order_items, product_barcodes, products_fts and meta. Tables this
    file does not own — `users`, `audit_log`, or anything a later plan adds
    to a separate file — are left untouched.

    The connection must be autocommit (isolation_level=None). `executescript`
    issues an implicit COMMIT first, so on a non-autocommit connection it
    would silently commit the caller's pending transaction. The assert makes
    that misuse fail loudly instead.
    """
    assert connection.isolation_level is None, (
        "apply_schema requires an autocommit connection (isolation_level=None);"
        " passing a transactional connection would implicitly commit it"
    )
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
