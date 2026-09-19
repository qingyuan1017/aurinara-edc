"""Pydantic contracts for minimized CTMS dashboard queries."""

from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseCreateSchema, BaseSchema


class DashboardQueryCreate(BaseCreateSchema):
    name: str = Field(min_length=1, max_length=255)
    query_definition: dict[str, Any] = Field(default_factory=dict)
    owner_id: UUID | None = None
    status: str = "Active"
    correlation_id: str | None = None


class DashboardQueryResponse(BaseSchema):
    id: UUID
    study_id: UUID
    name: str
    query_definition: dict[str, Any]
    owner_id: UUID | None = None
    status: str
    created_by: UUID
    created_at: Any
    updated_at: Any


__all__ = ["DashboardQueryCreate", "DashboardQueryResponse"]


class CTMSDashboardResponse(BaseSchema):
    study_id: UUID
    site_id: UUID | None = None
    operational: dict[str, Any] = Field(default_factory=dict)
    projected_clinical: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: Any
