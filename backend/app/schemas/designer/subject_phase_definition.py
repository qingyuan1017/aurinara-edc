"""Subject_Phase_Definition Pydantic schemas — Designer-owned.

Request/response contracts for authoring a ``Subject_Phase_Definition`` inside a
``Draft_Design``. The read-only, published-design view
(``SubjectPhaseDefinitionView``) lives in ``app.schemas.designer.views`` and is
part of the Design_Consumption_Contract; these schemas are the mutable
design-time authoring surface.

Satisfies Requirements:
  - 3.1: Name 1-100 chars, display_order 1-999 (enforced as field bounds).
  - 3.2: Duplicate names are rejected by the service (surfaced in the response).
  - 3.3: Each definition binds to exactly one Design_Version.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.models.designer.subject_phase_definition import SubjectPhaseType
from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    BaseUpdateSchema,
    UtcDatetime,
)


class SubjectPhaseDefinitionCreate(BaseCreateSchema):
    """Request body for creating a Subject_Phase_Definition in a Draft_Design."""

    name: str = Field(..., min_length=1, max_length=100)
    phase_type: SubjectPhaseType = SubjectPhaseType.common
    display_order: int = Field(..., ge=1, le=999)
    visit_definition_ids: list[UUID] = Field(default_factory=list)


class SubjectPhaseDefinitionUpdate(BaseUpdateSchema):
    """Request body for editing a Subject_Phase_Definition (partial PATCH)."""

    name: str | None = Field(None, min_length=1, max_length=100)
    phase_type: SubjectPhaseType | None = None
    display_order: int | None = Field(None, ge=1, le=999)
    visit_definition_ids: list[UUID] | None = None


class SubjectPhaseDefinitionResponse(BaseSchema):
    """Response schema for a persisted Subject_Phase_Definition."""

    id: UUID
    design_version_id: UUID
    name: str
    phase_type: SubjectPhaseType
    display_order: int
    visit_definition_ids: list[UUID] = Field(default_factory=list)
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None


__all__ = [
    "SubjectPhaseDefinitionCreate",
    "SubjectPhaseDefinitionResponse",
    "SubjectPhaseDefinitionUpdate",
    "SubjectPhaseType",
]
