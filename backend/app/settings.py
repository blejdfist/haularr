"""Application settings using Pydantic BaseSettings."""

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HAULARR_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Paths
    config_dir: Path = Field(default=Path("/config"))
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_file_max_mb: int = 10  # <config_dir>/logs/haularr.log rotates at this size
    log_file_backups: int = 5  # rotated files kept (haularr.log.1 ... .N)

    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    secret_key: str | None = None  # empty: generated at startup unless specified
    access_token_expire_minutes: int = 1440  # 24h

    # Database
    @property
    def database_url(self) -> str:
        db_path = self.config_dir / "haularr.db"
        return f"sqlite+aiosqlite:///{db_path}"

    @property
    def sync_database_url(self) -> str:
        db_path = self.config_dir / "haularr.db"
        return f"sqlite:///{db_path}"

    # Scheduler / concurrency defaults
    max_concurrent_download_jobs: int = 3
    max_concurrent_verify_jobs: int = 2
    max_concurrent_extract_jobs: int = 1
    max_concurrent_publish_jobs: int = 1
    max_concurrent_import_jobs: int = 2
    completed_history_days: int = 14
    discovery_interval_seconds: int = 30
    retry_limit: int = 5
    stage_lease_seconds: int = 90

    # Demo mode: fake sources/libraries/jobs, no real background services (see app/demo.py)
    demo: bool = False

    # Static frontend
    static_dir: Path = Field(default=Path("frontend/build"))

    @field_validator("config_dir", mode="before")
    @classmethod
    def expand_config_dir(cls, v: str | Path) -> Path:
        return Path(os.path.expandvars(str(v))).expanduser()


def get_settings() -> Settings:
    return Settings()
