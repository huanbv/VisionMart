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

    # ---- Operational Monitoring (read-only proxy target; see monitoring/) ----
    MONITORING_SERVICE_URL: str = "http://monitoring:8200"
    MONITORING_API_TOKEN: str = "change-me-monitoring-token"

    # ---- Detection alerts ----
    DETECTION_ALERT_MIN_CONFIDENCE: float = 0.7
    DETECTION_ALERT_CLASSES: str = "person"
    DETECTION_ALERT_DEDUP_SECONDS: int = 60
    DETECTION_ALERT_FALLBACK_ROLE_CODE: str = "org_admin"

    # ---- Auth rate limiting ----
    AUTH_LOGIN_RATE_LIMIT: int = 10
    AUTH_LOGIN_RATE_WINDOW_SECONDS: int = 300
    AUTH_REFRESH_RATE_LIMIT: int = 60
    AUTH_REFRESH_RATE_WINDOW_SECONDS: int = 300

    # ---- Public /shop/* rate limiting ----
    # /shop/checkout/{token} and its confirm/cancel actions require no
    # login (the token itself is the credential — see PUBLIC_APP_BASE_URL
    # above), so unlike every other mutating endpoint in this API they're
    # reachable by anyone who can guess or intercept a token, or who just
    # wants to hammer the endpoint. Same IP-keyed fixed-window limiter as
    # /auth/*, mirrored here rather than shared 1:1 since a checkout-token
    # guesser and a login brute-forcer are different threat profiles.
    SHOP_CHECKOUT_RATE_LIMIT: int = 30
    SHOP_CHECKOUT_RATE_WINDOW_SECONDS: int = 60

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

    # --- Dọn dẹp telemetry AI (ai_frames / ai_logs / ai_sessions) ---
    # Bật mặc định: các bảng này tăng ~2,5 triệu dòng/camera/ngày, để
    # không giới hạn thì sớm muộn cũng đầy đĩa. Chúng là dữ liệu chẩn
    # đoán — nhãn huấn luyện nằm ở bảng khác và KHÔNG bị job này đụng tới
    # (xem retention_service.py).
    AI_PIPELINE_CLEANUP_ENABLED: bool = True
    AI_PIPELINE_CLEANUP_INTERVAL_SECONDS: int = 21600   # 6 giờ
    # Log dày nhất, giữ ngắn nhất.
    AI_LOG_RETENTION_DAYS: int = 7
    # Khung hình kéo theo detection/classification/ocr/embedding (CASCADE).
    AI_FRAME_RETENTION_DAYS: int = 7
    # Phiên chỉ bị xoá khi đã rỗng cả khung hình lẫn sự kiện.
    AI_SESSION_RETENTION_DAYS: int = 90

    # ---- Shopping Cart / AI checkout ----
    AI_ENGINE_API_KEY: str = "change-me-ai-engine-key"
    CART_EXPIRATION_MINUTES: int = 30
    # Cart do AI dựng có vòng đời ngắn hơn cart thủ công: nếu 15 phút không
    # có hoạt động nào (AI thêm/bớt món) và không ai xác nhận thanh toán,
    # cart tự bị dọn (chuyển ABANDONED, nhả tồn kho). Tách khỏi
    # CART_EXPIRATION_MINUTES để không đổi hành vi cart nhân viên tạo tay.
    AI_CART_EXPIRATION_MINUTES: int = 15
    CART_SWEEPER_INTERVAL_SECONDS: int = 60
    CART_AI_MIN_CONFIDENCE: float = 0.6

    # ---- AI-assisted checkout: human confirmation required ----
    # AI detection ends at "pending checkout" — checkout_initiated freezes
    # the cart into PENDING_CHECKOUT (bill generated, nothing charged yet)
    # instead of billing instantly. AI never calls the payment gateway and
    # never confirms a sale; a human always does, one of two ways:
    #   * the customer confirms via a QR code (encodes PUBLIC_APP_BASE_URL +
    #     /shop/checkout/{token}) shown on a customer-facing screen, or
    #   * staff confirm on the customer's behalf for walk-ins without a phone.
    # If nobody confirms within the timeout, the cart reverts to ACTIVE so
    # the shopper can keep shopping / retry — this is NOT an autonomous
    # "walk out and get charged" system; every sale requires an explicit
    # confirmation step.
    CART_CHECKOUT_CONFIRM_TIMEOUT_MINUTES: int = 5
    # Public origin used to build the QR/confirm link shown to customers.
    # Must be reachable from a customer's own phone (not an internal Docker
    # hostname) — e.g. https://visionmart.thehuan.com
    PUBLIC_APP_BASE_URL: str = "https://visionmart.thehuan.com"

    # ---- Cross-camera visitor linking (anonymous journey tracking) ----
    # Heuristic v1: no real appearance/ReID model. When a track is seen for
    # the first time on a given camera, we hand it the most recently active
    # "global visitor" for the same branch if one was last seen within this
    # window (customer walking from one camera's view into another's).
    # Two shoppers who both cross camera boundaries within this window can
    # be misattributed to each other — see visitor_linker.py docstring.
    VISITOR_HANDOFF_WINDOW_SECONDS: int = 20
    VISITOR_TRACK_TTL_SECONDS: int = 90
    VISITOR_ACTIVE_TTL_SECONDS: int = 600

    # ---- Continuous frame pipeline (product pickup/return + checkout AI) ----
    # Separate from RTSP_CAPTURE_* (which only does generic detection+alerts
    # every RTSP_CAPTURE_INTERVAL_SECONDS via /capture). This drives the real
    # tracking + cart automation pipeline via /ai/frame, so it needs a much
    # shorter interval to catch pickup events — keep camera count conservative,
    # each camera holds its own full YOLO model in ai-engine RAM (see
    # person_tracker.py).
    FRAME_PIPELINE_ENABLED: bool = False
    FRAME_PIPELINE_INTERVAL_SECONDS: int = 3
    FRAME_PIPELINE_MAX_CAMERAS: int = 8
    FRAME_PIPELINE_MIN_CONFIDENCE: float = 0.35
    FRAME_PIPELINE_RECOGNIZE_FACE: bool = False
    FRAME_PIPELINE_OPEN_TIMEOUT_MS: int = 4000

    # ---- Payment gateway ----
    PAYMENT_GATEWAY: str = "simulated"
    PAYMENT_SIMULATE_SUCCESS_RATE: float = 1.0

    # ---- MinIO ----
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ROOT_USER: str = "visionmart"
    MINIO_ROOT_PASSWORD: str = "visionmart-minio"
    MINIO_BUCKET: str = "visionmart"
    MINIO_USE_SSL: bool = False
    MINIO_PUBLIC_ENDPOINT: str | None = None
    MINIO_PUBLIC_USE_SSL: bool = True
    # Optional path prefix when MinIO is reverse-proxied (e.g. "/visionmart").
    # Leave empty when MINIO_PUBLIC_ENDPOINT points directly at MinIO.
    MINIO_PUBLIC_PATH_PREFIX: str = ""
    # Explicit bucket region. The minio SDK otherwise auto-detects the region
    # by calling GET /{bucket}?location= *without* a trailing slash, which
    # commonly doesn't match reverse-proxy path rules (e.g. an nginx
    # `location /visionmart/ { ... }` block only matches paths ending in a
    # slash) and gets misrouted. Setting this explicitly skips that lookup.
    MINIO_REGION: str = "us-east-1"

    # ---- Camera simulation (course project — no physical cameras yet) ----
    # Uploaded demo videos (see camera_router.py's /simulated-stream
    # endpoint) land in a *separate*, public-read MinIO bucket — never
    # MINIO_BUCKET, which holds private snapshots — so the standalone
    # "camera-sim-runner" container (docker-compose.yml) can loop them over
    # plain HTTP without credentials. CAMERA_SIM_RTSP_HOST/PORT must match
    # the "rtsp-sim" service's in-network name/port. See
    # docs/21_CAMERA_MANAGER.md and docker-compose.yml's "camera-sim" block.
    MINIO_CAMERA_SIM_BUCKET: str = "camera-sim"
    CAMERA_SIM_RTSP_HOST: str = "rtsp-sim"
    CAMERA_SIM_RTSP_PORT: int = 8554

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
            # `AI_ENGINE_API_KEY` is the *only* auth guarding /api/v1/ai/cart-events
            # (creates orders) and /api/v1/ai/customers/by-face-ref (returns
            # customer PII). The default value is published in .env.example, so
            # leaving it unchanged in production lets anyone on the internet call
            # those endpoints unauthenticated.
            if (
                self.AI_ENGINE_API_KEY.strip().lower() in _INSECURE_SECRETS
                or self.AI_ENGINE_API_KEY == "change-me-ai-engine-key"
            ):
                raise ValueError(
                    "AI_ENGINE_API_KEY must be set to a strong, non-default value in production "
                    "(it is the only auth on the /ai/cart-events and /ai/customers/by-face-ref endpoints)."
                )
            if self.MINIO_ROOT_PASSWORD.strip().lower() in _INSECURE_SECRETS or (
                self.MINIO_ROOT_PASSWORD == "visionmart-minio"
            ):
                raise ValueError(
                    "MINIO_ROOT_PASSWORD must be set to a strong, non-default value in production."
                )
            # `MONITORING_API_TOKEN` must match the same value configured on the
            # standalone `monitoring` service (monitoring/config.py's
            # MONITORING_API_TOKEN) — this backend uses it server-side, in
            # app/modules/ops_monitoring/api/router.py, to authenticate to
            # monitoring on the frontend's behalf. Leaving the shared default
            # would let anyone who can reach the monitoring service directly
            # (bypassing this backend) read operational data with the
            # published default token.
            if (
                self.MONITORING_API_TOKEN.strip().lower() in _INSECURE_SECRETS
                or self.MONITORING_API_TOKEN == "change-me-monitoring-token"
            ):
                raise ValueError(
                    "MONITORING_API_TOKEN must be set to a strong, non-default value in production "
                    "(and must match the monitoring service's own MONITORING_API_TOKEN)."
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
