"""Pydantic schemas for the Employee bounded context."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class EmployeeUserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    branch_id: uuid.UUID
    branch_name: str | None = None
    user_id: uuid.UUID | None
    user: EmployeeUserRef | None = None
    code: str
    full_name: str
    position: str | None
    hired_at: date | None
    terminated_at: date | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EmployeeListResponse(BaseModel):
    items: list[EmployeeResponse]
    total: int
    skip: int
    limit: int


class EmployeeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    full_name: str = Field(min_length=1, max_length=255)
    branch_id: uuid.UUID
    position: str | None = Field(default=None, max_length=120)
    user_id: uuid.UUID | None = None
    hired_at: date | None = None
    is_active: bool = True


class EmployeeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    branch_id: uuid.UUID | None = None
    position: str | None = None
    user_id: uuid.UUID | None = None
    hired_at: date | None = None
    is_active: bool | None = None

    position_unset: bool = False
    user_unset: bool = False
    hired_at_unset: bool = False


class EmployeeTerminate(BaseModel):
    terminated_at: date
