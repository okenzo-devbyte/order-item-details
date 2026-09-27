from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_app_path_is_importable_inside_the_image():
    assert "PYTHONPATH=/app/src" in DOCKERFILE


def test_uvicorn_listens_on_the_platform_port():
    assert "--port ${PORT:-8000}" in DOCKERFILE
    assert "EXPOSE 7860" in DOCKERFILE


def test_uvicorn_trusts_the_platform_proxy():
    assert "--proxy-headers" in DOCKERFILE
    assert "--forwarded-allow-ips" in DOCKERFILE


def test_container_never_runs_as_root():
    assert "USER app" in DOCKERFILE
    assert DOCKERFILE.index("USER app") < DOCKERFILE.index("CMD")


def test_image_carries_the_sealed_snapshot_only():
    assert "COPY snapshot.enc data/snapshot.enc" in DOCKERFILE
    assert "sample_order_data" not in DOCKERFILE


def test_readme_declares_the_space_metadata():
    assert README.startswith("---\n")
    assert "sdk: docker" in README
    assert "app_port: 7860" in README
