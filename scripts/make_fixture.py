from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from order_search.ingest.excel_reader import read_order_rows

HEADER = [
    "Store Code",
    "Order Type",
    "Product Name",
    "NO.",
    "Dept",
    "Class",
    "Subclass",
    "Bar_Code",
    "Customer Name",
    "Item Remark",
    "VIP Customer Remarks",
    "VIP Customer Groups",
    "Original Expected Date",
]
ORDER_TYPES = [
    "Standard delivery",
    "Scheduled delivery",
    "Express delivery",
    "Pickup",
]
REMARKS = ["โทรแจ้งก่อนส่ง", "แพ็คแยก", "ส่งก่อน 12:00", None]
TIERS = ["VIP", "Gold", "Platinum", "Wholesale VIP", None]


def stamp(start: date, days: int) -> str:
    end = start + timedelta(days=days)
    fmt = "%d-%b-%Y"
    if end == start:
        return start.strftime(fmt)
    return f"{start.strftime(fmt)} - {end.strftime(fmt)}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a synthetic workbook with varied dates."
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--source", default=None,
                        help="workbook to take products and customers from")
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    source = Path(args.source) if args.source else (
        Path(__file__).resolve().parents[1]
        / "sample_order_data_1000_records.xlsx"
    )
    if not source.is_file():
        print(f"source not found: {source}", file=sys.stderr)
        return 2

    original = read_order_rows(source)
    products = sorted({row["Product Name"] for row in original})
    customers = sorted({row["Customer Name"] for row in original})
    barcodes: dict[str, list[str]] = {}
    for row in original:
        barcodes.setdefault(row["Product Name"], row["Bar_Code"])
    stores = sorted({str(row["Store Code"]) for row in original})
    hierarchy = {
        row["Product Name"]: (row["Dept"], row["Class"], row["Subclass"])
        for row in original
    }

    rng = random.Random(args.seed)
    base = date(2026, 1, 1)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Order Data"
    sheet.append(HEADER)

    for number in range(1, args.rows + 1):
        product = rng.choice(products)
        dept, klass, sub = hierarchy[product]
        codes = barcodes.get(product) or []
        cell = " || ".join(codes) if codes else ""
        start = base + timedelta(days=rng.randint(0, 300))
        sheet.append(
            [
                rng.choice(stores),
                rng.choice(ORDER_TYPES),
                product,
                number,
                dept,
                klass,
                sub,
                cell,
                rng.choice(customers),
                rng.choice(REMARKS),
                rng.choice(REMARKS),
                rng.choice(TIERS),
                stamp(start, rng.choice([0, 0, 1, 2, 5])),
            ]
        )

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(target)
    print(f"wrote {target} with {args.rows} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
