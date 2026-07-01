"""AI Engine FastAPI application.

This service is intentionally kept separate from the backend API so it can be
deployed independently (GPU node, edge gateway, etc.) without changing the
public contract.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from app import __version__
from app.api.capture import router as capture_router
from app.api.detect import router as detect_router

logger = logging.getLogger("ai-engine")


class HealthStatus(BaseModel):
    status: str
    service: str
    version: str


app = FastAPI(
    title="VisionMart AI Engine",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/health", response_model=HealthStatus, tags=["health"])
async def health() -> HealthStatus:
    return HealthStatus(status="ok", service="ai-engine", version=__version__)


@app.get("/ready", response_model=HealthStatus, tags=["health"])
async def ready() -> HealthStatus:
    return HealthStatus(status="ready", service="ai-engine", version=__version__)


app.include_router(detect_router)
app.include_router(capture_router)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
