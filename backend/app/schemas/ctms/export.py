"""Validated CTMS operational export contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.models.ctms.ownership import ProjectionType
from app.schemas.base import BaseCreateSchema, BaseSchema


class OperationalExportFormat(StrEnum):
    """Formats supported by the CTMS operational exporter.

    Clinical-only formats (ODM, SAS transport, and subject-list exports) are
    intentionally not accepted by this contract.
    """

    CSV = "csv"
    JSON = "json"
    EXCEL = "excel"


OperationalRecordType = Literal[
    "operational_study",
    "study_plan",
    "enrollment_plan",
    "readiness_criterion",
    "study_milestone",
    "operational_site",
    "activation_action",
    "enrollment_target",
    "operational_milestone",
    "monitoring_plan",
    "monitoring_plan_version",
    "monitoring_activity",
    "operational_task",
    "operational_contact",
]


class OperationalExportFilters(BaseCreateSchema):
    """Allowlisted filters for CTMS-owned operational records."""

    model_config = ConfigDict(extra="forbid")

    site_id: UUID | None = None
    record_types: list[OperationalRecordType] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list, max_length=20)
    date_from: datetime | None = None
    date_to: datetime | None = None
    include_archived: bool = False
    include_projections: bool = False
    projection_types: list[str] = Field(default_factory=list, max_length=10)
    page: int = Field(default=1, ge=1, le=10000)
    page_size: int = Field(default=100, ge=1, le=1000)

    @field_validator("date_from", "date_to")
    @classmethod
    def require_aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("export dates must include timezone information")
        return value.astimezone(UTC) if value is not None else None

    @field_validator("statuses", "projection_types")
    @classmethod
    def reject_blank_values(cls, values: list[str], info) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("filter values must not be blank")
        if info.field_name == "projection_types":
            allowed = {projection_type.value for projection_type in ProjectionType}
            if any(value not in allowed for value in normalized):
                raise ValueError("projection_types must use an approved projection type")
        return normalized

    @model_validator(mode="after")
    def validate_date_range(self) -> OperationalExportFilters:
        if self.date_from is not None and self.date_to is not None and self.date_from > self.date_to:
            raise ValueError("date_from must be earlier than or equal to date_to")
        if self.projection_types and not self.include_projections:
            raise ValueError("projection_types require include_projections=true")
        return self


class OperationalExportCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    export_type: OperationalExportFormat = Field(default=OperationalExportFormat.CSV)
    filters: OperationalExportFilters = Field(default_factory=OperationalExportFilters)


class OperationalExportResponse(BaseSchema):
    id: UUID
    study_id: UUID
    module: str
    content_owner: str
    correlation_id: str | None = None
    export_type: str
    status: str
    filters: dict | None = None
    file_path: str | None = None
    file_size: int | None = None
    error_message: str | None = None
    requested_by: UUID
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class OperationalExportListResponse(BaseSchema):
    items: list[OperationalExportResponse]
    page: int
    page_size: int
    total: int


__all__ = [
    "OperationalExportCreate",
    "OperationalExportFilters",
    "OperationalExportFormat",
    "OperationalExportListResponse",
    "OperationalExportResponse",
]
