"""Pydantic contracts for minimized CTMS report queries."""

from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseCreateSchema, BaseSchema


class ReportQueryCreate(BaseCreateSchema):
    name: str = Field(min_length=1, max_length=255)
    query_definition: dict[str, Any] = Field(default_factory=dict)
    owner_id: UUID | None = None
    status: str = "Active"
    correlation_id: str | None = None


class ReportQueryResponse(BaseSchema):
    id: UUID
    study_id: UUID
    name: str
    query_definition: dict[str, Any]
    owner_id: UUID | None = None
    status: str
    created_by: UUID
    created_at: Any
    updated_at: Any


__all__ = ["ReportQueryCreate", "ReportQueryResponse"]


class CTMSReportResponse(BaseSchema):
    study_id: UUID
    site_id: UUID | None = None
    report_type: str
    items: list[dict[str, Any]] = Field(default_factory=list)
    totals: dict[str, Any] = Field(default_factory=dict)
    generated_at: Any
