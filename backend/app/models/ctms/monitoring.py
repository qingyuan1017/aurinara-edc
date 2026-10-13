"""CTMS monitoring plans, immutable versions, and operational activities.

Monitoring records are CTMS-owned operational data.  ``edc_visit_instance_id``
is an informational canonical EDC reference only; this module deliberately does
not copy protocol visit dates, windows, status, casebook, or clinical data.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.inspection import inspect as sqlalchemy_inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

JSONBType = JSONB().with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    """Return an aware UTC timestamp for monitoring records."""

    return datetime.now(UTC)


class MonitoringPlanStatus(enum.StrEnum):
    DRAFT = "Draft"
    PUBLISHED = "Published"
    ARCHIVED = "Archived"


class MonitoringPlanVersionStatus(enum.StrEnum):
    DRAFT = "Draft"
    PUBLISHED = "Published"
    RETIRED = "Retired"


class MonitoringActivityType(enum.StrEnum):
    SITE_QUALIFICATION = "Site Qualification"
    SITE_INITIATION = "Site Initiation"
    ROUTINE_MONITORING = "Routine Monitoring"
    CLOSE_OUT = "Close-out"
    REMOTE_REVIEW = "Remote Review"
    TRIGGERED_REVIEW = "Triggered Review"
    UNSCHEDULED = "Unscheduled"


class MonitoringVisitModality(enum.StrEnum):
    ON_SITE = "On-site"
    REMOTE = "Remote"
    HYBRID = "Hybrid"


class MonitoringChecklistResult(enum.StrEnum):
    PENDING = "Pending"
    COMPLETED = "Completed"
    NOT_COMPLETED = "Not Completed"
    NOT_APPLICABLE = "Not Applicable"


class MonitoringReportStatus(enum.StrEnum):
    DRAFT = "Draft"
    SUBMITTED = "Submitted"
    UNDER_REVIEW = "Under Review"
    REVISION_REQUIRED = "Revision Required"
    APPROVED = "Approved"
    FINALIZED = "Finalized"


class MonitoringFindingSeverity(enum.StrEnum):
    CRITICAL = "Critical"
    MAJOR = "Major"
    MINOR = "Minor"
    OBSERVATION = "Observation"


class MonitoringFindingStatus(enum.StrEnum):
    OPEN = "Open"
    ACTION_ASSIGNED = "Action Assigned"
    IN_PROGRESS = "In Progress"
    PENDING_VERIFICATION = "Pending Verification"
    CLOSED = "Closed"
    CANCELLED = "Cancelled"


class MonitoringActivityStatus(enum.StrEnum):
    PLANNED = "Planned"
    SCHEDULED = "Scheduled"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    RESCHEDULED = "Rescheduled"
    CANCELLED = "Cancelled"
    OVERDUE = "Overdue"


class _MonitoringRecord:
    """Common CTMS ownership, scope, traceability, and retention fields."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    retention_reason: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deletion_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class MonitoringPlan(Base, _MonitoringRecord):
    """Stable operational monitoring plan identity and current-version pointer."""

    __tablename__ = "ctms_monitoring_plans"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MonitoringPlanStatus.DRAFT.value
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("ctms_monitoring_plan_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    study = relationship("Study", lazy="selectin")
    site = relationship("Site", lazy="selectin")
    versions = relationship(
        "MonitoringPlanVersion",
        back_populates="plan",
        foreign_keys="MonitoringPlanVersion.plan_id",
        order_by="MonitoringPlanVersion.version_number",
        cascade="all, delete-orphan",
    )
    current_version = relationship(
        "MonitoringPlanVersion",
        foreign_keys=[current_version_id],
        post_update=True,
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_ctms_monitoring_plans_scope_status", "study_id", "site_id", "status"),
        Index("ix_ctms_monitoring_plans_current_version", "current_version_id"),
    )


class MonitoringPlanVersion(Base, _MonitoringRecord):
    """Versioned monitoring definition; a published row is append-only."""

    __tablename__ = "ctms_monitoring_plan_versions"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_monitoring_plans.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MonitoringPlanVersionStatus.DRAFT.value
    )
    objectives: Mapped[str | None] = mapped_column(Text)
    activity_types: Mapped[list[Any]] = mapped_column(JSONBType, nullable=False, default=list)
    frequency: Mapped[str | None] = mapped_column(String(100))
    frequency_value: Mapped[int | None] = mapped_column(Integer)
    frequency_unit: Mapped[str | None] = mapped_column(String(30))
    cadence: Mapped[str | None] = mapped_column(String(100))
    responsibilities: Mapped[dict[str, Any]] = mapped_column(
        JSONBType, nullable=False, default=dict
    )
    scope: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    completion_criteria: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(String(50))
    risk_strategy: Mapped[str | None] = mapped_column(String(255))
    monitoring_strategy: Mapped[str | None] = mapped_column(String(255))
    risk_threshold: Mapped[str | None] = mapped_column(String(255))
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    amendment_reason: Mapped[str | None] = mapped_column(Text)
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan = relationship(
        "MonitoringPlan", back_populates="versions", foreign_keys=[plan_id], lazy="selectin"
    )
    activities = relationship("MonitoringActivity", back_populates="plan_version", lazy="selectin")
    rules = relationship(
        "MonitoringRule",
        back_populates="plan_version",
        order_by="MonitoringRule.sort_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("uq_ctms_monitoring_plan_versions_number", "plan_id", "version_number", unique=True),
        Index("ix_ctms_monitoring_plan_versions_status", "plan_id", "status"),
        Index("ix_ctms_monitoring_plan_versions_published_at", "published_at"),
    )


