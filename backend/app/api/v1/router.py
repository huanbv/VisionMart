"""Versioned API router aggregator."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.identity.api.auth_router import router as auth_router
from app.modules.identity.api.role_router import router as role_router
from app.modules.identity.api.user_router import router as user_router
from app.modules.tenancy.api.branch_router import router as branch_router
from app.modules.tenancy.api.organization_router import router as organization_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(organization_router)
api_router.include_router(branch_router)
api_router.include_router(user_router)
api_router.include_router(role_router)
