"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.metrics import router as metrics_router
from app.api.v1.router import api_router
from app.config.settings import get_settings
from app.core.logging import configure_logging
from app.middleware.audit import AuditMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.modules.notification.api.notification_ws import router as notification_ws_router
from app.routers import health


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=__version__,
        debug=settings.APP_DEBUG,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        AuditMiddleware,
        skip_prefixes=("/auth/refresh",),
    )

    app.include_router(health.router)
    app.include_router(metrics_router)
    app.include_router(api_router, prefix=settings.BACKEND_API_PREFIX)
    app.include_router(notification_ws_router, prefix="/ws")

    return app


app = create_app()
