"""Pydantic v2 schemas for clinical review endpoints."""

from uuid import UUID

from app.schemas.shared.base import BaseSchema, UtcDatetime


class ReviewStatusResponse(BaseSchema):
    """Current review state for one form instance."""

    id: UUID
    form_instance_id: UUID
    is_reviewed: bool
    reviewed_by: UUID | None = None
    reviewed_at: UtcDatetime | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None


class ReviewProgressResponse(BaseSchema):
    """Reviewed and not-reviewed form counts for a requested study."""

    reviewed: int
    not_reviewed: int
