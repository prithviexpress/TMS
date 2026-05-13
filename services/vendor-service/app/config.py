"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration is read from environment variables (or a .env file)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://tms:tms@localhost:5432/tms_vendor"

    # NATS
    NATS_URL: str = "nats://localhost:4222"

    # Downstream services
    SCHEDULE_SERVICE_URL: str = "http://localhost:8003"

    # JWT (shared secret for token validation)
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"

    # Service metadata
    SERVICE_NAME: str = "vendor-service"
    DEBUG: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
