"""Pydantic schemas for file attachment routes."""

from uuid import UUID

from pydantic import Field, field_validator

from app.models.shared.file_attachment import FileAttachmentObjectType
from app.schemas.shared.base import BaseCreateSchema, BaseSchema, UtcDatetime


class FileAttachmentDelete(BaseCreateSchema):
    """Payload for logically deleting an attachment."""

    reason: str = Field(..., min_length=1, description="Reason for deleting the attachment")


class FileAttachmentResponse(BaseSchema):
    """Persisted attachment metadata and soft-delete state."""

    @field_validator("module", mode="before")
    @classmethod
    def default_module(cls, value: str | None) -> str:
        return value or "EDC"

    @field_validator("attachment_type", mode="before")
    @classmethod
    def default_attachment_type(cls, value: str | None) -> str:
        return value or "Clinical_Attachment"

    id: UUID
    module: str = "EDC"
    attachment_type: str = "Clinical_Attachment"
    object_type: FileAttachmentObjectType
    object_id: UUID
    study_id: UUID
    site_id: UUID | None = None
    subject_id: UUID | None = None
    filename: str
    content_type: str
    size_bytes: int
    storage_key: str
    uploaded_by: UUID
    uploaded_at: UtcDatetime
    deleted_at: UtcDatetime | None = None
    deleted_by: UUID | None = None
    delete_reason: str | None = None
    retention_until: UtcDatetime | None = None
    correlation_id: str | None = None
    archived_at: UtcDatetime | None = None
    archived_by: UUID | None = None
    archive_reason: str | None = None
    restored_at: UtcDatetime | None = None
    restored_by: UUID | None = None
