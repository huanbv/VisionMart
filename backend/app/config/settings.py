"""Centralised application settings (Pydantic v2)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRETS: frozenset[str] = frozenset(
    {"change-me", "change-me-please-generate-a-strong-secret", "secret", ""}
)


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

    # ---- Auth ----
    JWT_PRIVATE_KEY_PATH: str = "/run/secrets/jwt_private.pem"
    JWT_PUBLIC_KEY_PATH: str = "/run/secrets/jwt_public.pem"
    JWT_ALGORITHM: str = "RS256"
    JWT_ISSUER: str = "visionmart"
    JWT_AUDIENCE: str = "visionmart-api"
    ACCESS_TOKEN_TTL_SECONDS: int = 900            # 15 minutes
    REFRESH_TOKEN_TTL_SECONDS: int = 1209600       # 14 days
    SEED_ADMIN_EMAIL: str = "admin@visionmart.local"
    SEED_ADMIN_USERNAME: str = "admin"
    SEED_ADMIN_PASSWORD: str = "ChangeMe!2026"
    SEED_ORGANIZATION_NAME: str = "VisionMart Demo"
    SEED_ORGANIZATION_SLUG: str = "demo"

    # ---- Database ----
    DATABASE_URL: str = (
        "postgresql+asyncpg://visionmart:visionmart@postgres:5432/visionmart"
    )

    # ---- Redis / Celery ----
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"

    # ---- Alerts ----
    ALERT_SCAN_INTERVAL_SECONDS: int = 300
    ALERT_DEDUP_HOURS: int = 6
    CAMERA_OFFLINE_THRESHOLD_SECONDS: int = 300

    # ---- AI Engine ----
    AI_ENGINE_BASE_URL: str = "http://ai-engine:8100"

    # ---- Detection alerts ----
    DETECTION_ALERT_MIN_CONFIDENCE: float = 0.7
    DETECTION_ALERT_CLASSES: str = "person"
    DETECTION_ALERT_DEDUP_SECONDS: int = 60

    # ---- RTSP auto-capture ----
    RTSP_CAPTURE_ENABLED: bool = False
    RTSP_CAPTURE_INTERVAL_SECONDS: int = 60
    RTSP_CAPTURE_MAX_CAMERAS: int = 20
    RTSP_CAPTURE_OPEN_TIMEOUT_MS: int = 5000

    # ---- Detection retention ----
    DETECTION_CLEANUP_ENABLED: bool = True
    DETECTION_RETENTION_DAYS: int = 30
    DETECTION_CLEANUP_INTERVAL_SECONDS: int = 3600
    DETECTION_CLEANUP_BATCH_SIZE: int = 500

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

    @model_validator(mode="after")
    def _validate_production_safety(self) -> "Settings":
        if self.is_production:
            if self.BACKEND_SECRET_KEY.strip().lower() in _INSECURE_SECRETS:
                raise ValueError(
                    "BACKEND_SECRET_KEY must be set to a strong, non-default value in production."
                )
            if self.APP_DEBUG:
                raise ValueError("APP_DEBUG must be false in production.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
