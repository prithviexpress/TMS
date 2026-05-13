"""Application configuration via pydantic-settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://tms:password@localhost:5432/tms_schedule"

    # ── NATS ──────────────────────────────────────────────────────────
    NATS_URL: str = "nats://localhost:4222"

    # ── MinIO / Object Storage ────────────────────────────────────────
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "tmsadmin"
    MINIO_SECRET_KEY: str = "changeme_minio"
    MINIO_BUCKET_NAGARE: str = "nagare-uploads"

    # ── Auth ──────────────────────────────────────────────────────────
    JWT_SECRET: str = "change-this-to-a-256-bit-random-hex-secret"

    # ── Tolerances for gate check (minutes) ──────────────────────────
    GATE_CHECK_EARLY_MINUTES: int = 30
    GATE_CHECK_LATE_MINUTES: int = 60


settings = Settings()
