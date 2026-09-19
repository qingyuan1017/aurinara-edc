"""Pydantic schemas for repeating form-record routes.

Satisfies Requirements 11.1-11.4 and 21.1: records are created, edited,
soft-deleted, and restored through validated JSON API payloads.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseCreateSchema, BaseSchema, BaseUpdateSchema


class FormRecordCreate(BaseCreateSchema):
    """Payload for adding a row to a repeating form instance."""

    values: dict[str, Any] | None = Field(
        default=None,
        description="Optional mapping of repeating-form field identifiers to values",
    )


class FormRecordUpdate(BaseUpdateSchema):
    """Payload for replacing an active repeating-record row's values."""

    values: dict[str, Any] = Field(
        ...,
        description="Mapping of repeating-form field identifiers to values",
    )


class FormRecordDelete(BaseCreateSchema):
    """Payload for a soft deletion; the reason is retained in history."""

    reason: str = Field(..., min_length=1, description="Reason for deleting the row")


class FormRecordResponse(BaseSchema):
    """Persisted repeating-record row, including soft-delete metadata."""

    id: UUID
    form_instance_id: UUID
    sequence_number: int
    data_jsonb: dict[str, Any] | None = None
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None
    deletion_reason: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
