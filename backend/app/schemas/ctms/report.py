"""Pydantic contracts for minimized CTMS report queries."""

from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.shared.base import BaseCreateSchema, BaseSchema, UtcDatetime


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
    created_at: UtcDatetime
    updated_at: UtcDatetime | None


class CTMSReportResponse(BaseSchema):
    study_id: UUID
    site_id: UUID | None = None
    category: str | None = None
    report_type: str
    label: str | None = None
    data_source: str = "ctms"
    read_only: bool = True
    items: list[dict[str, Any]] = Field(default_factory=list)
    totals: dict[str, Any] = Field(default_factory=dict)
    generated_at: UtcDatetime


class CTMSReportDefinition(BaseSchema):
    category: str
    category_label: str
    report_type: str
    label: str
    data_source: str
    read_only: bool = True


class CTMSReportCatalogResponse(BaseSchema):
    items: list[CTMSReportDefinition] = Field(default_factory=list)


__all__ = [
    "CTMSReportCatalogResponse",
    "CTMSReportDefinition",
    "CTMSReportResponse",
    "ReportQueryCreate",
    "ReportQueryResponse",
]
