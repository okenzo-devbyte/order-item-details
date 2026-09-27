from __future__ import annotations

import sqlite3
from typing import Any

from .schema_path import SCHEMA_PATH
from .transform import transform


def apply_schema(connection: sqlite3.Connection) -> None:
    assert connection.isolation_level is None, (
        "apply_schema requires an autocommit connection (isolation_level=None);"
        " passing a transactional connection would implicitly commit it"
    )
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def build_database(
    rows: list[dict[str, Any]],
    connection: sqlite3.Connection,
) -> Any:
    data = transform(rows)
    apply_schema(connection)

    connection.execute("BEGIN")
    try:
        connection.executemany(
            "INSERT INTO products (id, name, name_norm, name_fold_light,"
            " name_fold_heavy, dept, class_code, subclass_code, pack_size, unit)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            data.products,
        )
        connection.executemany(
            "INSERT INTO customers (id, name, name_norm, name_fold_light,"
            " name_fold_heavy) VALUES (?,?,?,?,?)",
            data.customers,
        )
        connection.executemany(
            "INSERT INTO orders (id, order_no, store_code, customer_id,"
            " order_type, date_from, date_to, item_remark, vip_remark, vip_group)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            data.orders,
        )
        connection.executemany(
            "INSERT INTO order_items (order_id, product_id, qty, price)"
            " VALUES (?,?,?,?)",
            data.order_items,
        )
        connection.executemany(
            "INSERT INTO product_barcodes (product_id, barcode) VALUES (?,?)",
            data.barcodes,
        )
        connection.executemany(
            "INSERT INTO products_fts (name_norm, name_fold_light, product_id)"
            " VALUES (?,?,?)",
            [(r[2], r[3], r[0]) for r in data.products],
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

    report = data.report
    connection.executemany(
        "INSERT INTO meta (key, value) VALUES (?,?)",
        [
            ("rows_read", str(report.rows_read)),
            ("rows_imported", str(report.rows_imported)),
            ("rows_skipped", str(report.rows_skipped)),
            ("products", str(report.products)),
            ("customers", str(report.customers)),
            ("barcodes", str(report.barcodes)),
        ],
    )
    return report
