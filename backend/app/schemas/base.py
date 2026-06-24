"""Base Pydantic v2 schemas and the generic paginated response envelope.

Satisfies Requirements:
  - 21.2: List endpoints return a pagination envelope (items, page, page_size, total).
  - 29.2: List endpoints return paginated results.
"""

from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard pagination envelope for all list endpoints.

    All list endpoints return this shape, ensuring clients have
    a predictable structure for iterating pages.
    """

    items: list[T]
    page: int
    page_size: int
    total: int


class BaseSchema(BaseModel):
    """Base schema with sensible Pydantic v2 defaults for all response models."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )


class BaseCreateSchema(BaseModel):
    """Base schema for creation (POST) request bodies."""

    model_config = ConfigDict(
        from_attributes=True,
    )


class BaseUpdateSchema(BaseModel):
    """Base schema for update (PATCH) request bodies.

    All fields should be Optional so clients can send partial payloads.
    """

    model_config = ConfigDict(
        from_attributes=True,
    )


class TimestampMixin(BaseSchema):
    """Mixin that adds created_at / updated_at fields to response schemas."""

    created_at: datetime
    updated_at: datetime | None = None


class IDMixin(BaseSchema):
    """Mixin that adds a UUID id field to response schemas."""

    id: UUID
