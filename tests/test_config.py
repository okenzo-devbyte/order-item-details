from api.config import Settings


def test_defaults_are_dev_safe():
    settings = Settings()
    assert settings.cookie_secure is False
    assert settings.persistent is False
    assert settings.access_ttl_minutes == 15


def test_disk_path_makes_it_persistent(tmp_path):
    settings = Settings(disk_path=str(tmp_path))
    assert settings.persistent is True
    assert settings.data_dir == tmp_path
    assert settings.app_db_path == tmp_path / "app.db"
    assert settings.versions_dir == tmp_path / "versions"


def test_without_disk_path_it_uses_temp_dir():
    settings = Settings(disk_path="")
    assert settings.persistent is False
    assert settings.app_db_path.parent == settings.data_dir


def test_env_overrides_field(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "7")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    settings = Settings()
    assert settings.rate_limit_per_minute == 7
    assert settings.cookie_secure is True
