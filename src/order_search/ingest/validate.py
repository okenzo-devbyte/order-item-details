from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REQUIRED_TEXT = ("Product Name", "Customer Name")


@dataclass
class ImportReport:
    """Counters produced by an import run.

    Every number here is asserted by the build tests, so a silent data loss
    cannot pass unnoticed. The product, customer, order and barcode counts are
    filled in by the builder rather than by validate_rows, because only the
    builder knows what it actually wrote.
    """

    rows_read: int = 0
    rows_imported: int = 0
    rows_skipped: int = 0
    products: int = 0
    customers: int = 0
    orders: int = 0
    barcodes: int = 0
    missing_barcode_rows: int = 0
    unparsed_date_rows: int = 0
    missing_pack_size_products: int = 0
    skipped_rows: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return "\n".join(
            [
                f"rows read      : {self.rows_read}",
                f"rows imported  : {self.rows_imported}",
                f"rows skipped   : {self.rows_skipped}",
                f"products       : {self.products}",
                f"customers      : {self.customers}",
                f"orders         : {self.orders}",
                f"barcodes       : {self.barcodes}",
                f"no barcode     : {self.missing_barcode_rows}",
                f"bad date       : {self.unparsed_date_rows}",
                f"no pack size   : {self.missing_pack_size_products}",
            ]
        )


def is_blank(value: object) -> bool:
    """A value counts as blank when it is None, a whitespace-only string, or an
    empty container (list, tuple, set or dict). Numbers such as ``0`` and
    ``False`` are not blank.
    """
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return str(value).strip() == ""


def validate_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], ImportReport]:
    """Splits rows into (usable, report).

    Row numbers are 1-based positions in the worksheet counting the header as
    row 1, so a number in a warning can be looked up directly in Excel. A row is
    skipped only when a field the search cannot work without is missing: without
    a product name there is nothing to search for, and without a customer name
    the purchase history cannot be attributed to anyone. The skipped row numbers
    are recorded on ``report.skipped_rows`` and mirrored in ``report.warnings``.
    """
    report = ImportReport(rows_read=len(rows))
    usable: list[dict[str, Any]] = []
    skipped: list[int] = []

    for position, row in enumerate(rows, start=2):
        missing = [name for name in REQUIRED_TEXT if is_blank(row.get(name))]
        if missing:
            skipped.append(position)
            report.warnings.append(
                f"row {position}: missing {', '.join(missing)}"
            )
            continue
        if is_blank(row.get("Bar_Code")):
            report.missing_barcode_rows += 1
        if row.get("date_from") is None:
            report.unparsed_date_rows += 1
        usable.append(row)

    report.skipped_rows = skipped
    report.rows_skipped = len(skipped)
    report.rows_imported = len(usable)
    return usable, report
