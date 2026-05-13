"""Bay-service configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://tms:tms@localhost:5432/tms_bay"

    # NATS
    NATS_URL: str = "nats://localhost:4222"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # display-service base URL (for K70 light control)
    DISPLAY_SERVICE_URL: str = "http://display-service:8006"

    # LoRaWAN webhook security — validated in sensor ingest route
    LORAWAN_INGEST_API_KEY: str = "changeme"

    # JWT secret shared across all TMS services
    JWT_SECRET: str = "changeme"

    # Occupancy detection threshold for Milesight EM400-MUD
    # Distance (mm) below which the bay is considered OCCUPIED
    OCCUPANCY_DISTANCE_THRESHOLD_MM: int = 500


settings = Settings()