class MonitoringRule(Base):
    """Structured visit requirement frozen with a monitoring-plan version."""

    __tablename__ = "ctms_monitoring_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ctms_monitoring_plan_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    visit_type: Mapped[str] = mapped_column(String(40), nullable=False)
    frequency_value: Mapped[int | None] = mapped_column(Integer)
    frequency_unit: Mapped[str | None] = mapped_column(String(30))
    trigger: Mapped[str | None] = mapped_column(Text)
    allowed_modalities: Mapped[list[Any]] = mapped_column(JSONBType, nullable=False, default=list)
    expected_duration_hours: Mapped[int | None] = mapped_column(Integer)
    required_activities: Mapped[list[Any]] = mapped_column(JSONBType, nullable=False, default=list)
    report_due_days: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    plan_version = relationship("MonitoringPlanVersion", back_populates="rules")

    __table_args__ = (Index("ix_ctms_monitoring_rules_version", "plan_version_id", "sort_order"),)


class MonitoringActivity(Base, _MonitoringRecord):
    """Operational monitoring visit/activity linked to canonical EDC records."""

    __tablename__ = "ctms_monitoring_activities"

    plan_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ctms_monitoring_plan_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    activity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    visit_code: Mapped[str | None] = mapped_column(String(40))
    modality: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MonitoringVisitModality.ON_SITE.value
    )
    planned_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_cra_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=MonitoringActivityStatus.PLANNED.value
    )
    edc_visit_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("visit_instances.id", ondelete="RESTRICT"), nullable=True
    )
    completion_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONBType, nullable=False, default=dict
    )
    completion_notes: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    issue_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    issue_reference: Mapped[str | None] = mapped_column(String(255))
    escalation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    escalation_reference: Mapped[str | None] = mapped_column(String(255))

    plan_version = relationship(
        "MonitoringPlanVersion", back_populates="activities", lazy="selectin"
    )
    study = relationship("Study", lazy="selectin")
    site = relationship("Site", lazy="selectin")
    edc_visit_instance = relationship("VisitInstance", lazy="selectin")
    schedule_history = relationship(
        "MonitoringActivityScheduleHistory",
        back_populates="activity",
        order_by="MonitoringActivityScheduleHistory.changed_at",
        cascade="all, delete-orphan",
    )
    checklist_items = relationship(
        "MonitoringVisitActivity",
        back_populates="visit",
        order_by="MonitoringVisitActivity.sort_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    reports = relationship(
        "MonitoringVisitReport",
        back_populates="visit",
        order_by="MonitoringVisitReport.version_number",
        lazy="selectin",
    )
    findings = relationship("MonitoringFinding", back_populates="visit", lazy="selectin")

    __table_args__ = (
        Index("ix_ctms_monitoring_activities_planned_date", "study_id", "planned_date"),
        Index("ix_ctms_monitoring_activities_status", "study_id", "site_id", "status"),
        Index("ix_ctms_monitoring_activities_cra", "assigned_cra_id", "planned_date"),
        Index("ix_ctms_monitoring_activities_edc_visit", "edc_visit_instance_id"),
        Index("ix_ctms_monitoring_activities_plan_version", "plan_version_id"),
    )


