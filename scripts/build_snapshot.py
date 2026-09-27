from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from api import crypto
from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build an encrypted SQLite snapshot from an order workbook."
    )
    parser.add_argument("source", help="path to the .xlsx file")
    parser.add_argument("--out", required=True, help="path of snapshot.enc")
    parser.add_argument("--key", default=os.environ.get("DATA_KEY", ""))
    parser.add_argument("--key-id", default=os.environ.get("DATA_KEY_ID", "v1"))
    args = parser.parse_args()

    source = Path(args.source)
    if not source.is_file():
        print(f"source file not found: {source}", file=sys.stderr)
        return 2
    if not args.key:
        print("DATA_KEY is required (env or --key)", file=sys.stderr)
        return 2

    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        report = build_database(read_order_rows(source), connection)
        plaintext = connection.serialize()
    finally:
        connection.close()

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(crypto.seal(plaintext, crypto.load_key(args.key), args.key_id))

    print(report.summary())
    print(f"key_id   : {args.key_id}")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
