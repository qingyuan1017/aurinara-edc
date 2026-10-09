"""Crf_Access_Definition Pydantic schemas — Designer-owned authoring surface.

Request/response contracts for authoring a ``Crf_Access_Definition`` inside a
Draft_Design.

Satisfies Requirements:
  - 4.6: Persist per-role read/write access for a form or field within a design
         version.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    UtcDatetime,
)


class CrfAccessDefinitionCreate(BaseCreateSchema):
    """Request body for creating a Crf_Access_Definition in a Draft_Design.

    ``blinded`` applies at whichever scope the grant expresses (form or field).
    ``unblind_role`` optionally names a role permitted to unblind; the service
    requires ``blinded`` to be True when ``unblind_role`` is set.
    """

    role: str = Field(..., min_length=1, max_length=100)
    can_read: bool = False
    can_write: bool = False
    form_definition_id: UUID | None = None
    field_definition_id: UUID | None = None
    blinded: bool = False
    unblind_role: str | None = Field(None, max_length=100)


class CrfAccessDefinitionResponse(BaseSchema):
    """Response schema for a persisted Crf_Access_Definition."""

    id: UUID
    design_version_id: UUID
    role: str
    can_read: bool
    can_write: bool
    form_definition_id: UUID | None = None
    field_definition_id: UUID | None = None
    blinded: bool = False
    unblind_role: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None


__all__ = [
    "CrfAccessDefinitionCreate",
    "CrfAccessDefinitionResponse",
]
