from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    max_upload_bytes: int = 20 * 1024 * 1024
    database_url: str = ""
    schema_item: str = Field(default="item", validation_alias="DB_SCHEMA_ITEM")
    schema_sales: str = Field(default="sales", validation_alias="DB_SCHEMA_SALES")
    schema_app: str = Field(default="app", validation_alias="DB_SCHEMA_APP")
