from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from api.config import Settings
from api.db import Database
from api.users import bootstrap_admin, create_user, get_by_username, update_user


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or reset an admin account in Postgres."
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default="admin", choices=("staff", "admin"))
    args = parser.parse_args()

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
        existing = get_by_username(database, args.username)
        if existing is None:
            create_user(database, args.username, args.password, args.role)
            print(f"created {args.role} {args.username}")
        else:
            update_user(
                database,
                existing["id"],
                password=args.password,
                role=args.role,
                is_active=True,
            )
            print(f"updated {args.role} {args.username}")
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())