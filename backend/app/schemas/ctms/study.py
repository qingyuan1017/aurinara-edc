"""Pydantic contracts for CTMS operational study workflows."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.models.ctms.operational_study import (
    OperationalMilestoneStatus,
    OperationalStudyStatus,
    ProjectScopeLevel,
    StudyPlanStatus,
)
from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    BaseUpdateSchema,
    UtcDatetime,
)


def _reason(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("reason must not be blank")
    return value


def _not_blank(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value must not be blank")
    return value


class OperationalStudyCreate(BaseCreateSchema):
    """CTMS-owned profile fields; ``study_id`` is a canonical EDC reference."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="forbid")

    phase: str = Field(min_length=1, max_length=50)
    study_type: str = Field(min_length=1, max_length=100)
    main_purpose: str = Field(min_length=1, max_length=100)
    therapeutic_area: str | None = Field(default=None, max_length=255)
    program: str | None = Field(default=None, max_length=255)
    indication: str | None = Field(default=None, max_length=255)
    study_description: str | None = None
    investigational_product: str | None = Field(default=None, max_length=500)
    blind_method: str = Field(min_length=1, max_length=100)
    randomized: bool
    expected_subject_count: int = Field(ge=0)
    language: str = Field(min_length=1, max_length=50)
    expected_site_count: int = Field(ge=0)
    construction_period: str = Field(min_length=1, max_length=100)
    planned_start_date: date
    planned_end_date: date
    actual_start_date: date | None = None
    actual_end_date: date | None = None
    study_currency: str = Field(min_length=3, max_length=3)
    exchange_date: date | None = None
    query_expected_days: int | None = Field(default=None, ge=0)
    operational_owner_id: UUID | None = None
    planning_metadata: dict[str, Any] = Field(default_factory=dict)
    readiness_criteria: dict[str, Any] = Field(default_factory=dict)
    status: OperationalStudyStatus = OperationalStudyStatus.DRAFT
    correlation_id: str | None = None

    @field_validator("study_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        if not value.isalpha():
            raise ValueError("study_currency must be a three-letter currency code")
        return value.upper()

    @model_validator(mode="after")
    def validate_dates(self):
        if self.planned_end_date < self.planned_start_date:
            raise ValueError("planned_end_date must be on or after planned_start_date")
        if (
            self.actual_start_date
            and self.actual_end_date
            and self.actual_end_date < self.actual_start_date
        ):
            raise ValueError("actual_end_date must be on or after actual_start_date")
        return self


class OperationalStudyUpdate(BaseUpdateSchema):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="forbid")

    phase: str | None = Field(default=None, min_length=1, max_length=50)
    study_type: str | None = Field(default=None, min_length=1, max_length=100)
    main_purpose: str | None = Field(default=None, min_length=1, max_length=100)
    therapeutic_area: str | None = Field(default=None, max_length=255)
    program: str | None = Field(default=None, max_length=255)
    indication: str | None = Field(default=None, max_length=255)
    study_description: str | None = None
    investigational_product: str | None = Field(default=None, max_length=500)
    blind_method: str | None = Field(default=None, min_length=1, max_length=100)
    randomized: bool | None = None
    expected_subject_count: int | None = Field(default=None, ge=0)
    language: str | None = Field(default=None, min_length=1, max_length=50)
    expected_site_count: int | None = Field(default=None, ge=0)
    construction_period: str | None = Field(default=None, min_length=1, max_length=100)
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    actual_start_date: date | None = None
    actual_end_date: date | None = None
    study_currency: str | None = Field(default=None, min_length=3, max_length=3)
    exchange_date: date | None = None
    query_expected_days: int | None = Field(default=None, ge=0)
    operational_owner_id: UUID | None = None
    planning_metadata: dict[str, Any] | None = None
    readiness_criteria: dict[str, Any] | None = None
    correlation_id: str | None = None

    @field_validator("study_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.isalpha():
            raise ValueError("study_currency must be a three-letter currency code")
        return value.upper()


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
    milestone_id: UUID | None = None
    scope_level: ProjectScopeLevel = ProjectScopeLevel.STUDY
    country_code: str | None = Field(default=None, max_length=100)
    site_id: UUID | None = None
    planning_scope: dict[str, Any] = Field(default_factory=dict)
    owner_id: UUID | None = None
    assignee_role_id: UUID | None = None
    assignee_user_id: UUID | None = None
    start_at: datetime | date | None = None
    due_at: datetime | date | None = None
    status: str = Field(default=StudyPlanStatus.DRAFT.value, min_length=1, max_length=100)
    correlation_id: str | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_at and self.due_at and self.due_at < self.start_at:
            raise ValueError("due_at must be on or after start_at")
        return self

    _validate_status = field_validator("status")(_not_blank)


class StudyPlanUpdate(BaseUpdateSchema):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    objective: str | None = None
    milestone_id: UUID | None = None
    scope_level: ProjectScopeLevel | None = None
    country_code: str | None = Field(default=None, max_length=100)
    site_id: UUID | None = None
    assignee_role_id: UUID | None = None
    assignee_user_id: UUID | None = None
    start_at: datetime | date | None = None
    due_at: datetime | date | None = None
    status: str | None = Field(default=None, min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        return _not_blank(value) if value is not None else None


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
    description: str | None = None
    milestone_type: str = Field(min_length=1, max_length=100)
    scope_level: ProjectScopeLevel = ProjectScopeLevel.STUDY
    country_code: str | None = Field(default=None, max_length=100)
    site_id: UUID | None = None
    planned_at: datetime | date | None = None
    owner_id: UUID | None = None
    notes: str | None = None
    status: OperationalMilestoneStatus = OperationalMilestoneStatus.PLANNED
    correlation_id: str | None = None


class OperationalMilestoneUpdate(BaseUpdateSchema):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    milestone_type: str | None = Field(default=None, min_length=1, max_length=100)
    scope_level: ProjectScopeLevel | None = None
    country_code: str | None = Field(default=None, max_length=100)
    site_id: UUID | None = None
    planned_at: datetime | date | None = None
    completed_at: datetime | date | None = None
    owner_id: UUID | None = None
    notes: str | None = None
    status: OperationalMilestoneStatus | None = None
    reason: str = Field(min_length=1, max_length=500)


class OperationalStudyResponse(BaseSchema):
    id: UUID
    study_id: UUID
    operational_owner_id: UUID | None = None
    study_name: str
    sponsor: str | None = None
    phase: str | None = None
    study_type: str | None = None
    main_purpose: str | None = None
    therapeutic_area: str | None = None
    program: str | None = None
    indication: str | None = None
    study_description: str | None = None
    investigational_product: str | None = None
    blind_method: str | None = None
    randomized: bool | None = None
    expected_subject_count: int | None = None
    language: str | None = None
    expected_site_count: int | None = None
    construction_period: str | None = None
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    actual_start_date: date | None = None
    actual_end_date: date | None = None
    study_currency: str | None = None
    exchange_date: date | None = None
    query_expected_days: int | None = None
    planning_metadata: dict[str, Any]
    readiness_criteria: dict[str, Any]
    status: OperationalStudyStatus
    retention_state: str
    archived_at: UtcDatetime | None = None
    created_by: UUID
    updated_by: UUID | None = None
    correlation_id: UUID
    created_at: UtcDatetime
    updated_at: UtcDatetime


__all__ = [
    "EnrollmentPlanCreate",
    "OperationalMilestoneCreate",
    "OperationalMilestoneUpdate",
    "OperationalStudyArchive",
    "OperationalStudyCreate",
    "OperationalStudyResponse",
    "OperationalStudyStatusChange",
    "OperationalStudyUpdate",
    "ProjectManagementOptionsResponse",
    "ProjectOption",
    "ReadinessCriterionCreate",
    "StudyOperationalMilestoneResponse",
    "StudyPlanCreate",
    "StudyPlanResponse",
    "StudyPlanUpdate",
]


class StudyPlanResponse(BaseSchema):
    id: UUID
    study_id: UUID
    title: str
    objective: str | None
    milestone_id: UUID | None = None
    scope_level: ProjectScopeLevel
    country_code: str | None = None
    site_id: UUID | None = None
    planning_scope: dict[str, Any]
    owner_id: UUID | None
    assignee_role_id: UUID | None = None
    assignee_user_id: UUID | None = None
    start_at: UtcDatetime | None = None
    due_at: UtcDatetime | None = None
    status: str
    correlation_id: UUID
    created_by: UUID
    updated_by: UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class EnrollmentPlanResponse(BaseSchema):
    id: UUID
    study_id: UUID
    title: str
    target_quantity: int | None
    planning_period_start: UtcDatetime | None
    planning_period_end: UtcDatetime | None
    planning_scope: dict[str, Any]
    owner_id: UUID | None
    status: str
    correlation_id: UUID
    created_by: UUID
    updated_by: UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ReadinessCriterionResponse(BaseSchema):
    id: UUID
    study_id: UUID
    name: str
    description: str | None
    status: str
    required: bool
    due_at: UtcDatetime | None
    completed_at: UtcDatetime | None
    completed_by: UUID | None
    evidence_reference: str | None
    correlation_id: UUID
    created_by: UUID
    updated_by: UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class StudyOperationalMilestoneResponse(BaseSchema):
    id: UUID
    study_id: UUID
    title: str
    description: str | None = None
    milestone_type: str
    scope_level: ProjectScopeLevel
    country_code: str | None = None
    site_id: UUID | None = None
    planned_at: UtcDatetime | None
    completed_at: UtcDatetime | None
    owner_id: UUID | None
    notes: str | None
    status: str
    correlation_id: UUID
    created_by: UUID
    updated_by: UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ProjectOption(BaseSchema):
    id: UUID
    label: str
    secondary_label: str | None = None
    country_code: str | None = None


class ProjectManagementOptionsResponse(BaseSchema):
    users: list[ProjectOption]
    roles: list[ProjectOption]
    sites: list[ProjectOption]
