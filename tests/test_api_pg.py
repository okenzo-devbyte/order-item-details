import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from order_search.ingest.excel_reader import read_order_rows
from order_search.ingest.load import load_into_version
from conftest import DATA_FILE


@pytest.fixture
def api(client_db, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "false")
    load_into_version(client_db, read_order_rows(DATA_FILE), 1)
    with TestClient(create_app(client_db)) as client:
        yield client


def login(client):
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "change-me-now"}
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_healthz_reports_a_loaded_database(api):
    body = api.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["products"] == 15


def test_login_then_search_finds_the_customer(api):
    headers = login(api)
    body = api.post("/api/v1/search", json={"q": "สุรชัย"}, headers=headers).json()
    assert body["mode"] == "customer"
    assert len(body["customers"]) == 1


def test_a_search_without_a_session_is_rejected(api):
    assert api.post("/api/v1/search", json={"q": "สุรชัย"}).status_code == 401


def test_the_audit_log_records_a_search(api):
    headers = login(api)
    api.post("/api/v1/search", json={"q": "สุรชัย"}, headers=headers)
    entries = api.get("/api/v1/admin/audit?action=search").json()["entries"]
    assert entries
    assert entries[0]["query"] == "สุรชัย"


def test_create_app_injects_the_database_by_keyword(client_db):
    app = create_app(database=client_db)
    assert app.state.db is client_db
