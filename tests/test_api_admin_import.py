import pytest
from fastapi.testclient import TestClient

from api.main import create_app

from conftest import DATA_FILE
from test_api_boot import make_settings


def make_alt_workbook(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Order Data"
    sheet.append([
        "Store Code", "Order Type", "Product Name", "NO.", "Dept", "Class",
        "Subclass", "Bar_Code", "Customer Name", "Item Remark",
        "VIP Customer Remarks", "VIP Customer Groups",
        "Original Expected Date",
    ])
    for number in range(1, 4):
        sheet.append([
            "101", "Pickup", "สินค้าทดสอบALT", number, 1, 100, 1000,
            "999888777", "ลูกค้าทดสอบALT", None, None, None, "26-Sep-2026",
        ])
    path = tmp_path / "alt.xlsx"
    workbook.save(path)
    return path


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


def test_rollback_restores_previous_snapshot(client, tmp_path):
    alt = make_alt_workbook(tmp_path)
    with open(alt, "rb") as handle:
        imported = client.post(
            "/api/v1/admin/import",
            files={"file": ("alt.xlsx", handle, "application/octet-stream")},
            headers=csrf(client),
        )
    assert imported.status_code == 200
    assert client.post("/api/v1/search", json={"q": "ALT"}).json()["products"]
    assert not client.post(
        "/api/v1/search", json={"q": "น้ำดื่มสิงห์"}
    ).json()["products"]

    versions = client.get("/api/v1/admin/import/versions").json()["versions"]
    baseline = [v for v in versions if v["created_by"] is None][0]
    rolled_back = client.post(
        "/api/v1/admin/import/rollback",
        json={"version_id": baseline["id"]},
        headers=csrf(client),
    )
    assert rolled_back.status_code == 200
    assert client.post(
        "/api/v1/search", json={"q": "น้ำดื่มสิงห์"}
    ).json()["products"]


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


def test_persistent_disk_reloads_current_version_on_boot(tmp_path):
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as first:
        first.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me-now"},
        )
        alt = make_alt_workbook(tmp_path)
        with open(alt, "rb") as handle:
            first.post(
                "/api/v1/admin/import",
                files={"file": ("alt.xlsx", handle, "application/octet-stream")},
                headers={"X-CSRF-Token": first.cookies["csrf_token"]},
            )
        assert first.post("/api/v1/search", json={"q": "ALT"}).json()["products"]

    with TestClient(create_app(make_settings(tmp_path))) as second:
        second.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me-now"},
        )
        assert second.post(
            "/api/v1/search", json={"q": "ALT"}
        ).json()["products"]
