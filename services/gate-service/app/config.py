"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration is read from environment variables (or a .env file)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql://tms:tms@localhost:5432/tms_gate"

    # NATS
    NATS_URL: str = "nats://localhost:4222"

    # Downstream services
    SCHEDULE_SERVICE_URL: str = "http://localhost:8003"

    # MinIO / S3-compatible object store
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_ALPR: str = "alpr-images"

    # JWT (shared secret used to verify inbound tokens if needed)
    JWT_SECRET: str = "change-me-in-production"

    # Service metadata
    SERVICE_NAME: str = "gate-service"
    DEBUG: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
