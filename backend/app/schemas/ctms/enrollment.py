"""Pydantic contracts for CTMS enrollment targets and subject milestones."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.core.ctms import ensure_utc
from app.models.ctms.enrollment import (
    EnrollmentTargetStatus,
    EnrollmentTargetType,
    OperationalSubjectStatus,
)
from app.schemas.base import BaseCreateSchema, BaseSchema


class EnrollmentTargetCreate(BaseCreateSchema):
    """Create an operational target for a study or one of its sites."""

    model_config = ConfigDict(extra="forbid")

    study_id: UUID
    site_id: UUID | None = None
    target_type: EnrollmentTargetType
    target_quantity: int = Field(gt=0)
    planning_period_start: datetime
    planning_period_end: datetime
    dimension: dict[str, Any] = Field(default_factory=dict)
    owner_id: UUID | None = None
    status: EnrollmentTargetStatus = EnrollmentTargetStatus.draft

    @field_validator("planning_period_start", "planning_period_end")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("planning_period_end")
    @classmethod
    def period_is_ordered(cls, value: datetime, info) -> datetime:
        start = info.data.get("planning_period_start")
        if start is not None and value < start:
            raise ValueError("planning_period_end must not precede planning_period_start")
        return value


class EnrollmentTargetUpdate(BaseCreateSchema):
    """Update mutable planning fields without changing canonical references."""

    model_config = ConfigDict(extra="forbid")

    target_quantity: int | None = Field(default=None, gt=0)
    planning_period_start: datetime | None = None
    planning_period_end: datetime | None = None
    dimension: dict[str, Any] | None = None
    owner_id: UUID | None = None
    status: EnrollmentTargetStatus | None = None

    @field_validator("planning_period_start", "planning_period_end")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class EnrollmentTargetResponse(BaseSchema):
    """Serialized CTMS enrollment target."""

    id: UUID
    study_id: UUID
    site_id: UUID | None
    target_type: EnrollmentTargetType
    target_quantity: int
    planning_period_start: datetime
    planning_period_end: datetime
    dimension: dict[str, Any]
    owner_id: UUID | None
    status: EnrollmentTargetStatus
    retention_state: str
    correlation_id: UUID
    created_by: UUID
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class OperationalMilestoneCreate(BaseCreateSchema):
    """Record operational progress against an existing EDC subject.

    ``subject_id`` is mandatory and is always resolved against the EDC
    registry.  The two display/reference fields are approved operational
    values, not replacements for the canonical EDC identifier.
    """

    model_config = ConfigDict(extra="forbid")

    study_id: UUID
    site_id: UUID | None = None
    subject_id: UUID
    approved_pseudonym: str | None = Field(default=None, min_length=1, max_length=255)
    approved_reference: str | None = Field(default=None, min_length=1, max_length=255)
    milestone_type: str = Field(min_length=1, max_length=100)
    milestone_date: datetime
    status: OperationalSubjectStatus

    @field_validator("milestone_date")
    @classmethod
    def timestamp_is_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("approved_pseudonym", "approved_reference")
    @classmethod
    def non_blank_reference(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("approved references must not be blank")
        return value


class OperationalMilestoneResponse(BaseSchema):
    """Serialized operational subject milestone."""

    id: UUID
    study_id: UUID
    site_id: UUID | None
    subject_id: UUID
    approved_pseudonym: str | None
    approved_reference: str | None
    milestone_type: str
    milestone_date: datetime
    status: OperationalSubjectStatus
    retention_state: str
    correlation_id: UUID
    created_by: UUID
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class SubjectStatusProjectionRule(BaseSchema):
    """Explicit EDC-to-CTMS rule for a minimized subject status projection."""

    edc_status: str
    ctms_status: OperationalSubjectStatus
    rule_version: int = Field(ge=1)
    authoritative_module: str = "EDC"
    projection_target: str = "CTMS"
    active: bool = True


__all__ = [
    "EnrollmentTargetCreate",
    "EnrollmentTargetResponse",
    "EnrollmentTargetStatus",
    "EnrollmentTargetType",
    "EnrollmentTargetUpdate",
    "OperationalMilestoneCreate",
    "OperationalMilestoneResponse",
    "OperationalSubjectStatus",
    "SubjectStatusProjectionRule",
]
