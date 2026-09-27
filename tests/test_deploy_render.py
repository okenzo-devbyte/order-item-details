import json
import os
import subprocess
from pathlib import Path

from scripts.deploy_render import build_patch, build_payload

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def test_payload_deploys_a_prebuilt_image():
    payload = build_payload(
        "order-search", "own-1", "docker.io/me/order-search:latest", "free",
        "/healthz", {"DATA_KEY": KEY, "COOKIE_SECURE": "true"},
    )
    assert payload["type"] == "web_service"
    assert payload["image"] == {
        "imagePath": "docker.io/me/order-search:latest",
        "ownerId": "own-1",
    }
    details = payload["serviceDetails"]
    assert details["runtime"] == "image"
    assert details["plan"] == "free"
    assert details["healthCheckPath"] == "/healthz"
    assert {"key": "COOKIE_SECURE", "value": "true"} in details["env"]


def test_patch_keeps_only_image_and_details():
    payload = build_payload("n", "o", "docker.io/me/x:1", "free", "/healthz", {})
    assert build_patch(payload) == {
        "image": payload["image"],
        "serviceDetails": payload["serviceDetails"],
    }


def test_private_image_carries_a_registry_credential():
    payload = build_payload(
        "order-search", "own-1", "docker.io/me/order-search:latest", "free",
        "/healthz", {}, "cred-9",
    )
    assert payload["image"] == {
        "imagePath": "docker.io/me/order-search:latest",
        "ownerId": "own-1",
        "registryCredentialId": "cred-9",
    }


def test_half_a_registry_credential_is_refused():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("RENDER_API_KEY", None)
    env["DATA_KEY"] = KEY
    env["ADMIN_PASSWORD"] = "a-long-admin-password"
    env["REGISTRY_USERNAME"] = "ohkenzo"
    env.pop("REGISTRY_TOKEN", None)
    result = subprocess.run(
        [
            str(PYTHON),
            str(ROOT / "scripts" / "deploy_render.py"),
            "--image",
            "docker.io/ohkenzo/order-search:latest",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
    )
    assert result.returncode == 2
    assert "registry-token" in result.stderr


def test_dry_run_emits_valid_json_without_a_key(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("RENDER_API_KEY", None)
    env["DATA_KEY"] = KEY
    env["ADMIN_PASSWORD"] = "a-long-admin-password"
    result = subprocess.run(
        [
            str(PYTHON),
            str(ROOT / "scripts" / "deploy_render.py"),
            "--image",
            "docker.io/me/order-search:latest",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    names = {item["key"] for item in payload["serviceDetails"]["env"]}
    assert {"DATA_KEY", "ADMIN_PASSWORD", "SECRET_KEY", "COOKIE_SECURE"} <= names


def test_refuses_to_run_without_a_data_key(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("DATA_KEY", None)
    env.pop("ADMIN_PASSWORD", None)
    result = subprocess.run(
        [
            str(PYTHON),
            str(ROOT / "scripts" / "deploy_render.py"),
            "--image",
            "docker.io/me/order-search:latest",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
    )
    assert result.returncode == 2
    assert "DATA_KEY" in result.stderr
