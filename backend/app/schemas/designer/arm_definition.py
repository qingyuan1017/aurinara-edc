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
    visit_definition_ids: list[UUID] = Field(default_factory=list)


class ArmDefinitionUpdate(BaseUpdateSchema):
    """Request body for editing an Arm_Definition (partial PATCH)."""

    name: str | None = Field(None, min_length=1, max_length=100)
    display_order: int | None = Field(None, ge=1, le=999)
    description: str | None = None
    visit_definition_ids: list[UUID] | None = None


class ArmDefinitionResponse(BaseSchema):
    """Response schema for a persisted Arm_Definition.

    ``visit_definition_ids`` lists the arm's real member visits (standalone and
    cycle-owned leaves). The route constructs this field explicitly from ``arm.visits``;
    ``model_validate(arm)`` cannot populate it because the ORM relationship is
    named ``visits``.
    """

    id: UUID
    study_version_id: UUID
    name: str
    display_order: int
    description: str | None = None
    visit_definition_ids: list[UUID] = Field(default_factory=list)
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None


__all__ = [
    "ArmDefinitionCreate",
    "ArmDefinitionResponse",
    "ArmDefinitionUpdate",
]
