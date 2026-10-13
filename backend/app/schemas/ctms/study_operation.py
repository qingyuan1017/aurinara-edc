"""Contracts for CTMS financial, risk, monitoring-issue, and tracking records."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.models.ctms.study_operation import StudyOperationResource
from app.schemas.shared.base import BaseCreateSchema, BaseSchema, BaseUpdateSchema, UtcDatetime


class StudyOperationCreate(BaseCreateSchema):
    title: str = Field(min_length=1, max_length=255)
    site_id: UUID | None = None
    subject_id: UUID | None = None
    reference_id: UUID | None = None
    record_subtype: str | None = Field(default=None, max_length=100)
    status: str = Field(default="Draft", min_length=1, max_length=40)
    owner_id: UUID | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "status", "record_subtype")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @model_validator(mode="after")
    def validate_period(self):
        if self.start_at and self.end_at and self.end_at < self.start_at:
            raise ValueError("end_at must be on or after start_at")
        return self


class StudyOperationUpdate(BaseUpdateSchema):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    site_id: UUID | None = None
    subject_id: UUID | None = None
    reference_id: UUID | None = None
    record_subtype: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, min_length=1, max_length=40)
    owner_id: UUID | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    details: dict[str, Any] | None = None
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("title", "status", "record_subtype", "reason")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class StudyOperationResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID | None = None
    subject_id: UUID | None = None
    reference_id: UUID | None = None
    resource_type: StudyOperationResource
    title: str
    record_subtype: str | None = None
    status: str
    owner_id: UUID | None = None
    start_at: UtcDatetime | None = None
    end_at: UtcDatetime | None = None
    amount: Decimal | None = None
    currency: str | None = None
    details: dict[str, Any] = Field(default_factory=dict, validation_alias="details_json")
    retention_state: str
    created_by: UUID
    updated_by: UUID | None = None
    correlation_id: UUID
    created_at: UtcDatetime
    updated_at: UtcDatetime


__all__ = [
    "StudyOperationCreate",
    "StudyOperationResource",
    "StudyOperationResponse",
    "StudyOperationUpdate",
]
