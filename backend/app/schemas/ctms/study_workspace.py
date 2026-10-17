"""Public contracts for completed CTMS study workspaces."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from app.schemas.shared.base import BaseCreateSchema, BaseSchema, BaseUpdateSchema, UtcDatetime


class StudySummary(BaseSchema):
    study_id: UUID
    site_count: int = 0
    active_sites: int = 0
    enrollment: dict[str, Any] = Field(default_factory=dict)
    monitoring: dict[str, Any] = Field(default_factory=dict)
    work: dict[str, Any] = Field(default_factory=dict)
    capas: dict[str, Any] = Field(default_factory=dict)
    contracts: dict[str, Any] = Field(default_factory=dict)
    financials_by_currency: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: UtcDatetime


class HealthSignal(BaseSchema):
    dimension: str
    status: Literal["Green", "Amber", "Red", "Unknown"]
    summary: str
    factors: list[dict[str, Any]] = Field(default_factory=list)
    source_date: UtcDatetime | None = None
    destination_path: str


class ActivityRow(BaseSchema):
    id: UUID
    timestamp: UtcDatetime
    actor_id: UUID | None = None
    actor_name: str | None = None
    entity_type: str
    entity_id: UUID
    action: str
    description: str
    site_id: UUID | None = None
    destination_path: str
    permitted_actions: list[str] = Field(default_factory=lambda: ["open"])


class TeamAssignmentCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    site_id: UUID | None = None
    user_id: UUID | None = None
    staff_entity_id: UUID | None = None
    organization_id: UUID | None = None
    role: str = Field(min_length=1, max_length=100)
    assignment_type: Literal["Primary", "Backup"] = "Primary"
    responsibilities: str | None = Field(default=None, max_length=4000)
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def valid_identity_and_dates(self):
        if (self.user_id is None) == (self.staff_entity_id is None):
            raise ValueError("Exactly one of user_id or staff_entity_id is required")
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")
        return self


class TeamAssignmentUpdate(BaseUpdateSchema):
    model_config = ConfigDict(extra="forbid")
    role: str | None = Field(default=None, min_length=1, max_length=100)
    assignment_type: Literal["Primary", "Backup"] | None = None
    responsibilities: str | None = Field(default=None, max_length=4000)
    effective_from: date | None = None
    effective_to: date | None = None
    active: bool | None = None
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=1)


class TeamAssignmentResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID | None
    user_id: UUID | None
    staff_entity_id: UUID | None
    organization_id: UUID | None
    display_name: str
    role: str
    assignment_type: str
    responsibilities: str | None
    effective_from: date
    effective_to: date | None
    active: bool
    version: int
    created_at: UtcDatetime
    destination_path: str
    permitted_actions: list[str] = Field(default_factory=lambda: ["open", "update"])


class TransitionRequest(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int | None = Field(default=None, ge=1)


class AmendmentCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    amendment_number: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    source_module: Literal["PLATFORM", "EDC"] = "PLATFORM"
    source_reference_id: UUID
    source_version: str | None = Field(default=None, max_length=100)
    owner_id: UUID | None = None
    effective_date: date | None = None
    due_date: date | None = None
    summary: str | None = Field(default=None, max_length=4000)


class AmendmentImpactCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")
    site_id: UUID | None = None
    impact_area: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=4000)
    owner_id: UUID | None = None
    due_date: date | None = None


class AmendmentResponse(BaseSchema):
    id: UUID
    study_id: UUID
    amendment_number: str
    title: str
    source_module: str
    source_reference_id: UUID
    source_version: str | None
    owner_id: UUID | None
    effective_date: date | None
    due_date: date | None
    status: str
    summary: str | None
    version: int
    created_at: UtcDatetime
    destination_path: str
    permitted_actions: list[str] = Field(default_factory=lambda: ["open", "transition"])


class CloseoutCreate(BaseCreateSchema):
    site_id: UUID
    owner_id: UUID | None = None
    planned_date: date | None = None


class CloseoutItemCreate(BaseCreateSchema):
    item_type: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    required: bool = True
    due_date: date | None = None


class CloseoutItemUpdate(BaseUpdateSchema):
    status: Literal["Open", "In Progress", "Completed", "Cancelled"] | None = None
    due_date: date | None = None
    evidence_references: list[dict[str, Any]] | None = None
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=1)


class CloseoutResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID
    site_label: str
    owner_id: UUID | None
    planned_date: date | None
    status: str
    required_items: int = 0
    completed_required_items: int = 0
    blockers: list[str] = Field(default_factory=list)
    version: int
    created_at: UtcDatetime
    destination_path: str
    permitted_actions: list[str] = Field(default_factory=lambda: ["open", "transition"])


class RiskAssessmentCreate(BaseCreateSchema):
    name: str = Field(min_length=1, max_length=255)
    owner_id: UUID | None = None
    rationale: str | None = Field(default=None, max_length=4000)


class RiskItemCreate(BaseCreateSchema):
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=4000)
    probability: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    detectability: int = Field(ge=1, le=5)
    mitigation: str | None = Field(default=None, max_length=4000)
    owner_id: UUID | None = None


class RiskAssessmentVersionCreate(BaseCreateSchema):
    rationale: str | None = Field(default=None, max_length=4000)
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=1)


class RiskAssessmentResponse(BaseSchema):
    id: UUID
    study_id: UUID
    name: str
    owner_id: UUID | None
    current_version: int
    status: str
    version: int
    risk_item_count: int = 0
    highest_risk_score: int | None = None
    created_at: UtcDatetime
    destination_path: str
    permitted_actions: list[str] = Field(default_factory=lambda: ["open", "transition"])


class KRICreate(BaseCreateSchema):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    owner_id: UUID | None = None
    source_type: Literal["ctms_operational", "approved_edc_projection"]
    unit: str | None = Field(default=None, max_length=50)
    amber_threshold: Decimal
    red_threshold: Decimal
    direction: Literal["above", "below"] = "above"

    @model_validator(mode="after")
    def valid_threshold_order(self):
        if self.direction == "above" and self.red_threshold < self.amber_threshold:
            raise ValueError("red_threshold must be at or above amber_threshold")
        if self.direction == "below" and self.red_threshold > self.amber_threshold:
            raise ValueError("red_threshold must be at or below amber_threshold")
        return self


class KRIObservationCreate(BaseCreateSchema):
    site_id: UUID | None = None
    observed_at: datetime
    value: Decimal
    source_date: datetime
    source_reference_id: UUID | None = None


class KRIVersionCreate(BaseCreateSchema):
    source_type: Literal["ctms_operational", "approved_edc_projection"]
    unit: str | None = Field(default=None, max_length=50)
    amber_threshold: Decimal
    red_threshold: Decimal
    direction: Literal["above", "below"] = "above"
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def valid_threshold_order(self):
        if self.direction == "above" and self.red_threshold < self.amber_threshold:
            raise ValueError("red_threshold must be at or above amber_threshold")
        if self.direction == "below" and self.red_threshold > self.amber_threshold:
            raise ValueError("red_threshold must be at or below amber_threshold")
        return self


class KRIResponse(BaseSchema):
    id: UUID
    study_id: UUID
    code: str
    name: str
    owner_id: UUID | None
    current_version: int
    status: str
    latest_value: Decimal | None = None
    latest_level: str | None = None
    latest_observed_at: UtcDatetime | None = None
    version: int
    created_at: UtcDatetime
    destination_path: str
    permitted_actions: list[str] = Field(default_factory=lambda: ["open", "transition"])


class ProtocolDeviationCreate(BaseCreateSchema):
    site_id: UUID | None = None
    projection_id: UUID
    source_record_id: UUID
    approved_reference: str = Field(min_length=1, max_length=255)
    classification: str | None = Field(default=None, max_length=100)
    severity: str | None = Field(default=None, max_length=30)
    owner_id: UUID | None = None
    due_date: date | None = None
    action_summary: str | None = Field(default=None, max_length=4000)


class ProtocolDeviationResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID | None
    projection_id: UUID | None
    source_record_id: UUID | None
    approved_reference: str
    classification: str | None
    severity: str | None
    owner_id: UUID | None
    due_date: date | None
    status: str
    action_summary: str | None
    version: int
    created_at: UtcDatetime
    destination_path: str
    permitted_actions: list[str] = Field(default_factory=lambda: ["open", "transition"])


class ICFVersionCreate(BaseCreateSchema):
    version_code: str = Field(min_length=1, max_length=100)
    country_code: str | None = Field(default=None, min_length=2, max_length=3)
    source_reference: str = Field(min_length=1, max_length=500)
    approved_date: date
    effective_date: date | None = None


class ICFRolloutCreate(BaseCreateSchema):
    site_id: UUID
    owner_id: UUID | None = None


class ICFEvidenceUpdate(BaseUpdateSchema):
    evidence_references: list[dict[str, Any]] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=1)


class ICFRolloutResponse(BaseSchema):
    id: UUID
    icf_version_id: UUID
    study_id: UUID
    site_id: UUID
    site_label: str
    version_code: str
    country_code: str | None
    owner_id: UUID | None
    status: str
    evidence_references: list[dict[str, Any]]
    version: int
    created_at: UtcDatetime
    destination_path: str
    permitted_actions: list[str] = Field(default_factory=lambda: ["open", "transition"])


def _validate_tracking_columns(columns: list[dict[str, Any]]) -> None:
    allowed_types = {"string", "number", "integer", "boolean", "date", "datetime"}
    keys: list[str] = []
    for column in columns:
        key = str(column.get("key") or "").strip()
        label = str(column.get("label") or "").strip()
        data_type = str(column.get("type") or "").strip().lower()
        if not key or not label or data_type not in allowed_types:
            raise ValueError("Each tracking column requires key, label, and a supported type")
        keys.append(key)
    if len(keys) != len(set(keys)):
        raise ValueError("Tracking column keys must be unique")


class TrackingDefinitionCreate(BaseCreateSchema):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    columns: list[dict[str, Any]] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_columns(self):
        _validate_tracking_columns(self.columns)
        return self


class TrackingDefinitionVersionCreate(BaseCreateSchema):
    columns: list[dict[str, Any]] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def valid_columns(self):
        _validate_tracking_columns(self.columns)
        return self


class TrackingLogCreate(BaseCreateSchema):
    definition_version_id: UUID
    name: str = Field(min_length=1, max_length=255)
    owner_id: UUID | None = None


class TrackingEntryCreate(BaseCreateSchema):
    site_id: UUID | None = None
    row_key: str = Field(min_length=1, max_length=100)
    values: dict[str, Any]


class TrackingEntryRevisionCreate(BaseCreateSchema):
    values: dict[str, Any]
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=1)


class TaskDependencyCreate(BaseCreateSchema):
    depends_on_task_id: UUID
    reason: str | None = Field(default=None, max_length=2000)


class TaskEscalationCreate(BaseCreateSchema):
    owner_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=2000)
    deadline: datetime | None = None


class TaskEscalationTransition(BaseCreateSchema):
    status: Literal["Acknowledged", "Resolved", "Cancelled"]
    reason: str = Field(min_length=1, max_length=2000)


class TrackingLogResponse(BaseSchema):
    id: UUID
    study_id: UUID
    definition_version_id: UUID
    name: str
    owner_id: UUID | None
    status: str
    entry_count: int = 0
    version: int
    created_at: UtcDatetime
    destination_path: str
    permitted_actions: list[str] = Field(default_factory=lambda: ["open"])


class ActionIssueRow(BaseSchema):
    source_type: str
    source_id: UUID
    study_id: UUID
    site_id: UUID | None = None
    title: str
    status: str
    severity: str | None = None
    owner_id: UUID | None = None
    due_at: UtcDatetime | None = None
    is_overdue: bool = False
    permitted_actions: list[str] = Field(default_factory=list)
    destination_path: str


class SiteStudyRow(BaseSchema):
    site_id: UUID
    site_number: str
    site_name: str
    country: str | None = None
    region: str | None = None
    operational_status: str | None = None
    planned_activation_date: UtcDatetime | None = None
    open_activation_actions: int = 0
    performance_score: Decimal | None = None
    destination_path: str
    permitted_actions: list[str] = Field(default_factory=lambda: ["open", "update"])


__all__ = [
    name
    for name in globals()
    if name.endswith(("Create", "Update", "Response", "Row", "Request", "Signal", "Summary"))
]
