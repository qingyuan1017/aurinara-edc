"""Shared Pydantic v2 API contracts.

All response schemas inherit the same ORM, pagination, and UTC serialization
conventions. Error envelopes are defined here so EDC and CTMS use one shape.
"""

from datetime import UTC, datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

T = TypeVar("T")


def serialize_utc(value: datetime) -> str:
    """Serialize a timestamp to UTC ISO-8601.

    PostgreSQL ``TIMESTAMPTZ`` values are always aware. SQLite's portable test
    dialect drops timezone metadata when reloading a row, so a naive value at
    this serialization boundary is interpreted as UTC rather than allowing a
    test-dialect artifact to produce a 500 response.
    """

    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard ``items/page/page_size/total`` list response envelope."""

    items: list[T]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class ErrorBody(BaseModel):
    """The normalized error body shared by EDC and CTMS."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    correlation_id: str | None = None


class ErrorEnvelope(BaseModel):
    """The baseline ``{\"error\": {...}}`` API error response."""

    error: ErrorBody


class BaseSchema(BaseModel):
    """Base response schema with ORM compatibility and UTC JSON output."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_serializer("*", when_used="json", check_fields=False)
    def serialize_datetime_fields(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return serialize_utc(value)
        return value


class BaseCreateSchema(BaseModel):
    """Base schema for creation request bodies."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class BaseUpdateSchema(BaseModel):
    """Base schema for partial update request bodies."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TimestampMixin(BaseSchema):
    """Mixin that adds created/updated timestamps to response schemas."""

    created_at: datetime
    updated_at: datetime | None = None


class IDMixin(BaseSchema):
    """Mixin that adds a UUID id field to response schemas."""

    id: UUID


__all__ = [
    "BaseCreateSchema",
    "BaseSchema",
    "BaseUpdateSchema",
    "ErrorBody",
    "ErrorEnvelope",
    "IDMixin",
    "PaginatedResponse",
    "TimestampMixin",
    "serialize_utc",
]
