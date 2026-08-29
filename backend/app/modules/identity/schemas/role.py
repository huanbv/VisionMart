"""Pydantic schemas for Role read endpoints."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class RoleResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None

    model_config = {"from_attributes": True}
