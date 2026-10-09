"""Schedule_of_Assessment Pydantic schemas — Designer-owned authoring surface.

Request/response contracts for authoring a ``Schedule_of_Assessment`` matrix
inside a Draft_Design.

Satisfies Requirements:
  - 4.1: Persist a schedule of assessment that maps forms/procedures to visit and
         cycle definitions within a design version.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    UtcDatetime,
)


class ScheduleEntryCreate(BaseCreateSchema):
    """One form/procedure-to-visit mapping within an SoA.

    Exactly one of ``form_definition_id`` or ``procedure_name`` identifies what
    is collected; a ``visit_definition_id`` (a plain visit or a cycle) identifies
    when it is collected. The service validates these invariants.
    """

    form_definition_id: UUID | None = None
    procedure_name: str | None = Field(None, min_length=1, max_length=255)
    visit_definition_id: UUID | None = None
    display_order: int = 1


class ScheduleOfAssessmentCreate(BaseCreateSchema):
    """Request body for creating a Schedule_of_Assessment in a Draft_Design."""

    entries: list[ScheduleEntryCreate] = Field(default_factory=list)


class ScheduleEntryResponse(BaseSchema):
    """Response schema for a persisted SoA entry."""

    id: UUID
    schedule_of_assessment_id: UUID
    form_definition_id: UUID | None = None
    procedure_name: str | None = None
    visit_definition_id: UUID | None = None
    display_order: int
    created_at: UtcDatetime


class ScheduleOfAssessmentResponse(BaseSchema):
    """Response schema for a persisted Schedule_of_Assessment."""

    id: UUID
    design_version_id: UUID
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None
    entries: list[ScheduleEntryResponse] = Field(default_factory=list)


__all__ = [
    "ScheduleEntryCreate",
    "ScheduleEntryResponse",
    "ScheduleOfAssessmentCreate",
    "ScheduleOfAssessmentResponse",
]
