"""CTMS enrollment targets and operational subject milestones.

The models in this module are operational records only. ``subject_id`` is a
read-only foreign-key reference to the EDC clinical subject; CTMS never copies
or owns the clinical subject identity, binding, visits, forms, or data.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSONBType = JSONB().with_variant(JSON(), "sqlite")


class EnrollmentTargetType(enum.StrEnum):
    """Operational target dimensions supported by CTMS."""

    recruitment = "Recruitment"
    screening = "Screening"
    enrollment = "Enrollment"


class EnrollmentTargetStatus(enum.StrEnum):
    """Lifecycle status of an operational enrollment target."""

    draft = "Draft"
    active = "Active"
    met = "Met"
    expired = "Expired"
    cancelled = "Cancelled"


class OperationalSubjectStatus(enum.StrEnum):
    """CTMS operational subject progress statuses.

    These values intentionally mirror the approved operational vocabulary, but
    assigning one here does not transition the EDC ``Subject`` row.
    """

    screening = "Screening"
    screen_failed = "Screen Failed"
    enrolled = "Enrolled"
    randomized = "Randomized"
    on_treatment = "On Treatment"
    completed = "Completed"
    early_terminated = "Early Terminated"
    lost_to_follow_up = "Lost to Follow-up"
    withdrawn = "Withdrawn"


class EnrollmentTarget(Base):
    """A CTMS-owned planned recruitment, screening, or enrollment quantity."""

    __tablename__ = "ctms_enrollment_targets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=True
    )
    target_type: Mapped[EnrollmentTargetType] = mapped_column(String(20), nullable=False)
    target_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    planning_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    planning_period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    dimension: Mapped[dict[str, Any]] = mapped_column(
        JSONBType, nullable=False, default=dict
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[EnrollmentTargetStatus] = mapped_column(
        String(20), nullable=False, default=EnrollmentTargetStatus.draft
    )
    retention_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active"
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    retention_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    deletion_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index(
            "ix_ctms_enrollment_targets_scope_period",
            "study_id",
            "site_id",
            "target_type",
            "planning_period_start",
            "planning_period_end",
        ),
        Index("ix_ctms_enrollment_targets_status", "study_id", "status"),
    )


class OperationalMilestone(Base):
    """An operational milestone linked to one canonical EDC subject."""

    __tablename__ = "ctms_operational_milestones"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=True
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    approved_pseudonym: Mapped[str | None] = mapped_column(String(255))
    approved_reference: Mapped[str | None] = mapped_column(String(255))
    milestone_type: Mapped[str] = mapped_column(String(100), nullable=False)
    milestone_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[OperationalSubjectStatus] = mapped_column(
        String(30), nullable=False, default=OperationalSubjectStatus.screening
    )
    retention_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active"
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    retention_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    deletion_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_ctms_operational_milestones_subject", "subject_id", "milestone_date"),
        Index("ix_ctms_operational_milestones_scope", "study_id", "site_id", "status"),
    )


# Compatibility alias matching the specification terminology.
OperationalSubjectMilestone = OperationalMilestone

__all__ = [
    "EnrollmentTarget",
    "EnrollmentTargetStatus",
    "EnrollmentTargetType",
    "OperationalMilestone",
    "OperationalSubjectMilestone",
    "OperationalSubjectStatus",
]
