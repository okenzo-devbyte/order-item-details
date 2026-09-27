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
    shell_block = text.split("const SHELL = [", 1)[1].split("]", 1)[0]
    entries = [
        line.strip().strip(",").strip('"')
        for line in shell_block.splitlines()
        if line.strip()
    ]
    assert entries
    assert not any(entry.startswith("/api") for entry in entries)
    assert 'url.pathname.startsWith("/api/")' in text


def test_api_has_content_security_policy(client):
    response = client.get("/healthz")
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_app_js_escapes_server_values(client):
    text = client.get("/app.js").text
    assert "function escapeHtml" in text
    assert "escapeHtml(customer.name)" in text
    assert "escapeHtml(product.name)" in text


def test_styles_and_app_js_are_served(client):
    assert client.get("/styles.css").status_code == 200
    assert client.get("/app.js").status_code == 200
    assert client.get("/icons/icon.svg").status_code == 200
