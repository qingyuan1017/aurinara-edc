"""Pydantic response schemas for user notifications."""

from datetime import datetime
from uuid import UUID

from app.models.notification import NotificationStatus
from app.schemas.base import BaseSchema


class NotificationResponse(BaseSchema):
    """A notification addressed to the authenticated user."""

    id: UUID
    user_id: UUID
    type: str
    payload_json: dict
    status: NotificationStatus
    created_at: datetime
    read_at: datetime | None = None
