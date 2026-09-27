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


def test_search_by_customer(client):
    response = client.post("/api/v1/search", json={"q": "สุรชัย"})
    assert response.status_code == 200
    body = response.json()
    assert body["detected"] == "customer"
    assert body["customers"][0]["name"] == "สุรชัย"


def test_search_by_barcode(client):
    response = client.post("/api/v1/search", json={"q": "8850250001234"})
    products = response.json()["products"]
    assert products and products[0]["name"].startswith("น้ำดื่มสิงห์")


def test_search_with_typo(client):
    response = client.post("/api/v1/search", json={"q": "สิงห"})
    assert response.json()["products"]


def test_short_thai_query_returns_four_products(client):
    response = client.post("/api/v1/search", json={"q": "น้ำ"})
    assert len(response.json()["products"]) == 4


def test_pii_never_appears_in_the_url(client):
    response = client.post("/api/v1/search", json={"q": "สุรชัย"})
    assert response.request.method == "POST"
    assert not response.request.url.query
    assert "สุรชัย" not in str(response.request.url)


def test_search_requires_login(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as anonymous:
        assert anonymous.post("/api/v1/search", json={"q": "น้ำ"}).status_code == 401


def test_suggest_returns_products(client):
    response = client.post("/api/v1/suggest", json={"q": "น้ำ", "limit": 10})
    assert len(response.json()["suggestions"]) == 4


def test_query_length_is_capped(client):
    response = client.post("/api/v1/search", json={"q": "ก" * 201})
    assert response.status_code == 422


def test_filters_endpoint(client):
    response = client.get("/api/v1/filters")
    body = response.json()
    assert len(body["store_code"]) == 15
    assert "Standard delivery" in body["order_type"]


def test_search_with_store_filter(client):
    response = client.post(
        "/api/v1/search",
        json={"q": "น้ำ", "filters": {"store_code": ["101"]}},
    )
    assert response.json()["products"]


def test_search_is_rate_limited(tmp_path):
    from api.config import Settings

    settings = make_settings(tmp_path)
    limited = Settings(**{**settings.model_dump(), "rate_limit_per_minute": 2})
    with TestClient(create_app(limited)) as app_client:
        app_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me-now"},
        )
        assert app_client.post("/api/v1/search", json={"q": "น้ำ"}).status_code == 200
        assert app_client.post("/api/v1/search", json={"q": "น้ำ"}).status_code == 200
        assert app_client.post("/api/v1/search", json={"q": "น้ำ"}).status_code == 429


def test_search_bad_date_is_422(client):
    response = client.post(
        "/api/v1/search",
        json={"q": "น้ำ", "filters": {"date_from": "26-Sep-2026"}},
    )
    assert response.status_code == 422


def test_customer_history_endpoint(client):
    response = client.get("/api/v1/customers/1/history")
    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"] == 1
    assert body["products"]


def test_customer_history_bad_date_is_422(client):
    response = client.get(
        "/api/v1/customers/1/history", params={"date_from": "26-Sep-2026"}
    )
    assert response.status_code == 422


def test_customer_history_unknown_id_is_404(client):
    assert client.get("/api/v1/customers/99999/history").status_code == 404


def test_product_customers_endpoint(client):
    response = client.get("/api/v1/products/1/customers")
    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == 1
    assert body["customers"]


def test_product_customers_unknown_id_is_404(client):
    assert client.get("/api/v1/products/99999/customers").status_code == 404


def test_suggest_is_audited(client):
    client.post("/api/v1/suggest", json={"q": "น้ำ"})
    entries = client.get(
        "/api/v1/admin/audit", params={"action": "suggest"}
    ).json()["entries"]
    assert entries
