from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://tms:tms@localhost:5432/tms_notifications"
    NATS_URL: str = "nats://localhost:4222"
    MSG91_AUTH_KEY: str = ""
    MSG91_SENDER_ID: str = "MSILTM"
    WHATSAPP_API_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    JWT_SECRET: str = "dev-secret"
    JWT_ALGORITHM: str = "HS256"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
