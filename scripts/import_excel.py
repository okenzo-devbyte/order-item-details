from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import an order workbook into a SQLite snapshot."
    )
    parser.add_argument("source", help="path to the .xlsx file")
    parser.add_argument(
        "--out", required=True, help="path of the SQLite file to create"
    )
    args = parser.parse_args()

    source = Path(args.source)
    if not source.is_file():
        print(f"source file not found: {source}", file=sys.stderr)
        return 2

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    rows = read_order_rows(source)
    connection = sqlite3.connect(target, isolation_level=None)
    try:
        report = build_database(rows, connection)
    finally:
        connection.close()

    print(report.summary())
    for warning in report.warnings[:20]:
        print(f"  warning: {warning}")
    if len(report.warnings) > 20:
        print(f"  ... and {len(report.warnings) - 20} more warnings")
    print(f"\nwrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
