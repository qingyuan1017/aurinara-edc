"""PV regulatory reporting persistence (Phase 3).

This module backs reportability evaluation, expedited ``Regulatory_Clocks``, and
the ``Regulatory_Report`` status state machine (Requirement 8). A
``ReportabilityRule`` is PV-owned configuration that maps a matched Safety_Case
to a report type and destination. Reportability evaluation creates one
``RegulatoryReport`` per matched rule, each ``Pending`` with a
``RegulatoryClock`` whose due date is a pure function of the Awareness_Date and
the configured whole-day timeline (constrained to 1-90 inclusive).

E2B produce/parse and the ``E2B_Message`` payload land in task 4.3. This module
stores only the submitted ``e2b_message_ref`` string recorded when a report is
marked ``Submitted`` (Requirement 8.7).

Every record uses a UUID primary key, UTC ``TIMESTAMPTZ`` columns,
actor/correlation metadata, and soft-deletion/retention columns from
:mod:`app.models.pv.common`. Reports reference the PV-owned ``pv_safety_cases``
root and never create, allocate, or mutate an EDC clinical or CTMS operational
record.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.pv.common import PVBase

# Partial-index predicate that excludes soft-deleted rows (Requirement 17.5).
_NOT_DELETED = text("deleted_at IS NULL")

# The configured reporting timeline is a whole number of calendar days between
# 1 and 90 inclusive (Requirement 8.3).
TIMELINE_DAYS_MIN = 1
TIMELINE_DAYS_MAX = 90


class ReportStatus(enum.StrEnum):
    """Regulatory_Report status values (mirrors :class:`app.core.pv.ReportStatus`)."""

    PENDING = "Pending"
    SUBMITTED = "Submitted"
    ACKNOWLEDGED = "Acknowledged"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"


_REPORT_STATUS_VALUES = "','".join(status.value for status in ReportStatus)


class ReportabilityRule(PVBase):
    """PV-owned configuration mapping a matched Safety_Case to a report.

    A rule names the report ``report_type`` and ``destination`` produced when the
    rule matches, and the whole-day expedited ``timeline_days`` used to compute
    the Regulatory_Clock due date. ``timeline_days`` is constrained to 1-90
    inclusive (Requirement 8.3). Rules are additive PV configuration; they never
    reference or mutate EDC/CTMS records.
    """

    __tablename__ = "pv_reportability_rules"

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    report_type: Mapped[str] = mapped_column(String(100), nullable=False)
    destination: Mapped[str] = mapped_column(String(100), nullable=False)
    timeline_days: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)

    __table_args__ = (
        CheckConstraint(
            f"timeline_days BETWEEN {TIMELINE_DAYS_MIN} AND {TIMELINE_DAYS_MAX}",
            name="ck_pv_reportability_rules_timeline_days",
        ),
        Index(
            "ix_pv_reportability_rules_study",
            "study_id",
            "active",
            postgresql_where=_NOT_DELETED,
        ),
    )


class RegulatoryReport(PVBase):
    """One expedited Regulatory_Report for a Safety_Case and matched rule.

    A report is created ``Pending`` per matched configured rule with a
    ``report_type`` and ``destination`` (Requirements 8.1, 8.2). It records the
    ``awareness_date`` used to compute its clock; a report cannot be created
    without an Awareness_Date (Requirement 8.4). When marked ``Submitted`` the
    report records the submitting actor, the UTC submission timestamp, and the
    submitted ``e2b_message_ref`` (Requirement 8.7).
    """

    __tablename__ = "pv_regulatory_reports"

    case_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pv_safety_cases.id", ondelete="RESTRICT"), nullable=False
    )
    rule_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("pv_reportability_rules.id", ondelete="RESTRICT"), nullable=True
    )
    report_type: Mapped[str] = mapped_column(String(100), nullable=False)
    destination: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReportStatus.PENDING.value
    )
    awareness_date: Mapped[date] = mapped_column(Date, nullable=False)

    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    e2b_message_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    clock: Mapped[RegulatoryClock] = relationship(
        "RegulatoryClock",
        back_populates="report",
        uselist=False,
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ('{_REPORT_STATUS_VALUES}')",
            name="ck_pv_regulatory_reports_status",
        ),
        Index(
            "ix_pv_regulatory_reports_case",
            "case_id",
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_regulatory_reports_status",
            "status",
            postgresql_where=_NOT_DELETED,
        ),
    )


class RegulatoryClock(PVBase):
    """The expedited Regulatory_Clock for one Regulatory_Report.

    ``due_date = awareness_date + timedelta(days=timeline_days)`` counting whole
    calendar days in UTC where the Awareness_Date is day zero (Requirement 8.3).
    ``timeline_days`` is constrained to 1-90 inclusive.
    """

    __tablename__ = "pv_regulatory_clocks"

    report_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pv_regulatory_reports.id", ondelete="RESTRICT"), nullable=False
    )
    awareness_date: Mapped[date] = mapped_column(Date, nullable=False)
    timeline_days: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    report: Mapped[RegulatoryReport] = relationship(
        "RegulatoryReport", back_populates="clock", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            f"timeline_days BETWEEN {TIMELINE_DAYS_MIN} AND {TIMELINE_DAYS_MAX}",
            name="ck_pv_regulatory_clocks_timeline_days",
        ),
        Index(
            "uq_pv_regulatory_clocks_report",
            "report_id",
            unique=True,
            postgresql_where=_NOT_DELETED,
        ),
    )


__all__ = [
    "TIMELINE_DAYS_MAX",
    "TIMELINE_DAYS_MIN",
    "RegulatoryClock",
    "RegulatoryReport",
    "ReportStatus",
    "ReportabilityRule",
]
