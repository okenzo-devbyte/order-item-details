from __future__ import annotations

from .passwords import hash_password, verify_password

ROLES = ("staff", "admin")


def _users(schema: str) -> str:
    return f'"{schema}"."users"'


def get_by_username(db, username: str):
    return db.one(
        f"SELECT * FROM {_users(db.schema_app)} WHERE username = %s", (username,)
    )


def get_by_id(db, user_id: int):
    return db.one(f"SELECT * FROM {_users(db.schema_app)} WHERE id = %s", (user_id,))


def create_user(db, username: str, password: str, role: str) -> int:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    db.run(
        f"INSERT INTO {_users(db.schema_app)}"
        " (username, password_hash, role, is_active, created_at)"
        " VALUES (%s,%s,%s,true,now())",
        (username, hash_password(password), role),
    )
    return db.one(
        f"SELECT id FROM {_users(db.schema_app)} WHERE username = %s", (username,)
    )["id"]


def authenticate(db, username: str, password: str):
    row = get_by_username(db, username)
    if row is None or not row["is_active"]:
        return None
    if not verify_password(row["password_hash"], password):
        return None
    return row


def list_users(db):
    return db.all(
        f"SELECT id, username, role, is_active, created_at"
        f" FROM {_users(db.schema_app)} ORDER BY id"
    )


def update_user(db, user_id: int, *, password=None, role=None, is_active=None) -> bool:
    if get_by_id(db, user_id) is None:
        return False
    table = _users(db.schema_app)
    if password is not None:
        db.run(
            f"UPDATE {table} SET password_hash = %s WHERE id = %s",
            (hash_password(password), user_id),
        )
    if role is not None:
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        db.run(f"UPDATE {table} SET role = %s WHERE id = %s", (role, user_id))
    if is_active is not None:
        db.run(
            f"UPDATE {table} SET is_active = %s WHERE id = %s", (is_active, user_id)
        )
    return True


def bootstrap_admin(db, username: str, password: str) -> bool:
    row = db.one(
        f"SELECT count(*) AS n FROM {_users(db.schema_app)} WHERE role = 'admin'"
    )
    if row["n"]:
        return False
    create_user(db, username, password, "admin")
    return True