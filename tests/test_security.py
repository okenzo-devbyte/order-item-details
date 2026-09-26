from datetime import timedelta

import pytest

from api import security
from api.app_db import AppDB
from api.users import create_user, get_by_id

SECRET = "test-secret"


def make_db_with_user(tmp_path):
    db = AppDB(tmp_path / "app.db")
    user_id = create_user(db, "somchai", "password123", "admin")
    return db, get_by_id(db, user_id)


def test_issue_and_decode_access(tmp_path):
    db, user = make_db_with_user(tmp_path)
    access, _ = security.issue_session(
        db, SECRET, user, timedelta(minutes=15), timedelta(days=7)
    )
    payload = security.decode_token(SECRET, access, security.ACCESS)
    assert payload["sub"] == str(user["id"])
    assert payload["role"] == "admin"
    db.close()


def test_expired_access_is_rejected(tmp_path):
    db, user = make_db_with_user(tmp_path)
    access, _ = security.issue_session(
        db, SECRET, user, timedelta(seconds=-1), timedelta(days=7)
    )
    with pytest.raises(security.InvalidToken):
        security.decode_token(SECRET, access, security.ACCESS)
    db.close()


def test_wrong_type_is_rejected(tmp_path):
    db, user = make_db_with_user(tmp_path)
    access, _ = security.issue_session(
        db, SECRET, user, timedelta(minutes=15), timedelta(days=7)
    )
    with pytest.raises(security.InvalidToken):
        security.decode_token(SECRET, access, security.REFRESH)
    db.close()


def test_refresh_rotation_revokes_old_token(tmp_path):
    db, user = make_db_with_user(tmp_path)
    _, refresh = security.issue_session(
        db, SECRET, user, timedelta(minutes=15), timedelta(days=7)
    )
    security.rotate_refresh(
        db, SECRET, refresh, timedelta(minutes=15), timedelta(days=7),
        timedelta(minutes=30),
    )
    with pytest.raises(security.InvalidToken):
        security.rotate_refresh(
            db, SECRET, refresh, timedelta(minutes=15), timedelta(days=7),
            timedelta(minutes=30),
        )
    db.close()


def test_idle_timeout_revokes(tmp_path):
    db, user = make_db_with_user(tmp_path)
    _, refresh = security.issue_session(
        db, SECRET, user, timedelta(minutes=15), timedelta(days=7)
    )
    db.run(
        "UPDATE refresh_tokens SET last_used_at = ?",
        ("2000-01-01T00:00:00Z",),
    )
    with pytest.raises(security.InvalidToken):
        security.rotate_refresh(
            db, SECRET, refresh, timedelta(minutes=15), timedelta(days=7),
            timedelta(minutes=30),
        )
    db.close()


def test_revoke_all_for_user(tmp_path):
    db, user = make_db_with_user(tmp_path)
    _, refresh = security.issue_session(
        db, SECRET, user, timedelta(minutes=15), timedelta(days=7)
    )
    security.revoke_all_for_user(db, user["id"])
    with pytest.raises(security.InvalidToken):
        security.rotate_refresh(
            db, SECRET, refresh, timedelta(minutes=15), timedelta(days=7),
            timedelta(minutes=30),
        )
    db.close()
