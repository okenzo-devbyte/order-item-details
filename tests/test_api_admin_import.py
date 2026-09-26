import pytest
from fastapi.testclient import TestClient

from api.main import create_app

from conftest import DATA_FILE
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


def upload(client):
    with open(DATA_FILE, "rb") as handle:
        return client.post(
            "/api/v1/admin/import",
            files={
                "file": (
                    "orders.xlsx",
                    handle,
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet",
                )
            },
            headers=csrf(client),
        )


def test_import_creates_a_version(client):
    response = upload(client)
    assert response.status_code == 200
    body = response.json()
    assert body["report"]["products"] == 15
    assert body["report"]["customers"] == 20
    assert body["persistent"] is True


def test_search_still_works_after_import(client):
    upload(client)
    response = client.post("/api/v1/search", json={"q": "สุรชัย"})
    assert response.json()["customers"][0]["name"] == "สุรชัย"


def test_versions_endpoint_lists_versions(client):
    upload(client)
    response = client.get("/api/v1/admin/import/versions")
    assert response.status_code == 200
    body = response.json()
    assert body["persistent"] is True
    assert len(body["versions"]) >= 1


def test_rollback_restores_previous_snapshot(client):
    upload(client)
    versions = client.get("/api/v1/admin/import/versions").json()["versions"]
    target = versions[0]["id"]
    response = client.post(
        "/api/v1/admin/import/rollback",
        json={"version_id": target},
        headers=csrf(client),
    )
    assert response.status_code == 200
    assert client.post("/api/v1/search", json={"q": "น้ำ"}).status_code == 200


def test_rejects_non_xlsx(client):
    response = client.post(
        "/api/v1/admin/import",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=csrf(client),
    )
    assert response.status_code == 422


def test_rollback_unknown_version_is_404(client):
    response = client.post(
        "/api/v1/admin/import/rollback",
        json={"version_id": 99999},
        headers=csrf(client),
    )
    assert response.status_code == 404


def test_baseline_version_is_seeded(client):
    body = client.get("/api/v1/admin/import/versions").json()
    assert len(body["versions"]) >= 1
    assert any(version["created_by"] is None for version in body["versions"])


def test_corrupt_xlsx_is_422(client):
    response = client.post(
        "/api/v1/admin/import",
        files={"file": ("broken.xlsx", b"not a real workbook", "application/octet-stream")},
        headers=csrf(client),
    )
    assert response.status_code == 422


def test_zip_without_workbook_is_422(client):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")
    response = client.post(
        "/api/v1/admin/import",
        files={
            "file": (
                "fake.xlsx",
                buffer.getvalue(),
                "application/octet-stream",
            )
        },
        headers=csrf(client),
    )
    assert response.status_code == 422
