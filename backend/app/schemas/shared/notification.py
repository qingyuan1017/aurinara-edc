"""Pydantic response schemas for user notifications."""

from uuid import UUID

from app.models.shared.notification import NotificationStatus
from app.schemas.shared.base import BaseSchema, UtcDatetime


class NotificationResponse(BaseSchema):
    """A notification addressed to the authenticated user."""

    id: UUID
    user_id: UUID
    module: str | None = None
    correlation_id: str | None = None
    study_id: UUID | None = None
    site_id: UUID | None = None
    type: str
    payload_json: dict
    status: NotificationStatus
    created_at: UtcDatetime
    read_at: UtcDatetime | None = None
    destination_path: str | None = None
