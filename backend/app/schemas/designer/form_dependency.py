"""Form_Definition_Dependency Pydantic schemas — Designer-owned authoring surface.

Request/response contracts for authoring a form-to-form dependency edge inside a
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


class FormDependencyCreate(BaseCreateSchema):
    """Request body for creating a form-to-form dependency in a Draft_Design."""

    depends_on_form_definition_id: UUID
    dependency_type: str = Field("prerequisite", min_length=1, max_length=50)
    condition_expression: str | None = None


class FormDependencyResponse(BaseSchema):
    """Response schema for a persisted form-to-form dependency."""

    id: UUID
    form_definition_id: UUID
    depends_on_form_definition_id: UUID
    dependency_type: str
    condition_expression: str | None = None
    created_at: UtcDatetime


__all__ = [
    "FormDependencyCreate",
    "FormDependencyResponse",
]
