import pytest
from fastapi.testclient import TestClient

from api.main import create_app

from test_api_boot import make_settings


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as test_client:
        test_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me-now"},
        )
        yield test_client


def csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


def test_list_users(client):
    response = client.get("/api/v1/admin/users")
    assert response.status_code == 200
    assert any(user["username"] == "admin" for user in response.json()["users"])


def test_create_and_update_user(client):
    response = client.post(
        "/api/v1/admin/users",
        json={"username": "somchai", "password": "password123", "role": "staff"},
        headers=csrf(client),
    )
    assert response.status_code == 201
    user_id = response.json()["id"]
    patched = client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"role": "admin"},
        headers=csrf(client),
    )
    assert patched.status_code == 200
    assert patched.json()["role"] == "admin"


def test_mutation_requires_csrf_header(client):
    response = client.post(
        "/api/v1/admin/users",
        json={"username": "somchai", "password": "password123", "role": "staff"},
    )
    assert response.status_code == 403


def test_staff_cannot_reach_admin(client):
    client.post(
        "/api/v1/admin/users",
        json={"username": "staffy", "password": "password123", "role": "staff"},
        headers=csrf(client),
    )
    staff = TestClient(client.app)
    staff.post(
        "/api/v1/auth/login",
        json={"username": "staffy", "password": "password123"},
    )
    assert staff.get("/api/v1/admin/users").status_code == 403
    assert staff.get("/api/v1/admin/audit").status_code == 403
    staff.close()


def test_short_password_is_rejected(client):
    response = client.post(
        "/api/v1/admin/users",
        json={"username": "weak", "password": "short", "role": "staff"},
        headers=csrf(client),
    )
    assert response.status_code == 422
