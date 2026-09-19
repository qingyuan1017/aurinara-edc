"""CTMS operational study planning and reporting persistence.

All records in this module reference the canonical EDC ``Study`` by ``study_id``.
They contain CTMS-owned operational data only; no Study_Version or clinical
configuration is copied or writable here.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

JSONBType = JSONB().with_variant(JSON(), "sqlite")


class OperationalStudyStatus(enum.StrEnum):
    """CTMS operational study lifecycle."""

    DRAFT = "Draft"
    PLANNING = "Planning"
    READY = "Ready"
    ACTIVE = "Active"
    ENROLLMENT_CLOSED = "Enrollment Closed"
    SUSPENDED = "Suspended"
    CLOSED = "Closed"


class StudyPlanStatus(enum.StrEnum):
    DRAFT = "Draft"
    ACTIVE = "Active"
    COMPLETED = "Completed"
    ARCHIVED = "Archived"


class EnrollmentPlanStatus(enum.StrEnum):
    DRAFT = "Draft"
    ACTIVE = "Active"
    COMPLETED = "Completed"
    ARCHIVED = "Archived"


class ReadinessCriterionStatus(enum.StrEnum):
    OPEN = "Open"
    MET = "Met"
    WAIVED = "Waived"
    ARCHIVED = "Archived"


class OperationalMilestoneStatus(enum.StrEnum):
    PLANNED = "Planned"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    DELAYED = "Delayed"
    CANCELLED = "Cancelled"


def utc_now() -> datetime:
    return datetime.now(UTC)


class _RetentionFields:
    """Shared archive/soft-delete columns for task-2.2 records."""

    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class _StudyScopedRecord(_RetentionFields):
    """Common fields for CTMS records scoped to one canonical study."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class OperationalStudy(Base):
    """One operational profile for a canonical EDC study."""

    __tablename__ = "ctms_operational_studies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False)
    operational_owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sponsor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phase: Mapped[str | None] = mapped_column(String(50), nullable=True)
    therapeutic_area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    indication: Mapped[str | None] = mapped_column(String(255), nullable=True)
    planning_metadata: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    readiness_criteria: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=OperationalStudyStatus.DRAFT.value)
    retention_state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    study = relationship("Study", lazy="selectin")
    __table_args__ = (
        Index("ix_ctms_operational_studies_status", "study_id", "status"),
        Index("ix_ctms_operational_studies_correlation_id", "correlation_id"),
    )


class StudyPlan(Base, _StudyScopedRecord):
    """CTMS-owned operational study plan."""

    __tablename__ = "ctms_study_plans"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    planning_scope: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=StudyPlanStatus.DRAFT.value)
    study = relationship("Study", lazy="selectin")
    __table_args__ = (Index("ix_ctms_study_plans_study_status", "study_id", "status"),)


class EnrollmentPlan(Base, _StudyScopedRecord):
    """CTMS enrollment planning record; it does not create clinical subjects."""

    __tablename__ = "ctms_enrollment_plans"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    target_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planning_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planning_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planning_scope: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=EnrollmentPlanStatus.DRAFT.value)
    study = relationship("Study", lazy="selectin")
    __table_args__ = (Index("ix_ctms_enrollment_plans_study_status", "study_id", "status"),)


class ReadinessCriterion(Base, _StudyScopedRecord):
    """One operational readiness criterion for a study."""

    __tablename__ = "ctms_readiness_criteria"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ReadinessCriterionStatus.OPEN.value)
    required: Mapped[bool] = mapped_column(nullable=False, default=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    study = relationship("Study", lazy="selectin")
    __table_args__ = (Index("ix_ctms_readiness_criteria_study_status", "study_id", "status"),)


class StudyOperationalMilestone(Base, _StudyScopedRecord):
    """Study-level operational milestone, distinct from subject milestones."""

    __tablename__ = "ctms_study_milestones"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    milestone_type: Mapped[str] = mapped_column(String(100), nullable=False)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=OperationalMilestoneStatus.PLANNED.value)
    study = relationship("Study", lazy="selectin")
    __table_args__ = (Index("ix_ctms_study_milestones_study_status", "study_id", "status"),)


class _SavedQuery(Base, _StudyScopedRecord):
    """Base for minimized operational dashboard/report query definitions."""

    __abstract__ = True
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    query_definition: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Active")


class DashboardQuery(_SavedQuery):
    __tablename__ = "ctms_dashboard_queries"
    study = relationship("Study", lazy="selectin")
    __table_args__ = (Index("ix_ctms_dashboard_queries_study_status", "study_id", "status"),)


class ReportQuery(_SavedQuery):
    __tablename__ = "ctms_report_queries"
    study = relationship("Study", lazy="selectin")
    __table_args__ = (Index("ix_ctms_report_queries_study_status", "study_id", "status"),)


# Compatibility names used by API and service consumers.
OperationalStudyProfile = OperationalStudy
CTMSOperationalStudy = OperationalStudy
OperationalStudyPlan = StudyPlan
OperationalEnrollmentPlan = EnrollmentPlan
OperationalStudyMilestone = StudyOperationalMilestone

__all__ = [
    "CTMSOperationalStudy",
    "DashboardQuery",
    "EnrollmentPlan",
    "EnrollmentPlanStatus",
    "OperationalEnrollmentPlan",
    "OperationalMilestoneStatus",
    "OperationalStudy",
    "OperationalStudyMilestone",
    "OperationalStudyPlan",
    "OperationalStudyProfile",
    "OperationalStudyStatus",
    "ReadinessCriterion",
    "ReadinessCriterionStatus",
    "ReportQuery",
    "StudyOperationalMilestone",
    "StudyPlan",
    "StudyPlanStatus",
    "utc_now",
]
