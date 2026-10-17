"""CTMS portfolio planning, quality, template, and resource persistence.

The records in this module are operational only.  Study, site, and user
columns always reference the platform's canonical identities.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy import (
    inspect as sqlalchemy_inspect,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSONBType = JSONB().with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    return datetime.now(UTC)


class FeasibilityStatus(enum.StrEnum):
    DRAFT = "Draft"
    QUESTIONNAIRE_SENT = "Questionnaire Sent"
    RESPONSE_RECEIVED = "Response Received"
    UNDER_REVIEW = "Under Review"
    SELECTED = "Selected"
    NOT_SELECTED = "Not Selected"
    WITHDRAWN = "Withdrawn"


class CAPAStatus(enum.StrEnum):
    DRAFT = "Draft"
    INVESTIGATION = "Investigation"
    ACTION_PLAN_APPROVED = "Action Plan Approved"
    IMPLEMENTATION = "Implementation"
    EFFECTIVENESS_REVIEW = "Effectiveness Review"
    CLOSED = "Closed"
    CANCELLED = "Cancelled"


class VersionStatus(enum.StrEnum):
    DRAFT = "Draft"
    PUBLISHED = "Published"
    RETIRED = "Retired"


class WorkflowStatus(enum.StrEnum):
    DRAFT = "Draft"
    PUBLISHED = "Published"
    PAUSED = "Paused"
    RETIRED = "Retired"


class SiteFeasibilityAssessment(Base):
    __tablename__ = "ctms_site_feasibility_assessments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    questionnaire_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ctms_operational_template_versions.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=FeasibilityStatus.DRAFT.value
    )
    criteria_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    responses_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    recommendation: Mapped[str | None] = mapped_column(String(50))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        Index("ix_ctms_feasibility_scope_status", "study_id", "site_id", "status"),
        Index("ix_ctms_feasibility_owner_status", "owner_id", "status"),
        UniqueConstraint("study_id", "site_id", name="uq_ctms_feasibility_study_site"),
    )


class SitePerformanceScorecard(Base):
    __tablename__ = "ctms_site_performance_scorecards"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VersionStatus.DRAFT.value
    )
    weights_json: Mapped[dict[str, int]] = mapped_column(JSONBType, nullable=False)
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        UniqueConstraint("name", "version_number", name="uq_ctms_scorecard_name_version"),
        Index("ix_ctms_scorecard_status", "status", "published_at"),
    )


class SitePerformanceSnapshot(Base):
    __tablename__ = "ctms_site_performance_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
    )
    scorecard_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_site_performance_scorecards.id", ondelete="RESTRICT"), nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    component_scores_json: Mapped[dict[str, Decimal | None]] = mapped_column(
        JSONBType, nullable=False
    )
    component_sources_json: Mapped[dict[str, Any]] = mapped_column(
        JSONBType, nullable=False, default=dict
    )
    overall_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    coverage_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    source_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        UniqueConstraint(
            "study_id",
            "site_id",
            "scorecard_id",
            "snapshot_date",
            name="uq_ctms_site_performance_snapshot",
        ),
        Index("ix_ctms_site_performance_scope_date", "study_id", "site_id", "snapshot_date"),
    )


class CorrectiveActionPlan(Base):
    __tablename__ = "ctms_corrective_action_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT")
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=CAPAStatus.DRAFT.value)
    root_cause: Mapped[str | None] = mapped_column(Text)
    corrective_actions_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    preventive_actions_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    evidence_references_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    effectiveness_criteria: Mapped[str | None] = mapped_column(Text)
    effectiveness_result: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closure_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        Index("ix_ctms_capa_scope_status", "study_id", "site_id", "status"),
        Index("ix_ctms_capa_owner_due", "owner_id", "due_date"),
        UniqueConstraint("source_type", "source_id", name="uq_ctms_capa_source"),
    )


class CAPATransition(Base):
    __tablename__ = "ctms_capa_transitions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    capa_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_corrective_action_plans.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str] = mapped_column(String(30), nullable=False)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (Index("ix_ctms_capa_transition_history", "capa_id", "created_at"),)


class OperationalTemplate(Base):
    __tablename__ = "ctms_operational_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_ctms_operational_template_type", "template_type", "name"),)


class OperationalTemplateVersion(Base):
    __tablename__ = "ctms_operational_template_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_operational_templates.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VersionStatus.DRAFT.value
    )
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        UniqueConstraint("template_id", "version_number", name="uq_ctms_template_version"),
        Index("ix_ctms_template_version_status", "template_id", "status"),
    )


class TemplateApplication(Base):
    __tablename__ = "ctms_template_applications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ctms_operational_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    applied_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        UniqueConstraint("study_id", "idempotency_key", name="uq_ctms_template_application_key"),
    )


class WorkflowRule(Base):
    __tablename__ = "ctms_workflow_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class WorkflowRuleVersion(Base):
    __tablename__ = "ctms_workflow_rule_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_workflow_rules.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WorkflowStatus.DRAFT.value
    )
    trigger_type: Mapped[str] = mapped_column(String(50), nullable=False)
    conditions_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    actions_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        UniqueConstraint("rule_id", "version_number", name="uq_ctms_workflow_rule_version"),
        Index("ix_ctms_workflow_trigger_status", "trigger_type", "status"),
    )


class WorkflowExecution(Base):
    __tablename__ = "ctms_workflow_executions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_workflow_rule_versions.id", ondelete="RESTRICT"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    occurrence_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Pending")
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "rule_version_id",
            "source_type",
            "source_id",
            "occurrence_key",
            name="uq_ctms_workflow_execution",
        ),
    )


class CRAAssignment(Base):
    __tablename__ = "ctms_cra_assignments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT")
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="Primary")
    planned_hours_per_week: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=0
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    over_capacity_reason: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        Index("ix_ctms_cra_assignment_scope", "study_id", "site_id", "active"),
        Index("ix_ctms_cra_assignment_user_dates", "user_id", "effective_from", "effective_to"),
    )


class CRACapacityPlan(Base):
    __tablename__ = "ctms_cra_capacity_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    capacity_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (UniqueConstraint("user_id", "week_start", name="uq_ctms_cra_capacity_week"),)


class CRAAvailabilityException(Base):
    __tablename__ = "ctms_cra_availability_exceptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    exception_date: Mapped[date] = mapped_column(Date, nullable=False)
    exception_type: Mapped[str] = mapped_column(String(30), nullable=False)
    unavailable_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (Index("ix_ctms_cra_exception_user_date", "user_id", "exception_date"),)


def _reject_published_update(target: Any, label: str) -> None:
    state = sqlalchemy_inspect(target)
    history = state.attrs.status.history
    publishing = bool(
        history.has_changes()
        and history.deleted
        and history.deleted[0] == VersionStatus.DRAFT.value
        and target.status == VersionStatus.PUBLISHED.value
    )
    if target.status == VersionStatus.PUBLISHED.value and not publishing:
        raise ValueError(f"Published {label} versions are immutable")


@event.listens_for(OperationalTemplateVersion, "before_update")
def _immutable_template_version(mapper, connection, target) -> None:
    _reject_published_update(target, "operational template")


@event.listens_for(SitePerformanceScorecard, "before_update")
def _immutable_scorecard(mapper, connection, target) -> None:
    _reject_published_update(target, "site performance scorecard")


@event.listens_for(WorkflowRuleVersion, "before_update")
def _immutable_workflow_version(mapper, connection, target) -> None:
    _reject_published_update(target, "workflow rule")


__all__ = [
    "CAPAStatus",
    "CAPATransition",
    "CRAAssignment",
    "CRAAvailabilityException",
    "CRACapacityPlan",
    "CorrectiveActionPlan",
    "FeasibilityStatus",
    "OperationalTemplate",
    "OperationalTemplateVersion",
    "SiteFeasibilityAssessment",
    "SitePerformanceScorecard",
    "SitePerformanceSnapshot",
    "TemplateApplication",
    "VersionStatus",
    "WorkflowExecution",
    "WorkflowRule",
    "WorkflowRuleVersion",
    "WorkflowStatus",
]
