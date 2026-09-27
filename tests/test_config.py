from api.config import Settings


def test_defaults_are_dev_safe():
    settings = Settings()
    assert settings.cookie_secure is False
    assert settings.access_ttl_minutes == 15
    assert settings.schema_item == "item"
    assert settings.schema_sales == "sales"
    assert settings.schema_app == "app"


def test_env_overrides_field(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "7")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    settings = Settings()
    assert settings.rate_limit_per_minute == 7
    assert settings.cookie_secure is True


def test_database_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@pooler:6543/postgres")
    monkeypatch.setenv("DB_SCHEMA_ITEM", "t_item")
    monkeypatch.setenv("DB_SCHEMA_SALES", "t_sales")
    monkeypatch.setenv("DB_SCHEMA_APP", "t_app")
    settings = Settings()
    assert settings.database_url.startswith("postgresql://")
    assert settings.schema_item == "t_item"
    assert settings.schema_sales == "t_sales"
    assert settings.schema_app == "t_app"


def test_snapshot_settings_are_gone():
    fields = Settings.model_fields
    assert "data_key" not in fields
    assert "snapshot_path" not in fields
    assert "disk_path" not in fields
