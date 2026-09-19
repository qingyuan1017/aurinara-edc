"""Pydantic contracts for CTMS operational study workflows."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from app.models.ctms.operational_study import OperationalStudyStatus
from app.schemas.base import BaseCreateSchema, BaseSchema, BaseUpdateSchema


def _reason(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("reason must not be blank")
    return value


class OperationalStudyCreate(BaseCreateSchema):
    """CTMS-owned profile fields; ``study_id`` is a canonical EDC reference."""

    sponsor: str | None = Field(default=None, max_length=255)
    phase: str | None = Field(default=None, max_length=50)
    therapeutic_area: str | None = Field(default=None, max_length=255)
    indication: str | None = Field(default=None, max_length=255)
    operational_owner_id: UUID | None = None
    planning_metadata: dict[str, Any] = Field(default_factory=dict)
    readiness_criteria: dict[str, Any] = Field(default_factory=dict)
    status: OperationalStudyStatus = OperationalStudyStatus.DRAFT
    correlation_id: str | None = None


class OperationalStudyUpdate(BaseUpdateSchema):
    sponsor: str | None = Field(default=None, max_length=255)
    phase: str | None = Field(default=None, max_length=50)
    therapeutic_area: str | None = Field(default=None, max_length=255)
    indication: str | None = Field(default=None, max_length=255)
    operational_owner_id: UUID | None = None
    planning_metadata: dict[str, Any] | None = None
    readiness_criteria: dict[str, Any] | None = None
    correlation_id: str | None = None


class OperationalStudyStatusChange(BaseCreateSchema):
    status: OperationalStudyStatus
    reason: str
    correlation_id: str | None = None

    _validate_reason = field_validator("reason")(_reason)


class OperationalStudyArchive(BaseCreateSchema):
    reason: str
    correlation_id: str | None = None

    _validate_reason = field_validator("reason")(_reason)


class StudyPlanCreate(BaseCreateSchema):
    title: str = Field(min_length=1, max_length=255)
    objective: str | None = None
    planning_scope: dict[str, Any] = Field(default_factory=dict)
    owner_id: UUID | None = None
    status: str = "Draft"
    correlation_id: str | None = None


class EnrollmentPlanCreate(BaseCreateSchema):
    title: str = Field(min_length=1, max_length=255)
    target_quantity: int | None = Field(default=None, ge=0)
    planning_period_start: datetime | date | None = None
    planning_period_end: datetime | date | None = None
    planning_scope: dict[str, Any] = Field(default_factory=dict)
    owner_id: UUID | None = None
    status: str = "Draft"
    correlation_id: str | None = None


class ReadinessCriterionCreate(BaseCreateSchema):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    required: bool = True
    due_at: datetime | date | None = None
    correlation_id: str | None = None


class OperationalMilestoneCreate(BaseCreateSchema):
    title: str = Field(min_length=1, max_length=255)
    milestone_type: str = Field(min_length=1, max_length=100)
    planned_at: datetime | date | None = None
    owner_id: UUID | None = None
    notes: str | None = None
    correlation_id: str | None = None


class OperationalStudyResponse(BaseSchema):
    id: UUID
    study_id: UUID
    operational_owner_id: UUID | None = None
    sponsor: str | None = None
    phase: str | None = None
    therapeutic_area: str | None = None
    indication: str | None = None
    planning_metadata: dict[str, Any]
    readiness_criteria: dict[str, Any]
    status: OperationalStudyStatus
    retention_state: str
    archived_at: datetime | None = None
    created_by: UUID
    updated_by: UUID | None = None
    correlation_id: UUID
    created_at: datetime
    updated_at: datetime


__all__ = [
    "EnrollmentPlanCreate",
    "OperationalMilestoneCreate",
    "OperationalStudyArchive",
    "OperationalStudyCreate",
    "OperationalStudyResponse",
    "OperationalStudyStatusChange",
    "OperationalStudyUpdate",
    "ReadinessCriterionCreate",
    "StudyPlanCreate",
]


class StudyPlanResponse(BaseSchema):
    id: UUID
    study_id: UUID
    title: str
    objective: str | None
    planning_scope: dict[str, Any]
    owner_id: UUID | None
    status: str
    correlation_id: UUID
    created_by: UUID
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime


class EnrollmentPlanResponse(BaseSchema):
    id: UUID
    study_id: UUID
    title: str
    target_quantity: int | None
    planning_period_start: datetime | None
    planning_period_end: datetime | None
    planning_scope: dict[str, Any]
    owner_id: UUID | None
    status: str
    correlation_id: UUID
    created_by: UUID
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ReadinessCriterionResponse(BaseSchema):
    id: UUID
    study_id: UUID
    name: str
    description: str | None
    status: str
    required: bool
    due_at: datetime | None
    completed_at: datetime | None
    completed_by: UUID | None
    evidence_reference: str | None
    correlation_id: UUID
    created_by: UUID
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime


class StudyOperationalMilestoneResponse(BaseSchema):
    id: UUID
    study_id: UUID
    title: str
    milestone_type: str
    planned_at: datetime | None
    completed_at: datetime | None
    owner_id: UUID | None
    notes: str | None
    status: str
    correlation_id: UUID
    created_by: UUID
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime
