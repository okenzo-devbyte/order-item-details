from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from api.config import Settings
from api.db import Database
from order_search.ingest.excel_reader import read_order_rows
from order_search.ingest.load import load_into_version


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load an order workbook into a new Postgres version."
    )
    parser.add_argument("source", help="path to the .xlsx file")
    parser.add_argument("--version", type=int, default=1)
    args = parser.parse_args()

    source = Path(args.source)
    if not source.is_file():
        print(f"source file not found: {source}", file=sys.stderr)
        return 2

    settings = Settings()
    if not settings.database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    database = Database(
        settings.database_url,
        settings.schema_item,
        settings.schema_sales,
        settings.schema_app,
    )
    try:
        database.migrate()
        data = load_into_version(
            database, read_order_rows(source), args.version, source_filename=source.name
        )
    finally:
        database.close()

    report = data.report
    print(f"rows read      : {report.rows_read}")
    print(f"rows imported  : {report.rows_imported}")
    print(f"rows skipped   : {report.rows_skipped}")
    print(f"products       : {report.products}")
    print(f"customers      : {report.customers}")
    print(f"orders         : {report.orders}")
    print(f"barcodes       : {report.barcodes}")
    print(f"no pack size   : {report.missing_pack_size_products}")
    print(f"wrote version  : {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())