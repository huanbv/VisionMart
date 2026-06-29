"""Centralised application settings (Pydantic v2)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---- App ----
    APP_NAME: str = "VisionMart"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_DEBUG: bool = True
    APP_TIMEZONE: str = "UTC"

    # ---- Logging ----
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "text"] = "json"

    # ---- HTTP ----
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    BACKEND_API_PREFIX: str = "/api/v1"
    BACKEND_CORS_ORIGINS: str = "http://localhost:3000"
    BACKEND_SECRET_KEY: str = Field("change-me", min_length=8)

    # ---- Database ----
    DATABASE_URL: str = (
        "postgresql+asyncpg://visionmart:visionmart@postgres:5432/visionmart"
    )

    # ---- Redis / Celery ----
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"

    # ---- AI Engine ----
    AI_ENGINE_BASE_URL: str = "http://ai-engine:8100"

    # ---- MinIO ----
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ROOT_USER: str = "visionmart"
    MINIO_ROOT_PASSWORD: str = "visionmart-minio"
    MINIO_BUCKET: str = "visionmart"
    MINIO_USE_SSL: bool = False

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.BACKEND_CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
