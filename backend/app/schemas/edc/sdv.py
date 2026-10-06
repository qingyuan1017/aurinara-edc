"""Pydantic response schemas for source-data-verification endpoints."""

from uuid import UUID

from app.models.edc.sdv import SDVScopeType
from app.schemas.shared.base import BaseSchema, UtcDatetime


class SDVStatusResponse(BaseSchema):
    """Current SDV state for a field or form instance."""

    id: UUID
    scope_type: SDVScopeType
    scope_id: UUID
    is_verified: bool
    verified_by: UUID | None = None
    verified_at: UtcDatetime | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None


class SDVProgressResponse(BaseSchema):
    """Verified and not-verified counts for a study scope."""

    verified: int
    not_verified: int
