import pytest

from api import security, users


@pytest.fixture
def session_db(client_db):
    create = users.create_user(client_db, "boss", "password123", "admin")
    yield client_db, create
    client_db.run(f'TRUNCATE "{client_db.schema_app}"."users" CASCADE')


def issue(db):
    user = users.get_by_username(db, "boss")
    return security.issue_session(
        db, "test-secret", user,
        security.timedelta(minutes=15), security.timedelta(days=7),
    )


def test_a_refresh_token_is_single_use(session_db):
    db, _user_id = session_db
    _access, refresh = issue(db)
    security.rotate_refresh(
        db, "test-secret", refresh, security.timedelta(minutes=15),
        security.timedelta(days=7), security.timedelta(minutes=30),
    )
    with pytest.raises(security.InvalidToken):
        security.rotate_refresh(
            db, "test-secret", refresh, security.timedelta(minutes=15),
            security.timedelta(days=7), security.timedelta(minutes=30),
        )


def test_revoking_everything_blocks_the_user(session_db):
    db, user_id = session_db
    _access, refresh = issue(db)
    security.revoke_all_for_user(db, user_id)
    with pytest.raises(security.InvalidToken):
        security.rotate_refresh(
            db, "test-secret", refresh, security.timedelta(minutes=15),
            security.timedelta(days=7), security.timedelta(minutes=30),
        )


def test_a_rotation_refreshes_the_idle_window(session_db):
    db, _user_id = session_db
    _access, refresh = issue(db)
    _access2, _refresh2 = security.rotate_refresh(
        db, "test-secret", refresh, security.timedelta(minutes=15),
        security.timedelta(days=7), security.timedelta(minutes=30),
    )
    old_jti = security.decode_token("test-secret", refresh, security.REFRESH)["jti"]
    row = db.one(
        'SELECT last_used_at, revoked FROM "t_app"."refresh_tokens" WHERE id = %s',
        (old_jti,),
    )
    assert row["revoked"] is True
    assert row["last_used_at"] is not None
