"""Pydantic v2 schemas for clinical review endpoints."""

from datetime import datetime
from uuid import UUID

from app.schemas.base import BaseSchema


class ReviewStatusResponse(BaseSchema):
    """Current review state for one form instance."""

    id: UUID
    form_instance_id: UUID
    is_reviewed: bool
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ReviewProgressResponse(BaseSchema):
    """Reviewed and not-reviewed form counts for a requested study."""

    reviewed: int
    not_reviewed: int
