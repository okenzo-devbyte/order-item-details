import json

import pytest
from fastapi.testclient import TestClient

from api.main import create_app

from test_api_boot import make_settings


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as test_client:
        yield test_client


def test_index_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Order Search" in response.text


def test_manifest_is_valid_json(client):
    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200
    manifest = json.loads(response.text)
    assert manifest["name"]
    assert manifest["start_url"] == "/"


def test_service_worker_is_served(client):
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_service_worker_never_caches_api(client):
    text = client.get("/sw.js").text
    assert "/api/" not in text.split("const SHELL")[0]
    shell_line = [line for line in text.splitlines() if "const SHELL" in line][0]
    assert "api" not in shell_line


def test_styles_and_app_js_are_served(client):
    assert client.get("/styles.css").status_code == 200
    assert client.get("/app.js").status_code == 200
    assert client.get("/icons/icon.svg").status_code == 200
