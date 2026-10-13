"""Pydantic v2 contracts for CTMS monitoring plans and activities."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.core.ctms import ensure_utc
from app.models.ctms.monitoring import (
    MonitoringActivityStatus,
    MonitoringActivityType,
    MonitoringChecklistResult,
    MonitoringFindingSeverity,
    MonitoringFindingStatus,
    MonitoringPlanStatus,
    MonitoringPlanVersionStatus,
    MonitoringReportStatus,
    MonitoringVisitModality,
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


class MonitoringRuleCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    visit_type: MonitoringActivityType
    frequency_value: int | None = Field(default=None, ge=1)
    frequency_unit: str | None = Field(default=None, max_length=30)
    trigger: str | None = None
    allowed_modalities: list[MonitoringVisitModality] = Field(default_factory=list)
    expected_duration_hours: int | None = Field(default=None, ge=1)
    required_activities: list[str] = Field(default_factory=list)
    report_due_days: int = Field(default=10, ge=0, le=365)
    sort_order: int = Field(default=0, ge=0)


class MonitoringRuleResponse(BaseSchema):
    id: UUID
    plan_version_id: UUID
    visit_type: MonitoringActivityType
    frequency_value: int | None
    frequency_unit: str | None
    trigger: str | None
    allowed_modalities: list[Any]
    expected_duration_hours: int | None
    required_activities: list[Any]
    report_due_days: int
    sort_order: int
    created_at: UtcDatetime


class MonitoringPlanVersionCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    objectives: str | None = None
    activity_types: list[MonitoringActivityType] = Field(default_factory=list)
    frequency: str | None = None
    frequency_value: int | None = Field(default=None, ge=1)
    frequency_unit: str | None = None
    cadence: str | None = None
    responsibilities: dict[str, Any] = Field(default_factory=dict)
    scope: dict[str, Any] = Field(default_factory=dict)
    completion_criteria: str | None = None
    risk_level: str | None = None
    risk_strategy: str | None = None
    monitoring_strategy: str | None = None
    risk_threshold: str | None = None
    thresholds: dict[str, Any] = Field(default_factory=dict)
    visit_rules: list[MonitoringRuleCreate] = Field(default_factory=list)


class MonitoringPlanCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    site_id: UUID | None = None
    version: MonitoringPlanVersionCreate | None = None
    correlation_id: str | None = None


class MonitoringPlanUpdate(BaseUpdateSchema):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    correlation_id: str | None = None


class MonitoringPlanAmend(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    reason: str
    changes: MonitoringPlanVersionCreate = Field(default_factory=MonitoringPlanVersionCreate)
    correlation_id: str | None = None

    _validate_reason = field_validator("reason")(_reason)


class MonitoringPlanResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID | None
    name: str
    description: str | None
    status: MonitoringPlanStatus
    current_version_id: UUID | None
    retention_state: str
    correlation_id: str
    created_by: UUID
    updated_by: UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class MonitoringPlanVersionResponse(BaseSchema):
    id: UUID
    plan_id: UUID
    study_id: UUID
    site_id: UUID | None
    version_number: int
    status: MonitoringPlanVersionStatus
    objectives: str | None
    activity_types: list[Any]
    frequency: str | None
    frequency_value: int | None
    frequency_unit: str | None
    cadence: str | None
    responsibilities: dict[str, Any]
    scope: dict[str, Any]
    completion_criteria: str | None
    risk_level: str | None
    risk_strategy: str | None
    monitoring_strategy: str | None
    risk_threshold: str | None
    thresholds: dict[str, Any]
    amendment_reason: str | None
    published_by: UUID | None
    published_at: UtcDatetime | None
    correlation_id: str
    created_by: UUID
    updated_by: UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    rules: list[MonitoringRuleResponse] = Field(default_factory=list)


class MonitoringActivityCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    activity_type: MonitoringActivityType
    modality: MonitoringVisitModality = MonitoringVisitModality.ON_SITE
    planned_date: datetime | date
    site_id: UUID | None = None
    assigned_cra_id: UUID | None = None
    edc_visit_instance_id: UUID | None = None
    issue_id: UUID | None = None
    issue_reference: str | None = None
    escalation_id: UUID | None = None
    escalation_reference: str | None = None
    reason: str | None = None
    correlation_id: str | None = None

    @field_validator("planned_date")
    @classmethod
    def utc_planned_date(cls, value: datetime | date) -> datetime:
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
        return ensure_utc(value)


class MonitoringActivityReschedule(BaseCreateSchema):
    planned_date: datetime
    reason: str
    correlation_id: str | None = None

    @field_validator("planned_date")
    @classmethod
    def utc_planned_date(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    _validate_reason = field_validator("reason")(_reason)


class MonitoringActivityComplete(BaseCreateSchema):
    evidence: dict[str, Any] | str
    notes: str | None = None
    correlation_id: str | None = None


class MonitoringActivityCancel(BaseCreateSchema):
    reason: str
    correlation_id: str | None = None

    _validate_reason = field_validator("reason")(_reason)


class MonitoringActivityAssign(BaseCreateSchema):
    assigned_cra_id: UUID
    correlation_id: str | None = None


class MonitoringActivityResponse(BaseSchema):
    id: UUID
    plan_version_id: UUID
    study_id: UUID
    site_id: UUID | None
    activity_type: MonitoringActivityType
    visit_code: str | None
    modality: MonitoringVisitModality
    planned_date: UtcDatetime
    actual_start_at: UtcDatetime | None
    actual_end_at: UtcDatetime | None
    assigned_cra_id: UUID | None
    status: MonitoringActivityStatus
    edc_visit_instance_id: UUID | None
    completion_evidence: dict[str, Any]
    completion_notes: str | None
    completed_at: UtcDatetime | None
    completed_by: UUID | None
    cancellation_reason: str | None
    cancelled_at: UtcDatetime | None
    cancelled_by: UUID | None
    correlation_id: str
    created_by: UUID
    updated_by: UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class MonitoringVisitActivityCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    requirement_key: str = Field(min_length=1, max_length=100)
    requirement: str = Field(min_length=1)
    plan_reference: str | None = Field(default=None, max_length=255)
    sort_order: int = Field(default=0, ge=0)


class MonitoringVisitActivityUpdate(BaseUpdateSchema):
    model_config = ConfigDict(extra="forbid")

    result: MonitoringChecklistResult
    review_details: str | None = None
    observations: str | None = None
    subject_reference: str | None = Field(default=None, max_length=255)
    record_reference: str | None = Field(default=None, max_length=255)
    evidence_references: list[str] = Field(default_factory=list)


class MonitoringVisitActivityResponse(BaseSchema):
    id: UUID
    visit_id: UUID
    rule_id: UUID | None
    study_id: UUID
    site_id: UUID | None
    requirement_key: str
    requirement: str
    plan_reference: str | None
    result: MonitoringChecklistResult
    review_details: str | None
    observations: str | None
    subject_reference: str | None
    record_reference: str | None
    evidence_references: list[Any]
    completed_at: UtcDatetime | None
    completed_by: UUID | None
    sort_order: int
    created_at: UtcDatetime
    updated_at: UtcDatetime


class MonitoringReportCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any] = Field(default_factory=dict)


class MonitoringReportUpdate(BaseUpdateSchema):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any]


class MonitoringReportTransition(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    action: str
    comments: str | None = None
    document_reference: str | None = Field(default=None, max_length=500)


class MonitoringReportResponse(BaseSchema):
    id: UUID
    visit_id: UUID
    previous_report_id: UUID | None
    study_id: UUID
    site_id: UUID | None
    version_number: int
    status: MonitoringReportStatus
    content: dict[str, Any]
    reviewer_comments: str | None
    submitted_at: UtcDatetime | None
    submitted_by: UUID | None
    reviewed_at: UtcDatetime | None
    reviewed_by: UUID | None
    approved_at: UtcDatetime | None
    approved_by: UUID | None
    finalized_at: UtcDatetime | None
    finalized_by: UUID | None
    controlled_snapshot: dict[str, Any] | None
    document_reference: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class MonitoringFindingCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    site_id: UUID | None = None
    visit_id: UUID | None = None
    report_id: UUID | None = None
    category: str = Field(min_length=1, max_length=100)
    severity: MonitoringFindingSeverity
    description: str = Field(min_length=1)
    responsible_party: str | None = Field(default=None, max_length=255)
    owner_id: UUID | None = None
    due_date: datetime | date | None = None
    capa_required: bool = False
    capa_reference: str | None = Field(default=None, max_length=255)

    @field_validator("due_date")
    @classmethod
    def utc_due_date(cls, value: datetime | date | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
        return ensure_utc(value)


class MonitoringFindingTransition(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    status: MonitoringFindingStatus
    reason: str
    resolution: str | None = None

    _validate_reason = field_validator("reason")(_reason)


class MonitoringActionCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    owner_id: UUID | None = None
    responsible_party: str | None = Field(default=None, max_length=255)
    due_date: datetime | date | None = None

    @field_validator("due_date")
    @classmethod
    def utc_due_date(cls, value: datetime | date | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
        return ensure_utc(value)


class MonitoringActionComplete(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    evidence: dict[str, Any] | str


class MonitoringActionResponse(BaseSchema):
    id: UUID
    finding_id: UUID
    study_id: UUID
    site_id: UUID | None
    title: str
    description: str | None
    owner_id: UUID | None
    responsible_party: str | None
    due_date: UtcDatetime | None
    status: str
    completion_evidence: dict[str, Any]
    completed_at: UtcDatetime | None
    completed_by: UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class MonitoringFindingResponse(BaseSchema):
    id: UUID
    finding_code: str
    study_id: UUID
    site_id: UUID | None
    visit_id: UUID | None
    report_id: UUID | None
    category: str
    severity: MonitoringFindingSeverity
    description: str
    responsible_party: str | None
    owner_id: UUID | None
    due_date: UtcDatetime | None
    status: MonitoringFindingStatus
    capa_required: bool
    capa_reference: str | None
    resolution: str | None
    verified_by: UUID | None
    verified_at: UtcDatetime | None
    closed_at: UtcDatetime | None
    closure_reason: str | None
    actions: list[MonitoringActionResponse] = Field(default_factory=list)
    created_at: UtcDatetime
    updated_at: UtcDatetime


__all__ = [name for name in globals() if not name.startswith("_")]
