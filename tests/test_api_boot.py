import base64
import sqlite3

from fastapi.testclient import TestClient

from api.config import Settings
from api.crypto import seal
from api.main import create_app
from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows

from conftest import DATA_FILE

RAW_KEY = bytes(range(32))
KEY_ID = "v1"


def make_settings(tmp_path) -> Settings:
    snapshot = tmp_path / "snapshot.enc"
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(DATA_FILE), connection)
    snapshot.write_bytes(seal(connection.serialize(), RAW_KEY, KEY_ID))
    connection.close()
    return Settings(
        secret_key="test-secret",
        data_key=base64.urlsafe_b64encode(RAW_KEY).decode("ascii"),
        data_key_id=KEY_ID,
        snapshot_path=str(snapshot),
        disk_path=str(tmp_path / "data"),
        admin_username="admin",
        admin_password="change-me-now",
    )


def test_healthz_is_ok(tmp_path):
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["snapshot"] is True


def test_security_headers_are_present(tmp_path):
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_api_responses_are_no_store(tmp_path):
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login", json={"username": "x", "password": "y"}
        )
    assert response.headers["cache-control"] == "no-store"
