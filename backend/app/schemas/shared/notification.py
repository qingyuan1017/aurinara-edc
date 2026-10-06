"""Pydantic response schemas for user notifications."""

from datetime import datetime
from uuid import UUID

from app.models.shared.notification import NotificationStatus
from app.schemas.shared.base import BaseSchema, UtcDatetime


class NotificationResponse(BaseSchema):
    """A notification addressed to the authenticated user."""

    id: UUID
    user_id: UUID
    type: str
    payload_json: dict
    status: NotificationStatus
    created_at: UtcDatetime
    read_at: UtcDatetime | None = None
