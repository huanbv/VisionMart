"""Versioned API router aggregator."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.identity.api.auth_router import router as auth_router

api_router = APIRouter()
api_router.include_router(auth_router)
