"""Validated PV safety export contracts (Requirement 12).

These transport contracts constrain a PV safety export request. PV safety
exports run on the shared export-job infrastructure but their formats, filters,
and produced content are PV-owned and kept separate from EDC clinical and CTMS
operational exports (Requirement 12.6).

The accepted formats are exactly CSV, Excel, JSON, and E2B XML; any other
requested format is rejected (Requirement 12.5). The applied filters (study,
site, subject reference, case status, seriousness, report status, and an
inclusive UTC date range) intersect, and a requested UTC date span exceeding
1,830 days is rejected before any Completed job can be created (Requirement
12.3).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.models.pv.regulatory import ReportStatus
from app.models.pv.safety_case import CaseState
from app.schemas.base import BaseCreateSchema, BaseSchema

# The maximum inclusive UTC date-range span accepted for a PV safety export
# (Requirement 12.3). A requested span strictly greater than this is rejected
# without creating a Completed job.
MAX_DATE_RANGE_DAYS = 1830


class PVExportFormat(StrEnum):
    """Formats accepted and produced by the PV safety exporter (Req 12.5).

    Exactly CSV, Excel, JSON, and E2B XML. Clinical-only formats (ODM, SAS
    transport, subject-list) and CTMS operational formats are intentionally not
    accepted by this contract.
    """

    CSV = "csv"
    EXCEL = "excel"
    JSON = "json"
    E2B_XML = "e2b_xml"


class PVExportFilters(BaseCreateSchema):
    """Allowlisted intersection filters for a PV safety export (Req 12.3).

    Every provided filter narrows the produced set; filters combine as an
    intersection. Only PV-owned safety filter dimensions are accepted here so a
    safety export can never select EDC clinical or CTMS operational content.
    """

    model_config = ConfigDict(extra="forbid")

    site_id: UUID | None = None
    subject_reference: UUID | None = None
    case_statuses: list[CaseState] = Field(default_factory=list, max_length=len(CaseState))
    seriousness: bool | None = None
    report_statuses: list[ReportStatus] = Field(
        default_factory=list, max_length=len(ReportStatus)
    )
    date_from: datetime | None = None
    date_to: datetime | None = None

    @field_validator("date_from", "date_to")
    @classmethod
    def require_aware_utc(cls, value: datetime | None) -> datetime | None:
        """Reject naive timestamps and normalize to UTC (Requirement 12.3)."""
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("export dates must include timezone information")
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def validate_date_range(self) -> PVExportFilters:
        if self.date_from is not None and self.date_to is not None:
            if self.date_from > self.date_to:
                raise ValueError("date_from must be earlier than or equal to date_to")
            # Inclusive span: both endpoints count. A span strictly greater than
            # the configured maximum is rejected here so no Completed job is
            # created (Requirement 12.3).
            span_days = (self.date_to - self.date_from).days
            if span_days > MAX_DATE_RANGE_DAYS:
                raise ValueError(
                    "requested UTC date-range span exceeds the maximum of "
                    f"{MAX_DATE_RANGE_DAYS} days"
                )
        return self


class PVExportCreate(BaseCreateSchema):
    """Request to create a PV safety export job."""

    model_config = ConfigDict(extra="forbid")

    export_type: PVExportFormat = Field(default=PVExportFormat.CSV)
    filters: PVExportFilters = Field(default_factory=PVExportFilters)


class PVExportResponse(BaseSchema):
    """A PV safety export job as returned by the API."""

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


class PVExportListResponse(BaseSchema):
    items: list[PVExportResponse]
    page: int
    page_size: int
    total: int


__all__ = [
    "MAX_DATE_RANGE_DAYS",
    "PVExportCreate",
    "PVExportFilters",
    "PVExportFormat",
    "PVExportListResponse",
    "PVExportResponse",
]
