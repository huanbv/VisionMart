"""Generic schemas reused across the API."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class HealthStatus(BaseModel):
    status: str = Field(examples=["ok"])
    service: str
    version: str


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 20
