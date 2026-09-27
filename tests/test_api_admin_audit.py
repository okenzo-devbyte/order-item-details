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


def test_audit_records_searches(client):
    client.post("/api/v1/search", json={"q": "สุรชัย"})
    response = client.get("/api/v1/admin/audit")
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert any(entry["action"] == "search" for entry in entries)


def test_audit_filter_by_action(client):
    client.post("/api/v1/search", json={"q": "น้ำ"})
    response = client.get("/api/v1/admin/audit", params={"action": "search"})
    assert all(entry["action"] == "search" for entry in response.json()["entries"])


def test_audit_pagination(client):
    for query in ("น้ำ", "สุรชัย", "กาแฟ"):
        client.post("/api/v1/search", json={"q": query})
    first = client.get("/api/v1/admin/audit", params={"limit": 1}).json()
    assert len(first["entries"]) == 1
    older = client.get(
        "/api/v1/admin/audit",
        params={"limit": 10, "before_id": first["entries"][0]["id"]},
    ).json()
    assert older["entries"]
    assert all(
        entry["id"] < first["entries"][0]["id"] for entry in older["entries"]
    )


def test_login_failure_is_audited(tmp_path):
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as anonymous:
        anonymous.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        anonymous.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me-now"},
        )
        entries = anonymous.get("/api/v1/admin/audit").json()["entries"]
    assert any(entry["action"] == "login_failed" for entry in entries)
