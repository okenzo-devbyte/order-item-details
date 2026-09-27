from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..textnorm import fold_heavy, fold_light, norm, parse_pack_size
from .validate import ImportReport, validate_rows


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class TransformedData:
    products: list[tuple] = field(default_factory=list)
    customers: list[tuple] = field(default_factory=list)
    orders: list[tuple] = field(default_factory=list)
    order_items: list[tuple] = field(default_factory=list)
    barcodes: list[tuple] = field(default_factory=list)
    report: ImportReport = field(default_factory=ImportReport)


def transform(rows: list[dict[str, Any]]) -> TransformedData:
    """Turns raw workbook rows into five insert-ready batches.

    Ids are assigned here, densely, in first-seen order, so the Postgres loader
    never has to own id logic of its own.
    """
    usable, report = validate_rows(rows)

    product_ids: dict[str, int] = {}
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

    customer_ids: dict[str, int] = {}
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
        item_rows.append((order_id, product_id, row.get("qty"), row.get("price")))

    barcode_pairs = _barcode_pairs(usable, product_ids)

    report.products = len(product_ids)
    report.customers = len(customer_ids)
    report.orders = len(order_rows)
    report.barcodes = len(barcode_pairs)
    report.missing_pack_size_products = sum(1 for row in product_rows if row[8] is None)

    return TransformedData(
        products=product_rows,
        customers=customer_rows,
        orders=order_rows,
        order_items=item_rows,
        barcodes=barcode_pairs,
        report=report,
    )


def _barcode_pairs(
    usable: list[dict[str, Any]], product_ids: dict[str, int]
) -> list[tuple[int, str]]:
    """Distinct (product_id, barcode) pairs, sorted.

    A barcode may appear on many rows of the same product, so the pairs are
    deduplicated. It may also legitimately appear on two different products, so
    the set is keyed on the pair and never on the barcode alone.
    """
    pairs: set[tuple[int, str]] = set()
    for row in usable:
        product_id = product_ids[str(row["Product Name"]).strip()]
        for barcode in row.get("Bar_Code") or []:
            pairs.add((product_id, barcode))
    return sorted(pairs)
