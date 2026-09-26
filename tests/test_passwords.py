import sqlite3

from api.app_db import AppDB
from api.passwords import hash_password, verify_password
from api.users import (
    authenticate,
    bootstrap_admin,
    create_user,
    get_by_username,
    list_users,
    update_user,
)


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password(hashed, "correct horse battery staple")
    assert not verify_password(hashed, "wrong")


def test_create_and_authenticate(tmp_path):
    db = AppDB(tmp_path / "app.db")
    create_user(db, "somchai", "password123", "staff")
    assert authenticate(db, "somchai", "password123")["username"] == "somchai"
    assert authenticate(db, "somchai", "nope") is None
    db.close()


def test_inactive_user_cannot_authenticate(tmp_path):
    db = AppDB(tmp_path / "app.db")
    user_id = create_user(db, "somchai", "password123", "staff")
    update_user(db, user_id, is_active=False)
    assert authenticate(db, "somchai", "password123") is None
    db.close()


def test_username_is_unique(tmp_path):
    db = AppDB(tmp_path / "app.db")
    create_user(db, "somchai", "password123", "staff")
    try:
        create_user(db, "somchai", "password456", "staff")
        assert False, "duplicate username should fail"
    except sqlite3.IntegrityError:
        pass
    db.close()


def test_bootstrap_admin_only_once(tmp_path):
    db = AppDB(tmp_path / "app.db")
    assert bootstrap_admin(db, "admin", "change-me-now") is True
    assert bootstrap_admin(db, "admin2", "change-me-now") is False
    assert get_by_username(db, "admin")["role"] == "admin"
    db.close()


def test_list_and_update_role(tmp_path):
    db = AppDB(tmp_path / "app.db")
    user_id = create_user(db, "ana", "password123", "staff")
    update_user(db, user_id, role="admin")
    row = [u for u in list_users(db) if u["id"] == user_id][0]
    assert row["role"] == "admin"
    assert row["is_active"] == 1
    db.close()
