import pytest
from pydantic import ValidationError

from api.config import Settings


def test_defaults_are_dev_safe():
    fields = Settings.model_fields
    assert fields["cookie_secure"].default is False
    assert fields["access_ttl_minutes"].default == 15


def test_the_environment_wins_at_runtime_but_not_in_the_declared_default(monkeypatch):
    """The asymmetry that keeps a correct developer out of a red suite.

    `Settings()` resolves the process environment and `.env`, and
    `.env.example` ships `COOKIE_SECURE=true`, so a live instance reports True.
    The declared default belongs to the model and cannot be moved by the
    environment, which is why every default assertion reads it from there.
    """
    monkeypatch.setenv("COOKIE_SECURE", "true")
    assert Settings().cookie_secure is True
    assert Settings.model_fields["cookie_secure"].default is False


def test_schema_defaults():
    fields = Settings.model_fields
    assert fields["schema_item"].default == "item"
    assert fields["schema_sales"].default == "sales"
    assert fields["schema_app"].default == "app"


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
    """A tombstone for the snapshot port, not a permanent design rule.

    Nothing may read these settings while the port is in flight. The modules that
    used them are deleted by the final task of the Postgres plan, and this test
    should be deleted along with them rather than outliving them.
    """
    fields = Settings.model_fields
    for name in ("data_key", "data_key_id", "snapshot_path", "disk_path"):
        assert name not in fields
    for name in ("persistent", "data_dir", "app_db_path", "versions_dir", "snapshot_file"):
        assert not hasattr(Settings, name)


def test_a_settings_round_trip_preserves_the_schema_names(monkeypatch):
    monkeypatch.setenv("DB_SCHEMA_ITEM", "t_item")
    monkeypatch.setenv("DB_SCHEMA_SALES", "t_sales")
    monkeypatch.setenv("DB_SCHEMA_APP", "t_app")
    original = Settings()
    for name in ("DB_SCHEMA_ITEM", "DB_SCHEMA_SALES", "DB_SCHEMA_APP"):
        monkeypatch.delenv(name)
    copied = Settings(**original.model_dump())
    assert copied.schema_item == "t_item"
    assert copied.schema_sales == "t_sales"
    assert copied.schema_app == "t_app"


def test_the_field_name_also_works():
    assert Settings(schema_item="custom").schema_item == "custom"


def test_the_bare_schema_env_var_still_works(monkeypatch):
    monkeypatch.setenv("SCHEMA_ITEM", "legacy")
    assert Settings().schema_item == "legacy"


def test_the_prefixed_schema_env_var_wins(monkeypatch):
    monkeypatch.setenv("SCHEMA_ITEM", "legacy")
    monkeypatch.setenv("DB_SCHEMA_ITEM", "prefixed")
    assert Settings().schema_item == "prefixed"


@pytest.mark.parametrize("field", ["schema_item", "schema_sales", "schema_app"])
def test_a_malformed_schema_name_is_rejected(field):
    with pytest.raises(ValidationError):
        Settings(**{field: 'x"; DROP TABLE item; --'})


def test_a_well_formed_schema_name_is_accepted():
    assert Settings(schema_item="_t1").schema_item == "_t1"
    assert Settings(schema_item="t_item_2").schema_item == "t_item_2"
