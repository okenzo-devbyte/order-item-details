import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.main import create_app

from test_api_boot import make_settings


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as test_client:
        yield test_client


def login(client, username="admin", password="change-me-now"):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


def test_login_sets_cookies_and_returns_user(client):
    response = login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "admin"
    assert body["role"] == "admin"
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies
    assert "csrf_token" in response.cookies


def test_login_rejects_bad_password(client):
    assert login(client, password="wrong").status_code == 401


def test_me_requires_login(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_current_user(client):
    login(client)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_logout_clears_session(client):
    login(client)
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_refresh_keeps_session_alive(client):
    login(client)
    assert client.post("/api/v1/auth/refresh").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_refresh_without_cookie_is_401(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as fresh:
        assert fresh.post("/api/v1/auth/refresh").status_code == 401


def test_login_is_rate_limited(tmp_path):
    settings = make_settings(tmp_path)
    limited = Settings(**{**settings.model_dump(), "rate_limit_per_minute": 2})
    with TestClient(create_app(limited)) as app_client:
        assert login(app_client, password="wrong").status_code == 401
        assert login(app_client, password="wrong").status_code == 401
        assert login(app_client, password="wrong").status_code == 429
