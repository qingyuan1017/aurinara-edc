"""Public contracts for the completed CTMS portfolio workspaces."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.schemas.shared.base import BaseCreateSchema, BaseSchema, UtcDatetime


class PortfolioSummary(BaseSchema):
    studies: int = 0
    sites: int = 0
    open_work: int = 0
    overdue_work: int = 0
    open_findings: int = 0
    overdue_visits: int = 0
    active_feasibility: int = 0
    open_capas: int = 0
    overloaded_cras: int = 0
    financials_by_currency: list[dict[str, Any]] = Field(default_factory=list)


class PortfolioStudyRow(BaseSchema):
    study_id: UUID
    study_code: str
    study_title: str
    status: str
    site_count: int = 0
    open_work: int = 0
    overdue_work: int = 0
    overdue_visits: int = 0
    open_findings: int = 0
    open_capas: int = 0
    performance_score: Decimal | None = None
    financials_by_currency: list[dict[str, Any]] = Field(default_factory=list)
    destination_path: str


class PortfolioWorkRow(BaseSchema):
    source_type: str
    source_id: UUID
    study_id: UUID
    study_code: str
    study_title: str
    site_id: UUID | None = None
    site_label: str | None = None
    title: str
    owner_id: UUID | None = None
    owner_name: str | None = None
    status: str
    priority: str | None = None
    due_at: UtcDatetime | None = None
    is_overdue: bool = False
    destination_path: str
    permitted_actions: list[str] = Field(default_factory=list)


class FeasibilityCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    study_id: UUID
    site_id: UUID
    owner_id: UUID | None = None
    questionnaire_version_id: UUID | None = None
    criteria: list[dict[str, Any]] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=4000)


class FeasibilityUpdate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    owner_id: UUID | None = None
    responses: dict[str, Any] | None = None
    score: Decimal | None = Field(default=None, ge=0, le=100)
    recommendation: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=4000)
    expected_version: int


class LifecycleTransition(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value


class FeasibilityResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID
    owner_id: UUID | None
    questionnaire_version_id: UUID | None
    status: str
    criteria_json: list[dict[str, Any]]
    responses_json: dict[str, Any]
    score: Decimal | None
    recommendation: str | None
    decision_reason: str | None
    notes: str | None
    sent_at: UtcDatetime | None
    responded_at: UtcDatetime | None
    decided_at: UtcDatetime | None
    version: int
    created_at: UtcDatetime
    updated_at: UtcDatetime


class FeasibilityPortfolioRow(FeasibilityResponse):
    study_code: str
    study_title: str
    site_number: str
    site_name: str
    owner_name: str | None = None
    destination_path: str


class SitePerformanceRow(BaseSchema):
    study_id: UUID
    study_code: str
    study_title: str
    site_id: UUID
    site_number: str
    site_name: str
    scorecard_id: UUID | None = None
    scorecard_version: int | None = None
    overall_score: Decimal | None = None
    coverage_percent: Decimal | None = None
    component_scores: dict[str, Any] = Field(default_factory=dict)
    component_sources: dict[str, Any] = Field(default_factory=dict)
    snapshot_date: date | None = None
    destination_path: str


class ScorecardCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    weights: dict[str, int]
    thresholds: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_weights(self):
        expected = {
            "startup_timeliness",
            "enrollment_attainment",
            "monitoring_timeliness",
            "finding_aging",
            "task_timeliness",
            "data_quality",
        }
        if set(self.weights) != expected or any(value < 0 for value in self.weights.values()):
            raise ValueError("weights must define every supported non-negative component")
        if sum(self.weights.values()) != 100:
            raise ValueError("scorecard weights must total 100")
        return self


class ScorecardResponse(BaseSchema):
    id: UUID
    name: str
    version_number: int
    status: str
    weights_json: dict[str, int]
    thresholds_json: dict[str, Any]
    published_at: UtcDatetime | None
    created_at: UtcDatetime


class CAPACreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    study_id: UUID
    site_id: UUID | None = None
    source_type: Literal[
        "monitoring_finding", "operational_task", "activation_blocker", "monitoring_issue"
    ]
    source_id: UUID
    title: str = Field(min_length=1, max_length=255)
    owner_id: UUID | None = None
    due_date: datetime | None = None


class CAPAUpdate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    owner_id: UUID | None = None
    root_cause: str | None = Field(default=None, max_length=10000)
    corrective_actions: list[dict[str, Any]] | None = None
    preventive_actions: list[dict[str, Any]] | None = None
    evidence_references: list[dict[str, Any]] | None = None
    effectiveness_criteria: str | None = Field(default=None, max_length=10000)
    effectiveness_result: str | None = Field(default=None, max_length=10000)
    due_date: datetime | None = None
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int


class CAPAResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID | None
    source_type: str
    source_id: UUID
    title: str
    owner_id: UUID | None
    status: str
    root_cause: str | None
    corrective_actions_json: list[dict[str, Any]]
    preventive_actions_json: list[dict[str, Any]]
    evidence_references_json: list[dict[str, Any]]
    effectiveness_criteria: str | None
    effectiveness_result: str | None
    due_date: UtcDatetime | None
    closed_at: UtcDatetime | None
    closure_reason: str | None
    version: int
    created_at: UtcDatetime
    updated_at: UtcDatetime


class CAPAPortfolioRow(CAPAResponse):
    study_code: str
    study_title: str
    site_label: str | None = None
    owner_name: str | None = None
    is_overdue: bool = False
    destination_path: str


class OperationalTemplateCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    template_type: Literal[
        "study_startup",
        "site_startup",
        "feasibility_questionnaire",
        "monitoring_checklist",
        "operational_task_pack",
    ]
    description: str | None = Field(default=None, max_length=4000)
    content: dict[str, Any] = Field(default_factory=dict)


class TemplateVersionCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    content: dict[str, Any]


class TemplateResponse(BaseSchema):
    id: UUID
    name: str
    template_type: str
    description: str | None
    retired_at: UtcDatetime | None
    version_id: UUID | None = None
    version_number: int | None = None
    version_status: str | None = None
    content: dict[str, Any] = Field(default_factory=dict)
    created_at: UtcDatetime


class TemplateApplyRequest(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    study_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=255)
    preview_only: bool = False


class TemplateApplicationResponse(BaseSchema):
    application_id: UUID | None = None
    template_version_id: UUID
    study_id: UUID
    preview: bool
    result: dict[str, Any]


class WorkflowRuleCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    trigger_type: Literal[
        "task_due",
        "task_overdue",
        "monitoring_overdue",
        "finding_severity",
        "site_activation_delay",
        "contract_expiration",
        "invoice_overdue",
        "capa_due",
        "capacity_overload",
    ]
    conditions: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(min_length=1)


class WorkflowRuleVersionCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    trigger_type: Literal[
        "task_due",
        "task_overdue",
        "monitoring_overdue",
        "finding_severity",
        "site_activation_delay",
        "contract_expiration",
        "invoice_overdue",
        "capa_due",
        "capacity_overload",
    ]
    conditions: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(min_length=1)


class WorkflowRuleResponse(BaseSchema):
    id: UUID
    name: str
    description: str | None
    version_id: UUID
    version_number: int
    status: str
    trigger_type: str
    conditions: dict[str, Any]
    actions: list[dict[str, Any]]
    created_at: UtcDatetime


class WorkflowDryRunRequest(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    sample: dict[str, Any] = Field(default_factory=dict)


class CRAAssignmentCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    study_id: UUID
    site_id: UUID | None = None
    role: Literal["Primary", "Backup"] = "Primary"
    planned_hours_per_week: Decimal = Field(ge=0, le=168)
    effective_from: date
    effective_to: date | None = None
    allow_over_capacity: bool = False
    over_capacity_reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def valid_dates_and_override(self):
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")
        if self.allow_over_capacity and not (self.over_capacity_reason or "").strip():
            raise ValueError("over_capacity_reason is required for an override")
        return self


class CRAAssignmentResponse(BaseSchema):
    id: UUID
    user_id: UUID
    user_name: str | None = None
    study_id: UUID
    study_code: str | None = None
    site_id: UUID | None
    site_label: str | None = None
    role: str
    planned_hours_per_week: Decimal
    effective_from: date
    effective_to: date | None
    active: bool
    over_capacity_reason: str | None
    created_at: UtcDatetime


class CapacityPlanCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    week_start: date
    capacity_hours: Decimal = Field(gt=0, le=168)
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("week_start")
    @classmethod
    def monday_only(cls, value: date) -> date:
        if value.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        return value


class AvailabilityExceptionCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    exception_date: date
    exception_type: Literal["Leave", "Holiday", "Training", "Other"]
    unavailable_hours: Decimal = Field(gt=0, le=24)
    reason: str = Field(min_length=1, max_length=2000)


class CapacityUtilizationRow(BaseSchema):
    user_id: UUID
    user_name: str
    week_start: date
    timezone: str
    capacity_hours: Decimal
    exception_hours: Decimal
    available_hours: Decimal
    allocated_hours: Decimal
    utilization_percent: Decimal
    upcoming_visits: int = 0
    overdue_visits: int = 0
    is_over_capacity: bool


class IssueRow(BaseSchema):
    source_type: str
    source_id: UUID
    study_id: UUID
    study_code: str
    study_title: str
    site_id: UUID | None = None
    site_label: str | None = None
    title: str
    severity: str | None = None
    status: str
    owner_id: UUID | None = None
    due_at: UtcDatetime | None = None
    is_overdue: bool = False
    capa_id: UUID | None = None
    destination_path: str


class EscalationRow(BaseSchema):
    id: UUID
    task_id: UUID
    study_id: UUID
    study_code: str
    study_title: str
    site_id: UUID | None = None
    task_title: str
    owner_id: UUID | None = None
    owner_name: str | None = None
    status: str
    reason: str
    deadline: UtcDatetime | None = None
    is_overdue: bool = False
    destination_path: str


__all__ = [name for name in globals() if not name.startswith("_")]
