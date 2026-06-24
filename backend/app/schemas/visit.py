"""Visit Pydantic schemas.

Satisfies Requirements:
  - 8.1: Visit definition metadata — name, visit number, visit type, target day,
          window bounds, display order, required flag.
  - 8.3: Visit instance window status (before_window, in_window, after_window).
  - 8.4: Unscheduled visit creation.
  - 8.5: Visit instance status (including missed).
  - 21.2: List endpoints return a pagination envelope.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import Field

from app.models.visit import VisitInstanceStatus
from app.schemas.base import BaseCreateSchema, BaseSchema

# ---------------------------------------------------------------------------
# Visit definition schemas (Requirement 8.1)
# ---------------------------------------------------------------------------


class VisitDefinitionCreate(BaseCreateSchema):
    """Request body for defining a study visit (Requirement 8.1).

    Persisted against a draft Study_Version. ``target_day`` and the window
    bounds are optional (e.g. for screening or unscheduled visit types).
    """

    name: str = Field(..., min_length=1, max_length=255)
    visit_number: int = Field(..., description="Ordinal number of the visit")
    visit_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="e.g. scheduled, unscheduled, screening",
    )
    target_day: int | None = Field(
        None, description="Day relative to baseline (None when not applicable)"
    )
    window_before: int | None = Field(
        None, ge=0, description="Days before target_day still considered in window"
    )
    window_after: int | None = Field(
        None, ge=0, description="Days after target_day still considered in window"
    )
    display_order: int = Field(..., description="Sort order within the schedule")
    is_required: bool = Field(True, description="Whether the visit is required")


class VisitDefinitionResponse(BaseSchema):
    """Response schema for a visit definition (Requirement 8.1)."""

    id: UUID
    study_version_id: UUID
    name: str
    visit_number: int
    visit_type: str
    target_day: int | None = None
    window_before: int | None = None
    window_after: int | None = None
    display_order: int
    is_required: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Visit instance schemas (Requirements 8.3, 8.4, 8.5)
# ---------------------------------------------------------------------------


class VisitDateRecord(BaseCreateSchema):
    """Request body for recording a visit date (Requirement 8.3).

    The optional ``baseline_date`` anchors the day offset used to compute the
    window status relative to the definition's ``target_day``. When omitted,
    no window status is computed.
    """

    visit_date: date
    baseline_date: date | None = Field(
        None,
        description="Baseline (day 0) anchor for window-status computation",
    )


class UnscheduledVisitCreate(BaseCreateSchema):
    """Request body for creating an unscheduled visit instance (Requirement 8.4)."""

    name: str = Field(..., min_length=1, max_length=255)
    visit_date: date | None = Field(
        None, description="Optional date of the unscheduled visit"
    )


class VisitInstanceResponse(BaseSchema):
    """Response schema for a visit instance (Requirements 8.3, 8.4, 8.5)."""

    id: UUID
    subject_id: UUID
    visit_definition_id: UUID | None = None
    name: str
    visit_date: date | None = None
    window_status: str | None = None
    status: VisitInstanceStatus
    created_at: datetime
    updated_at: datetime | None = None
