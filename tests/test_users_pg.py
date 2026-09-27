import pytest

from api.users import authenticate, bootstrap_admin, create_user, list_users, update_user


@pytest.fixture
def users_db(client_db):
    yield client_db
    client_db.run(f'TRUNCATE "{client_db.schema_app}"."users" CASCADE')


def test_create_and_authenticate(users_db):
    create_user(users_db, "boss", "password123", "admin")
    found = authenticate(users_db, "boss", "password123")
    assert found["role"] == "admin"
    assert found["is_active"] is True


def test_a_wrong_password_does_not_authenticate(users_db):
    create_user(users_db, "boss", "password123", "admin")
    assert authenticate(users_db, "boss", "wrong") is None


def test_an_unknown_role_is_rejected(users_db):
    with pytest.raises(ValueError):
        create_user(users_db, "boss", "password123", "wizard")


def test_bootstrap_only_fires_when_no_admin_exists(users_db):
    assert bootstrap_admin(users_db, "root", "password123") is True
    assert bootstrap_admin(users_db, "other", "password123") is False
    assert len(list_users(users_db)) == 1


def test_deactivating_a_user_blocks_login(users_db):
    user_id = create_user(users_db, "staff1", "password123", "staff")
    update_user(users_db, user_id, is_active=False)
    assert authenticate(users_db, "staff1", "password123") is None