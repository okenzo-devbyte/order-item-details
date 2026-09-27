import re
import sys
from pathlib import Path

import pytest
from pydantic import AliasChoices, ValidationError

from api.config import Settings

ROOT = Path(__file__).resolve().parents[1]

LOCAL_PACKAGES = {"api", "conftest", "order_search", "scripts", "test_api_boot"}

IMPORT_TO_DISTRIBUTION = {
    "argon2": "argon2-cffi",
    "jwt": "pyjwt",
    "pydantic_settings": "pydantic-settings",
    "starlette": "fastapi",
}

IMPORT_LINE = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)")


def _declared_distributions() -> set[str]:
    names = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(
                re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].lower().replace("_", "-")
            )
    return names


def _imported_top_level_names() -> dict[str, set[str]]:
    imported: dict[str, set[str]] = {}
    for folder in ("api", "src", "scripts", "tests"):
        for path in (ROOT / folder).rglob("*.py"):
            names = set()
            for line in path.read_text(encoding="utf-8").splitlines():
                match = IMPORT_LINE.match(line)
                if match:
                    names.add(match.group(1))
            imported[path.relative_to(ROOT).as_posix()] = names
    return imported


def test_every_imported_third_party_package_is_declared():
    """A declared dependency must outlive the code that imports it.

    Removing a line from requirements.txt while its importer still exists breaks
    a clean build, not the local venv, because the package stays installed there.
    """
    declared = _declared_distributions()
    missing = set()
    for path, names in _imported_top_level_names().items():
        for name in names - LOCAL_PACKAGES - set(sys.stdlib_module_names):
            distribution = IMPORT_TO_DISTRIBUTION.get(name, name)
            if distribution not in declared:
                missing.add(f"{distribution} (imported by {path})")
    assert not missing, f"undeclared imports: {sorted(missing)}"


def _env_names_for(field_name: str, field) -> set[str]:
    alias = field.validation_alias
    if alias is None:
        return {field_name.upper()}
    if isinstance(alias, AliasChoices):
        return {choice.upper() for choice in alias.choices if isinstance(choice, str)}
    return {str(alias).upper()}


ENV_ASSIGNMENT = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)\s*=")


def _documented_env_names(text: str) -> set[str]:
    """Every variable name written down, commented out or not.

    A commented `NAME=` still documents the variable. It just refuses to hand a
    blank value to whoever copies the file, which is what an active `NAME=` does.
    """
    names = set()
    for line in text.splitlines():
        match = ENV_ASSIGNMENT.match(line.strip())
        if match:
            names.add(match.group(1))
    return names


def test_env_example_documents_every_setting():
    """A setting nobody wrote down is a setting nobody can set correctly.

    The three schema names are the reason this matters: their env var names are
    `DB_SCHEMA_*` while the field names are `schema_*`, so nothing about the field
    declaration hints at the name an operator has to use.
    """
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    documented = _documented_env_names(text)
    missing = set()
    for field_name, field in Settings.model_fields.items():
        missing |= _env_names_for(field_name, field) - documented
    assert not missing, f"undocumented in .env.example: {sorted(missing)}"

    blank = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, _, value = stripped.partition("=")
        if not value.strip():
            blank.append(name.strip())
    assert not blank, f"active but empty, comment these out instead: {sorted(blank)}"


def test_env_example_holds_no_credential():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        _, _, value = line.partition("=")
        if "://" in value:
            assert "PASSWORD" in value.upper() or "@" not in value, (
                f"possible real credential: {line}"
            )


def test_defaults_are_dev_safe():
    settings = Settings()
    assert settings.cookie_secure is False
    assert settings.access_ttl_minutes == 15


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
