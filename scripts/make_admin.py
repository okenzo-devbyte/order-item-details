from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from api.app_db import AppDB
from api.users import create_user, get_by_username, update_user


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or reset an admin account in app.db."
    )
    parser.add_argument("--db", required=True, help="path to app.db")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default="admin", choices=("staff", "admin"))
    args = parser.parse_args()

    db = AppDB(Path(args.db))
    try:
        existing = get_by_username(db, args.username)
        if existing is None:
            create_user(db, args.username, args.password, args.role)
            print(f"created {args.role} {args.username}")
        else:
            update_user(
                db,
                existing["id"],
                password=args.password,
                role=args.role,
                is_active=True,
            )
            print(f"updated {args.role} {args.username}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
