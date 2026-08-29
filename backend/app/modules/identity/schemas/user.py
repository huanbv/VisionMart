"""Pydantic schemas for User management."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UserResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    username: str
    full_name: str | None
    is_active: bool
    is_superuser: bool
    roles: list[str]
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    skip: int
    limit: int


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool = True
    role_codes: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=255)
    role_codes: list[str] | None = None
