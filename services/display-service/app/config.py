"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration is read from environment variables (or a .env file)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql://tms:tms@localhost:5432/tms_display"

    # NATS
    NATS_URL: str = "nats://localhost:4222"

    # Hardware endpoints
    K70_GATEWAY_IP: str = "192.168.10.50"
    LED_DISPLAY_GATE2_IP: str = "192.168.10.51"
    LED_DISPLAY_PARKING_EXIT_IP: str = "192.168.10.52"

    # JWT
    JWT_SECRET: str = "change-me-in-production"

    # Service metadata
    SERVICE_NAME: str = "display-service"
    DEBUG: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
