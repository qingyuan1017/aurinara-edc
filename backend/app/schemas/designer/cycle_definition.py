"""Cycle_Definition Pydantic schemas — Designer-owned authoring surface.

Request/response contracts for authoring a ``Cycle_Definition`` inside a
Draft_Design.

Satisfies Requirements:
  - 4.4: Persist a Cycle_Definition and its member Visit_Definitions within a
         Draft_Design.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    UtcDatetime,
)


class CycleDefinitionCreate(BaseCreateSchema):
    """Request body for creating a Cycle_Definition in a Draft_Design."""

    name: str = Field(..., min_length=1, max_length=100)
    display_order: int = Field(..., ge=1, le=999)
    visit_definition_ids: list[UUID] = Field(default_factory=list)


class CycleDefinitionResponse(BaseSchema):
    """Response schema for a persisted Cycle_Definition."""

    id: UUID
    study_version_id: UUID
    name: str
    display_order: int
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None


__all__ = [
    "CycleDefinitionCreate",
    "CycleDefinitionResponse",
]
