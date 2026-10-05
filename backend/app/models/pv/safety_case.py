"""PV safety case intake, capture, and versioning persistence (Phase 1).

All records reference canonical Study/Site identity and the EDC
``Subject_Reference``. No PV table copies a clinical payload, and no PV table
creates, allocates, or mutates an EDC clinical subject record. Every record
uses a UUID primary key, UTC ``TIMESTAMPTZ`` columns, study/site scope,
actor/correlation metadata, and soft-deletion/retention columns provided by
:mod:`app.models.pv.common`.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.pv.common import PVBase

JSONBType = JSONB().with_variant(JSON(), "sqlite")

# Partial-index predicate that excludes soft-deleted rows (Requirement 17.5).
_NOT_DELETED = text("deleted_at IS NULL")


class CaseState(enum.StrEnum):
    """PV safety case lifecycle states."""

    OPEN = "Open"
    IN_REVIEW = "In Review"
    FOLLOW_UP_REQUIRED = "Follow-up Required"
    READY_TO_REPORT = "Ready to Report"
    REPORTED = "Reported"
    CLOSED = "Closed"
    REOPENED = "Reopened"


class CaseVersionKind(enum.StrEnum):
    """Whether a Case_Version is the initial submission or a follow-up."""

    INITIAL = "Initial"
    FOLLOW_UP = "Follow-up"


class CaseVersionStatus(enum.StrEnum):
    """Lifecycle of a captured Case_Version snapshot."""

    DRAFT = "Draft"
    SUBMITTED = "Submitted"


_CASE_STATE_VALUES = "','".join(state.value for state in CaseState)
_VERSION_KIND_VALUES = "','".join(kind.value for kind in CaseVersionKind)
_VERSION_STATUS_VALUES = "','".join(status.value for status in CaseVersionStatus)


class SafetyCase(PVBase):
    """A PV safety case: the system-of-record root for one safety event.

    ``case_identifier`` is globally unique across the Unified_Clinical_Platform.
    ``study_id``/``site_id`` reference canonical identity and ``subject_reference``
    references the EDC clinical subject identity read-only.
    """

    __tablename__ = "pv_safety_cases"

    case_identifier: Mapped[str] = mapped_column(String(100), nullable=False)
    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
    )
    subject_reference: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    case_type: Mapped[str] = mapped_column(String(100), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default=CaseState.OPEN.value
    )

    adverse_events: Mapped[list[AdverseEventRecord]] = relationship(
        "AdverseEventRecord", back_populates="case", lazy="selectin"
    )
    versions: Mapped[list[CaseVersion]] = relationship(
        "CaseVersion", back_populates="case", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            f"lifecycle_state IN ('{_CASE_STATE_VALUES}')",
            name="ck_pv_safety_cases_lifecycle_state",
        ),
        # Globally unique safety case identifier (Requirements 3.2, 17.4).
        Index(
            "uq_pv_safety_cases_case_identifier",
            "case_identifier",
            unique=True,
        ),
        # Queryable indexes (Requirement 17.5), partial to exclude soft-deleted rows.
        Index(
            "ix_pv_safety_cases_study",
            "study_id",
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_safety_cases_site",
            "site_id",
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_safety_cases_subject_reference",
            "subject_reference",
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_safety_cases_status",
            "study_id",
            "lifecycle_state",
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_safety_cases_created_at",
            "created_at",
            postgresql_where=_NOT_DELETED,
        ),
    )


class AdverseEventRecord(PVBase):
    """One adverse event captured under a Safety_Case.

    ``verbatim_term`` is 1-200 characters and ``resolution_date`` is persisted
    only when it is no earlier than ``onset_date`` (enforced by the service and a
    database check constraint).
    """

    __tablename__ = "pv_adverse_event_records"

    case_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pv_safety_cases.id", ondelete="RESTRICT"), nullable=False
    )
    verbatim_term: Mapped[str] = mapped_column(String(200), nullable=False)
    onset_date: Mapped[date] = mapped_column(Date, nullable=False)
    outcome: Mapped[str] = mapped_column(String(100), nullable=False)
    resolution_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    case: Mapped[SafetyCase] = relationship(
        "SafetyCase", back_populates="adverse_events", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "length(verbatim_term) BETWEEN 1 AND 200",
            name="ck_pv_adverse_event_records_verbatim_length",
        ),
        CheckConstraint(
            "resolution_date IS NULL OR resolution_date >= onset_date",
            name="ck_pv_adverse_event_records_resolution_after_onset",
        ),
        Index(
            "ix_pv_adverse_event_records_case",
            "case_id",
            postgresql_where=_NOT_DELETED,
        ),
    )


class CaseVersion(PVBase):
    """An initial or follow-up Case_Version.

    ``sequence_number`` is 1 for the initial version and ``max + 1`` for each
    follow-up. Once ``Submitted`` the ``captured_content`` snapshot is immutable
    and no submitted version is deleted or overwritten.
    """

    __tablename__ = "pv_case_versions"

    case_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pv_safety_cases.id", ondelete="RESTRICT"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CaseVersionStatus.DRAFT.value
    )
    captured_content: Mapped[dict[str, Any]] = mapped_column(
        JSONBType, nullable=False, default=dict
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason_for_change: Mapped[str | None] = mapped_column(Text, nullable=True)

    case: Mapped[SafetyCase] = relationship(
        "SafetyCase", back_populates="versions", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            f"version_kind IN ('{_VERSION_KIND_VALUES}')",
            name="ck_pv_case_versions_version_kind",
        ),
        CheckConstraint(
            f"status IN ('{_VERSION_STATUS_VALUES}')",
            name="ck_pv_case_versions_status",
        ),
        CheckConstraint(
            "sequence_number >= 1",
            name="ck_pv_case_versions_sequence_number",
        ),
        CheckConstraint(
            "reason_for_change IS NULL OR length(reason_for_change) <= 4000",
            name="ck_pv_case_versions_reason_length",
        ),
        # One sequence number per case among live versions.
        Index(
            "uq_pv_case_versions_case_sequence",
            "case_id",
            "sequence_number",
            unique=True,
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_case_versions_case",
            "case_id",
            "status",
            postgresql_where=_NOT_DELETED,
        ),
    )


__all__ = [
    "AdverseEventRecord",
    "CaseState",
    "CaseVersion",
    "CaseVersionKind",
    "CaseVersionStatus",
    "SafetyCase",
]
