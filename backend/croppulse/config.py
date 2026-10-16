"""Validated application configuration.

All settings come from environment variables (prefix ``CROPPULSE_``) or a ``.env``
file. Scientific thresholds live in ``config/science.yaml`` so that they are
versioned alongside the code and can be reviewed independently.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CROPPULSE_",
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = f"sqlite:///{REPO_ROOT / 'data' / 'croppulse.db'}"
    secret_key: str = Field(default="", description="HMAC key for access tokens")
    token_ttl_minutes: int = 12 * 60
    password_hash_iterations: int = 600_000

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3100", "http://127.0.0.1:3100"]

    data_dir: Path = REPO_ROOT / "data"
    upload_dir: Path = REPO_ROOT / "data" / "uploads"
    science_config_path: Path = REPO_ROOT / "config" / "science.yaml"
    alert_rules_path: Path = REPO_ROOT / "config" / "alert_rules.yaml"
    guidance_path: Path = REPO_ROOT / "config" / "guidance.yaml"
    sources_path: Path = REPO_ROOT / "config" / "sources.yaml"
    crop_calendar_path: Path = REPO_ROOT / "config" / "crop_calendar.yaml"

    # External sources. Empty means "not configured" — never silently faked.
    enable_live_sources: bool = True
    earthdata_token: str = ""
    http_timeout_seconds: float = 60.0
    http_max_retries: int = 3

    # Notification providers
    notification_email_provider: Literal["dev_outbox", "none"] = "dev_outbox"

    # Feature flags (deferred / unvalidated capabilities stay off)
    feature_yield_prediction: bool = False
    feature_market_prices: bool = False

    max_upload_bytes: int = 5 * 1024 * 1024
    login_rate_limit_per_minute: int = 10
    log_level: str = "INFO"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _check_secret(self) -> Settings:
        if self.environment == "production":
            if len(self.secret_key) < 32:
                raise ValueError(
                    "CROPPULSE_SECRET_KEY must be set to at least 32 characters in production. "
                    "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
                )
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is for development/tests only; set CROPPULSE_DATABASE_URL to PostgreSQL.")
        elif not self.secret_key:
            # Development convenience: a per-checkout key derived from the path. Never used in production.
            self.secret_key = hashlib.sha256(f"dev-only:{REPO_ROOT}".encode()).hexdigest()
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def load_yaml(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file {path} must contain a mapping")
    return data


def science_config() -> dict[str, Any]:
    return load_yaml(str(get_settings().science_config_path))


def config_version(path: Path) -> str:
    """Short content hash used to version configuration in assessments."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
