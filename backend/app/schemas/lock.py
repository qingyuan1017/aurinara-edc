"""Pydantic schemas for freeze and lock controls."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models.lock import FreezeLockObjectType, FreezeLockType
from app.schemas.base import BaseCreateSchema, BaseSchema


class UnlockRequest(BaseCreateSchema):
    """Reason required to remove a freeze or lock control."""

    reason: str = Field(description="Reason for removing the control")


class FreezeLockResponse(BaseSchema):
    """Persisted freeze/lock control and its audit-relevant metadata."""

    id: UUID
    object_type: FreezeLockObjectType
    object_id: UUID
    lock_type: FreezeLockType
    is_active: bool
    locked_by: UUID
    locked_at: datetime
    unlocked_by: UUID | None = None
    unlocked_at: datetime | None = None
    unlock_reason: str | None = None
    created_at: datetime
