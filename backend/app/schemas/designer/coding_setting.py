"""Coding_Setting Pydantic schemas — Designer-owned authoring surface.

Request/response contracts for authoring a ``Coding_Setting`` inside a
Draft_Design.

Satisfies Requirements:
  - 4.8: Persist a coding setting (dictionary reference + rule) per coded item
         within a design version.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    UtcDatetime,
)


class CodingSettingCreate(BaseCreateSchema):
    """Request body for creating a Coding_Setting in a Draft_Design."""

    dictionary_reference: str = Field(..., min_length=1, max_length=255)
    coding_rule: str | None = None
    field_definition_id: UUID | None = None
    dictionary_version: str | None = Field(None, max_length=100)
    coding_level: str | None = Field(None, max_length=100)
    locale: str | None = Field(None, max_length=35)
    priority: int = Field(default=100, ge=0, le=10_000)
    approval_required: bool = True
    auto_approval: bool = False


class CodingSettingResponse(BaseSchema):
    """Response schema for a persisted Coding_Setting."""

    id: UUID
    design_version_id: UUID
    dictionary_reference: str
    coding_rule: str | None = None
    field_definition_id: UUID | None = None
    dictionary_version: str | None = None
    coding_level: str | None = None
    locale: str | None = None
    priority: int = 100
    approval_required: bool = True
    auto_approval: bool = False
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None


__all__ = [
    "CodingSettingCreate",
    "CodingSettingResponse",
]
