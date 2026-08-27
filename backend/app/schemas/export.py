"""Export Pydantic schemas — request/response models for export lifecycle.

Satisfies Requirements:
  - 19.1: Export job creation and status tracking.
  - 19.2: Subject list export.
  - 19.3: Filter parameters for exports.
  - 21.2: List endpoints return pagination envelope.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models.export import ExportType
from app.schemas.base import BaseCreateSchema, BaseSchema

# ---------------------------------------------------------------------------
# Filter schema (Requirement 19.3)
# ---------------------------------------------------------------------------


class ExportFilters(BaseSchema):
    """Filter parameters for an export job.

    All fields optional — only provided filters are applied when generating
    the export file.
    """

    site_id: UUID | None = None
    subject_id: UUID | None = None
    visit_id: UUID | None = None
    form_id: UUID | None = None
    domain: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    changed_since: datetime | None = None
    locked_only: bool | None = None
    clean_only: bool | None = None


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ExportCreate(BaseCreateSchema):
    """Request body for creating a new export job (Requirement 19.1)."""

    export_type: ExportType = Field(
        default=ExportType.csv,
        description="Export format type (csv, subject_list)",
    )
    filters: ExportFilters | None = Field(
        default=None,
        description="Optional filter parameters for the export",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ExportResponse(BaseSchema):
    """Full response schema for an export job."""

    id: UUID
    study_id: UUID
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


class ExportListResponse(BaseSchema):
    """Lightweight response schema for export job listings."""

    id: UUID
    study_id: UUID
    export_type: str
    status: str
    file_size: int | None = None
    requested_by: UUID
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
