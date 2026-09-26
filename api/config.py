from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-insecure-secret-change-me"
    data_key: str = ""
    data_key_id: str = "v1"
    admin_username: str = "admin"
    admin_password: str = "change-me-now"
    snapshot_path: str = "build/snapshot.enc"
    disk_path: str = ""
    cookie_secure: bool = False
    allowed_hosts: str = "*"
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 7
    idle_timeout_minutes: int = 30
    rate_limit_per_minute: int = 60
    max_upload_bytes: int = 20 * 1024 * 1024

    @property
    def persistent(self) -> bool:
        return bool(self.disk_path)

    @property
    def data_dir(self) -> Path:
        if self.disk_path:
            return Path(self.disk_path)
        return Path(tempfile.gettempdir()) / "order-search"

    @property
    def app_db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def versions_dir(self) -> Path:
        return self.data_dir / "versions"

    @property
    def snapshot_file(self) -> Path:
        return Path(self.snapshot_path)
