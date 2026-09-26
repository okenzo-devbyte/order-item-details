from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from ..textnorm import fold_heavy, fold_light, norm, parse_pack_size
from .schema_path import SCHEMA_PATH
from .validate import ImportReport, validate_rows


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


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_database(
    rows: list[dict[str, Any]],
    connection: sqlite3.Connection,
) -> ImportReport:
    """Writes rows into a freshly created schema and returns the import report.

    The connection must be autocommit (isolation_level=None) because this
    function manages its own transaction. The whole insert set is one
    transaction: either every row lands or none does.
    """
    usable, report = validate_rows(rows)
    apply_schema(connection)

    product_ids: dict[str, int] = {}
    customer_ids: dict[str, int] = {}
    barcode_pairs: set[tuple[int, str]] = set()

    product_rows: list[tuple] = []
    for row in usable:
        name = str(row["Product Name"]).strip()
        if name in product_ids:
            continue
        product_ids[name] = len(product_ids) + 1
        product_rows.append(
            (
                product_ids[name],
                name,
                norm(name),
                fold_light(name),
                fold_heavy(name),
                row.get("Dept"),
                row.get("Class"),
                row.get("Subclass"),
                parse_pack_size(name),
                None,  # unit is absent from the source file, so never guessed
            )
        )

    customer_rows: list[tuple] = []
    for row in usable:
        name = str(row["Customer Name"]).strip()
        if name in customer_ids:
            continue
        customer_ids[name] = len(customer_ids) + 1
        customer_rows.append(
            (
                customer_ids[name],
                name,
                norm(name),
                fold_light(name),
                fold_heavy(name),
            )
        )

    order_rows: list[tuple] = []
    item_rows: list[tuple] = []
    for order_id, row in enumerate(usable, start=1):
        product_id = product_ids[str(row["Product Name"]).strip()]
        customer_id = customer_ids[str(row["Customer Name"]).strip()]
        order_rows.append(
            (
                order_id,
                _text(row.get("NO.")),
                _text(row.get("Store Code")),
                customer_id,
                _text(row.get("Order Type")),
                _iso(row.get("date_from")),
                _iso(row.get("date_to")),
                _text(row.get("Item Remark")),
                _text(row.get("VIP Customer Remarks")),
                _text(row.get("VIP Customer Groups")),
            )
        )
        item_rows.append(
            (order_id, product_id, row.get("qty"), row.get("price"))
        )
        for barcode in row.get("Bar_Code") or []:
            barcode_pairs.add((product_id, barcode))

    connection.execute("BEGIN")
    try:
        connection.executemany(
            "INSERT INTO products (id, name, name_norm, name_fold_light,"
            " name_fold_heavy, dept, class_code, subclass_code, pack_size, unit)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            product_rows,
        )
        connection.executemany(
            "INSERT INTO customers (id, name, name_norm, name_fold_light,"
            " name_fold_heavy) VALUES (?,?,?,?,?)",
            customer_rows,
        )
        connection.executemany(
            "INSERT INTO orders (id, order_no, store_code, customer_id,"
            " order_type, date_from, date_to, item_remark, vip_remark, vip_group)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            order_rows,
        )
        connection.executemany(
            "INSERT INTO order_items (order_id, product_id, qty, price)"
            " VALUES (?,?,?,?)",
            item_rows,
        )
        connection.executemany(
            "INSERT INTO product_barcodes (product_id, barcode) VALUES (?,?)",
            sorted(barcode_pairs),
        )
        connection.executemany(
            "INSERT INTO products_fts (name_norm, name_fold_light, product_id)"
            " VALUES (?,?,?)",
            [(r[2], r[3], r[0]) for r in product_rows],
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

    report.products = len(product_ids)
    report.customers = len(customer_ids)
    report.orders = len(order_rows)
    report.barcodes = len(barcode_pairs)
    report.missing_pack_size_products = sum(
        1 for row in product_rows if row[8] is None
    )
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
