"""Subject_Phase_Transition Pydantic schemas — Designer-owned authoring surface.

Request/response contracts for authoring a subject-phase-to-phase transition
edge inside a Draft_Design. The read-only, published-design view
(``SubjectPhaseTransitionView``) lives in ``app.schemas.designer.views`` and is
part of the Design_Consumption_Contract; these schemas are the mutable
design-time authoring surface.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    UtcDatetime,
)


class SubjectPhaseTransitionCreate(BaseCreateSchema):
    """Request body for creating a subject-phase transition in a Draft_Design."""

    from_phase_id: UUID
    to_phase_id: UUID
    label: str | None = Field(None, max_length=255)
    condition_expression: str | None = None


class SubjectPhaseTransitionResponse(BaseSchema):
    """Response schema for a persisted subject-phase transition.

    ``updated_at`` is intentionally omitted for parity with
    ``VisitDependencyResponse``.
    """

    id: UUID
    design_version_id: UUID
    from_phase_id: UUID
    to_phase_id: UUID
    label: str | None = None
    condition_expression: str | None = None
    created_at: UtcDatetime


__all__ = [
    "SubjectPhaseTransitionCreate",
    "SubjectPhaseTransitionResponse",
]
