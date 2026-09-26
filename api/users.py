from __future__ import annotations

from datetime import datetime, timezone

from .app_db import AppDB
from .passwords import hash_password, verify_password

ROLES = ("staff", "admin")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_by_username(db: AppDB, username: str):
    return db.query_one("SELECT * FROM users WHERE username = ?", (username,))


def get_by_id(db: AppDB, user_id: int):
    return db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def create_user(db: AppDB, username: str, password: str, role: str) -> int:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    return db.run(
        "INSERT INTO users (username, password_hash, role, is_active, created_at)"
        " VALUES (?,?,?,1,?)",
        (username, hash_password(password), role, _now()),
    )


def authenticate(db: AppDB, username: str, password: str):
    row = get_by_username(db, username)
    if row is None or not row["is_active"]:
        return None
    if not verify_password(row["password_hash"], password):
        return None
    return row


def list_users(db: AppDB):
    return db.query_all(
        "SELECT id, username, role, is_active, created_at FROM users ORDER BY id"
    )


def update_user(
    db: AppDB,
    user_id: int,
    *,
    password: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> bool:
    if get_by_id(db, user_id) is None:
        return False
    if password is not None:
        db.run(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(password), user_id),
        )
    if role is not None:
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        db.run("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    if is_active is not None:
        db.run(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, user_id),
        )
    return True


def bootstrap_admin(db: AppDB, username: str, password: str) -> bool:
    row = db.query_one("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'")
    if row["n"]:
        return False
    create_user(db, username, password, "admin")
    return True
