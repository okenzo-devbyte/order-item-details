from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from order_search.search.engine import SearchEngine
from order_search.search.filters import Filters


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query an imported snapshot."
    )
    parser.add_argument("query", nargs="?", default="", help="search text")
    parser.add_argument("--db", required=True, help="path to the SQLite file")
    parser.add_argument("--mode", default="auto",
                        choices=["auto", "customer", "product"])
    parser.add_argument("--store", action="append", default=[])
    parser.add_argument("--order-type", action="append", default=[])
    parser.add_argument("--vip", action="append", default=[])
    parser.add_argument("--dept", action="append", default=[])
    parser.add_argument("--class", dest="class_code", action="append", default=[])
    parser.add_argument("--subclass", dest="subclass_code", action="append", default=[])
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--cursor", default=None)
    parser.add_argument(
        "--suggest", default=None, help="return prefix suggestions instead"
    )
    args = parser.parse_args()

    db = Path(args.db)
    if not db.is_file():
        print(f"database not found: {db}", file=sys.stderr)
        print("run scripts/import_excel.py first", file=sys.stderr)
        return 2

    connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    try:
        engine = SearchEngine(connection)
        if args.suggest is not None:
            payload = {
                "suggestions": engine.suggest(args.suggest, limit=args.limit)
            }
        else:
            try:
                filters = Filters(
                    store_code=tuple(args.store),
                    order_type=tuple(args.order_type),
                    vip_group=tuple(args.vip),
                    dept=tuple(int(v) for v in args.dept),
                    class_code=tuple(int(v) for v in args.class_code),
                    subclass_code=tuple(int(v) for v in args.subclass_code),
                    date_from=args.date_from,
                    date_to=args.date_to,
                )
            except ValueError as exc:
                print(f"invalid filter: {exc}", file=sys.stderr)
                return 2
            try:
                payload = engine.search(
                    args.query,
                    mode=args.mode,
                    filters=filters,
                    limit=args.limit,
                    cursor=args.cursor,
                )
            except ValueError as exc:
                print(f"invalid search: {exc}", file=sys.stderr)
                return 2
    finally:
        connection.close()

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