class MonitoringVisitActivity(Base, _MonitoringRecord):
    """Evidence-bearing checklist result for one operational monitoring visit."""

    __tablename__ = "ctms_monitoring_visit_activities"

    visit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_monitoring_activities.id", ondelete="RESTRICT"), nullable=False
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ctms_monitoring_rules.id", ondelete="RESTRICT")
    )
    requirement_key: Mapped[str] = mapped_column(String(100), nullable=False)
    requirement: Mapped[str] = mapped_column(Text, nullable=False)
    plan_reference: Mapped[str | None] = mapped_column(String(255))
    result: Mapped[str] = mapped_column(
        String(30), nullable=False, default=MonitoringChecklistResult.PENDING.value
    )
    review_details: Mapped[str | None] = mapped_column(Text)
    observations: Mapped[str | None] = mapped_column(Text)
    subject_reference: Mapped[str | None] = mapped_column(String(255))
    record_reference: Mapped[str | None] = mapped_column(String(255))
    evidence_references: Mapped[list[Any]] = mapped_column(JSONBType, nullable=False, default=list)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    visit = relationship("MonitoringActivity", back_populates="checklist_items")

    __table_args__ = (Index("ix_ctms_monitoring_visit_activities_visit", "visit_id", "sort_order"),)


class MonitoringVisitReport(Base, _MonitoringRecord):
    """Structured, versioned monitoring visit report and approval record."""

    __tablename__ = "ctms_monitoring_visit_reports"

    visit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_monitoring_activities.id", ondelete="RESTRICT"), nullable=False
    )
    previous_report_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ctms_monitoring_visit_reports.id", ondelete="RESTRICT")
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=MonitoringReportStatus.DRAFT.value
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    reviewer_comments: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    controlled_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONBType)
    document_reference: Mapped[str | None] = mapped_column(String(500))

    visit = relationship("MonitoringActivity", back_populates="reports")
    findings = relationship("MonitoringFinding", back_populates="report", lazy="selectin")

    __table_args__ = (
        Index(
            "uq_ctms_monitoring_visit_reports_version",
            "visit_id",
            "version_number",
            unique=True,
        ),
        Index("ix_ctms_monitoring_visit_reports_status", "study_id", "status"),
    )


class MonitoringFinding(Base, _MonitoringRecord):
    """Finding whose lifecycle continues independently from report closure."""

    __tablename__ = "ctms_monitoring_findings"

    finding_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    visit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ctms_monitoring_activities.id", ondelete="RESTRICT")
    )
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ctms_monitoring_visit_reports.id", ondelete="RESTRICT")
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    responsible_party: Mapped[str | None] = mapped_column(String(255))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=MonitoringFindingStatus.OPEN.value
    )
    capa_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capa_reference: Mapped[str | None] = mapped_column(String(255))
    resolution: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closure_reason: Mapped[str | None] = mapped_column(Text)

    visit = relationship("MonitoringActivity", back_populates="findings")
    report = relationship("MonitoringVisitReport", back_populates="findings")
    actions = relationship(
        "MonitoringActionItem",
        back_populates="finding",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_ctms_monitoring_findings_scope", "study_id", "site_id", "status"),
        Index("ix_ctms_monitoring_findings_visit", "visit_id"),
    )


