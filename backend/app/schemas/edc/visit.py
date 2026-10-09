"""Visit Pydantic schemas — operational instance schemas; definition re-exported.

The design-time visit *definition* schemas (``VisitDefinitionCreate``,
``VisitDefinitionResponse``) were reassigned to the Designer module and now live
in ``app.schemas.designer.visit``. They are re-exported here so existing import
paths (``from app.schemas.edc.visit import VisitDefinitionCreate``) keep working
unchanged (R11.1 — additive, no breakage).

The operational visit *instance* schemas (recording a visit date, creating an
unscheduled visit, and the instance response) stay here — they describe
Operational_Records owned by the EDC module.

Satisfies Requirements:
  - 4.2: Visit definition metadata (now Designer-owned; re-exported).
  - 8.3: Visit instance window status (before_window, in_window, after_window).
  - 8.4: Unscheduled visit creation.
  - 8.5: Visit instance status (including missed).
  - 21.2: List endpoints return a pagination envelope.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field

from app.models.edc.visit import VisitInstanceStatus

# Visit definition schemas are owned by the Designer module. Re-exported here for
# backward compatibility with existing ``app.schemas.edc.visit`` imports.
from app.schemas.designer.visit import (
    VisitDefinitionCreate,
    VisitDefinitionResponse,
)
from app.schemas.shared.base import BaseCreateSchema, BaseSchema, UtcDatetime

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
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None


__all__ = [
    "UnscheduledVisitCreate",
    "VisitDateRecord",
    "VisitDefinitionCreate",
    "VisitDefinitionResponse",
    "VisitInstanceResponse",
]
