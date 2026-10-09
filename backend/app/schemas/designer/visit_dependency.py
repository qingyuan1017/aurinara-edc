"""Visit_Definition_Dependency Pydantic schemas — Designer-owned authoring surface.

Request/response contracts for authoring a visit-to-visit dependency edge inside
a Draft_Design. Because a cycle is now a visit, these contracts also express
cycle dependencies.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    UtcDatetime,
)


class VisitDependencyCreate(BaseCreateSchema):
    """Request body for creating a visit-to-visit dependency in a Draft_Design."""

    depends_on_visit_definition_id: UUID
    dependency_type: str = Field("prerequisite", min_length=1, max_length=50)
    condition_expression: str | None = None


class VisitDependencyResponse(BaseSchema):
    """Response schema for a persisted visit-to-visit dependency."""

    id: UUID
    visit_definition_id: UUID
    depends_on_visit_definition_id: UUID
    dependency_type: str
    condition_expression: str | None = None
    created_at: UtcDatetime


__all__ = [
    "VisitDependencyCreate",
    "VisitDependencyResponse",
]
