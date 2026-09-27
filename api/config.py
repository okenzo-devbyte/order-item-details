from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SQL_IDENTIFIER = r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )

    secret_key: str = "dev-insecure-secret-change-me"
    admin_username: str = "admin"
    admin_password: str = "change-me-now"
    cookie_secure: bool = False
    allowed_hosts: str = "*"
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 7
    idle_timeout_minutes: int = 30
    rate_limit_per_minute: int = 60
    database_url: str = ""
    # Env var names differ from field names (DB_SCHEMA_*); both are accepted.
    # These three are interpolated into SQL identifiers, so they are restricted to
    # what a bare Postgres identifier can be.
    schema_item: str = Field(
        default="item",
        validation_alias=AliasChoices("DB_SCHEMA_ITEM", "SCHEMA_ITEM"),
        pattern=SQL_IDENTIFIER,
    )
    schema_sales: str = Field(
        default="sales",
        validation_alias=AliasChoices("DB_SCHEMA_SALES", "SCHEMA_SALES"),
        pattern=SQL_IDENTIFIER,
    )
    schema_app: str = Field(
        default="app",
        validation_alias=AliasChoices("DB_SCHEMA_APP", "SCHEMA_APP"),
        pattern=SQL_IDENTIFIER,
    )
