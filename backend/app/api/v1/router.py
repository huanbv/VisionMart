"""Versioned API router aggregator.

Feature routers will be registered here in subsequent sprints, e.g.:

    from app.api.v1.endpoints import auth, cameras
    api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
"""

from __future__ import annotations

from fastapi import APIRouter

api_router = APIRouter()
