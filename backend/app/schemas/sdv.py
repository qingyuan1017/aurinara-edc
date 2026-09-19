"""Pydantic response schemas for source-data-verification endpoints."""

from datetime import datetime
from uuid import UUID

from app.models.sdv import SDVScopeType
from app.schemas.base import BaseSchema


class SDVStatusResponse(BaseSchema):
    """Current SDV state for a field or form instance."""

    id: UUID
    scope_type: SDVScopeType
    scope_id: UUID
    is_verified: bool
    verified_by: UUID | None = None
    verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class SDVProgressResponse(BaseSchema):
    """Verified and not-verified counts for a study scope."""

    verified: int
    not_verified: int
