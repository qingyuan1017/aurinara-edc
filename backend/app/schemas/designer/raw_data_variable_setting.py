"""Raw_Data_Variable_Setting Pydantic schemas — Designer-owned authoring surface.

Request/response contracts for authoring a ``Raw_Data_Variable_Setting`` inside
a Draft_Design.

Satisfies Requirements:
  - 4.7: Persist a raw-data variable setting (name, type, attributes) per
         captured item within a design version.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    UtcDatetime,
)


class RawDataVariableSettingCreate(BaseCreateSchema):
    """Request body for creating a Raw_Data_Variable_Setting in a Draft_Design."""

    name: str = Field(..., min_length=1, max_length=255)
    data_type: str = Field(..., min_length=1, max_length=50)
    attributes: dict[str, Any] = Field(default_factory=dict)


class RawDataVariableSettingResponse(BaseSchema):
    """Response schema for a persisted Raw_Data_Variable_Setting."""

    id: UUID
    design_version_id: UUID
    name: str
    data_type: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None


__all__ = [
    "RawDataVariableSettingCreate",
    "RawDataVariableSettingResponse",
]
