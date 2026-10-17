"""Arm_Definition Pydantic schemas — Designer-owned authoring surface.

Request/response contracts for authoring an ``Arm_Definition`` inside a
Draft_Design.

Satisfies Requirements:
  - 4.5: Persist an Arm_Definition within a Draft_Design.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    BaseUpdateSchema,
    UtcDatetime,
)


class ArmDefinitionCreate(BaseCreateSchema):
    """Request body for creating an Arm_Definition in a Draft_Design."""

    name: str = Field(..., min_length=1, max_length=100)
    display_order: int = Field(..., ge=1, le=999)
    description: str | None = None


class ArmDefinitionUpdate(BaseUpdateSchema):
    """Request body for editing an Arm_Definition (partial PATCH)."""

    name: str | None = Field(None, min_length=1, max_length=100)
    display_order: int | None = Field(None, ge=1, le=999)
    description: str | None = None


class ArmDefinitionResponse(BaseSchema):
    """Response schema for a persisted Arm_Definition.

    Visit/form scheduling is configured separately on the arm-scoped schedule
    of assessment.
    """

    id: UUID
    study_version_id: UUID
    name: str
    display_order: int
    description: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None


__all__ = [
    "ArmDefinitionCreate",
    "ArmDefinitionResponse",
    "ArmDefinitionUpdate",
]