class MonitoringActionItem(Base, _MonitoringRecord):
    """Assigned follow-up action for a monitoring finding."""

    __tablename__ = "ctms_monitoring_action_items"

    finding_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_monitoring_findings.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    responsible_party: Mapped[str | None] = mapped_column(String(255))
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Open")
    completion_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONBType, nullable=False, default=dict
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )

    finding = relationship("MonitoringFinding", back_populates="actions")

    __table_args__ = (
        Index("ix_ctms_monitoring_action_items_finding", "finding_id", "status"),
        Index("ix_ctms_monitoring_action_items_due", "study_id", "due_date", "status"),
    )


class MonitoringActivityScheduleHistory(Base):
    """Append-only operational history for activity scheduling changes."""

    __tablename__ = "ctms_monitoring_activity_schedule_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_monitoring_activities.id", ondelete="RESTRICT"), nullable=False
    )
    previous_planned_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    activity = relationship(
        "MonitoringActivity", back_populates="schedule_history", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_ctms_monitoring_activity_schedule_history_activity", "activity_id", "changed_at"),
    )


@event.listens_for(MonitoringPlanVersion, "before_update")
def _reject_published_version_update(mapper, connection, target) -> None:
    """Reject all edits after publication, while allowing draft publication."""

    state = sqlalchemy_inspect(target)
    status_history = state.attrs.status.history
    publishing_draft = (
        target.status == MonitoringPlanVersionStatus.PUBLISHED.value
        and status_history.has_changes()
        and status_history.deleted
        and status_history.deleted[0] == MonitoringPlanVersionStatus.DRAFT.value
    )
    if target.status == MonitoringPlanVersionStatus.PUBLISHED.value and not publishing_draft:
        raise ValueError("Published monitoring plan versions are immutable")


@event.listens_for(MonitoringPlanVersion, "before_delete")
def _reject_published_version_delete(mapper, connection, target) -> None:
    if target.status == MonitoringPlanVersionStatus.PUBLISHED.value:
        raise ValueError("Published monitoring plan versions are immutable")


@event.listens_for(MonitoringVisitReport, "before_update")
def _reject_finalized_report_update(mapper, connection, target) -> None:
    state = sqlalchemy_inspect(target)
    status_history = state.attrs.status.history
    finalizing = (
        target.status == MonitoringReportStatus.FINALIZED.value
        and status_history.has_changes()
        and status_history.deleted
        and status_history.deleted[0] == MonitoringReportStatus.APPROVED.value
    )
    if target.status == MonitoringReportStatus.FINALIZED.value and not finalizing:
        raise ValueError("Finalized monitoring visit reports are immutable")


@event.listens_for(MonitoringVisitReport, "before_delete")
def _reject_finalized_report_delete(mapper, connection, target) -> None:
    if target.status == MonitoringReportStatus.FINALIZED.value:
        raise ValueError("Finalized monitoring visit reports are immutable")


# Compatibility names used by service/API consumers.
MonitoringPlanVersionRecord = MonitoringPlanVersion
MonitoringVisit = MonitoringActivity

__all__ = [
    "MonitoringActionItem",
    "MonitoringActivity",
    "MonitoringActivityScheduleHistory",
    "MonitoringActivityStatus",
    "MonitoringActivityType",
    "MonitoringChecklistResult",
    "MonitoringFinding",
    "MonitoringFindingSeverity",
    "MonitoringFindingStatus",
    "MonitoringPlan",
    "MonitoringPlanStatus",
    "MonitoringPlanVersion",
    "MonitoringPlanVersionRecord",
    "MonitoringPlanVersionStatus",
    "MonitoringReportStatus",
    "MonitoringRule",
    "MonitoringVisit",
    "MonitoringVisitActivity",
    "MonitoringVisitModality",
    "MonitoringVisitReport",
    "utc_now",
]
