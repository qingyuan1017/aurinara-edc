"""Query Pydantic schemas — request/response models for query lifecycle.

Satisfies Requirements:
  - 13.1: Query linked to exactly one affected object.
  - 13.2: Query statuses Open, Answered, Closed, Reopened, Cancelled.
  - 13.3: Response transitions query to Answered with message history.
  - 13.6: Complete threaded message history.
  - 21.2: List endpoints return pagination envelope.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models.query import QueryStatus, QueryTargetType, QueryType
from app.schemas.base import BaseCreateSchema, BaseSchema

# ---------------------------------------------------------------------------
# Query schemas (Requirement 13)
# ---------------------------------------------------------------------------


class QueryCreate(BaseCreateSchema):
    """Request body for creating a new Query (Requirement 13.1)."""

    target_type: QueryTargetType = Field(
        ..., description="Type of the affected object"
    )
    target_id: UUID = Field(
        ..., description="ID of the affected object"
    )
    text: str = Field(
        ..., min_length=1, max_length=4000, description="Initial query text"
    )
    query_type: QueryType = Field(
        default=QueryType.manual, description="Origin of the query"
    )
    assigned_role: str | None = Field(
        None, min_length=1, max_length=100,
        description="Role assigned to resolve the query",
    )
    site_id: UUID | None = Field(None, description="Optional site context")
    subject_id: UUID | None = Field(None, description="Optional subject context")


class QueryRespond(BaseCreateSchema):
    """Request body for responding to a Query (Requirement 13.3)."""

    message: str = Field(
        ..., min_length=1, max_length=4000, description="Response message text"
    )


class QueryMessageResponse(BaseSchema):
    """Response schema for a single message in the query thread (Req 13.6)."""

    id: UUID
    query_id: UUID
    author_id: UUID
    message: str
    created_at: datetime


class QueryResponse(BaseSchema):
    """Response schema for a Query record."""

    id: UUID
    study_id: UUID
    site_id: UUID | None = None
    subject_id: UUID | None = None
    target_type: str
    target_id: UUID
    text: str
    query_type: str
    assigned_role: str | None = None
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    closed_by: UUID | None = None
    messages: list[QueryMessageResponse] = Field(default_factory=list)


class QueryListResponse(BaseSchema):
    """Lightweight response schema for query listings (no messages)."""

    id: UUID
    study_id: UUID
    site_id: UUID | None = None
    subject_id: UUID | None = None
    target_type: str
    target_id: UUID
    text: str
    query_type: str
    assigned_role: str | None = None
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    closed_by: UUID | None = None


class QueryFilters(BaseSchema):
    """Filters for listing queries."""

    status: QueryStatus | None = None
    target_type: QueryTargetType | None = None
    query_type: QueryType | None = None
    site_id: UUID | None = None
    subject_id: UUID | None = None
