"""Contracts for configurable CTMS reference values."""

from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.models.ctms.reference_data import ReferenceCategory
from app.schemas.shared.base import BaseCreateSchema, BaseSchema, BaseUpdateSchema, UtcDatetime


def _not_blank(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value must not be blank")
    return value


class ReferenceValueCreate(BaseCreateSchema):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    category: ReferenceCategory
    code: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    sort_order: int = Field(default=0, ge=0)

    _validate_code = field_validator("code")(_not_blank)
    _validate_label = field_validator("label")(_not_blank)


class ReferenceValueUpdate(BaseUpdateSchema):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    sort_order: int | None = Field(default=None, ge=0)
    active: bool | None = None

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        return _not_blank(value) if value is not None else None


class ReferenceValueResponse(BaseSchema):
    id: UUID
    category: ReferenceCategory
    code: str
    label: str
    description: str | None = None
    sort_order: int
    active: bool
    created_by: UUID | None = None
    updated_by: UUID | None = None
    correlation_id: UUID | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


__all__ = ["ReferenceValueCreate", "ReferenceValueResponse", "ReferenceValueUpdate"]
